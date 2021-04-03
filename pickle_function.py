#!/usr/bin/env python3
# Tested in Python 3.9.  This uses a lot of internals, so it may break in
# earlier or later versions!
import io
import pickle
import types


# TODO:
# - generators, coroutines, async generators
# - classes, various types of methods
# - modules


# These are in the order of the types.CodeType constructor.  See also
# https://github.com/python/cpython/blob/3.9/Objects/codeobject.c#L117
_CODE_ATTRS = (
    'co_argcount',
    'co_posonlyargcount',
    'co_kwonlyargcount',
    'co_nlocals',
    'co_stacksize',
    'co_flags',
    'co_code',
    'co_consts',
    'co_names',
    'co_varnames',
    'co_filename',
    'co_name',
    'co_firstlineno',
    'co_lnotab',
    'co_freevars',
    'co_cellvars')
# We can't check that the order is correct (the constructor is in C so we can't
# introspect it) but we can check that the set is correct.
assert set(_CODE_ATTRS) == {attr for attr in dir(types.CodeType)
                            if attr.startswith('co_')}


class Pickler(pickle._Pickler):
    """A pickler that can save lambdas, inline functions, and other garbage."""
    def _save_global_name(self, name):
        """Saves the global with the given name.

        This is like save_global, but it works for values of type
        types.BuildinMethodType (i.e. anything defined in C) which
        don't live in __builtins__, such as types.FunctionType.
        """
        module, name = name.rsplit('.', 1)
        self.save(module)
        self.save(name)
        self.write(pickle.STACK_GLOBAL)

    dispatch = pickle._Pickler.dispatch.copy()

    def save_function(self, obj):
        """An improved version of save_global that can save functions.

        We delegate to ordinary save_global when we can, but then do our
        garbage hackery when we can't.

        Note that this has to hook directly into dispatch, rather than the
        intended extension points like dispatch_table or copyreg, for two
        reasons:
        1. Pickle thinks it already knows how to handle FunctionType, and we
           want to override that builtin handling.  (This does not apply to
           CodeType.)
        2. We need the internal semantics of save_foo (which writes opcodes
           directly) rather than __reduce__-like semantics exposed by
           dispatch_table (where we return a constructor and some arguments).
           This is because pickle doesn't know how to pickle our constructor
           (types.FunctionType): we need to use _save_global_name.  (This
           applies equally to CodeType.)
           TODO: could we avoid this limitation by special-casing the
           constructor itself in save_global, and then handling the rest
           normally?
        """
        # TODO: flag to allow using the below, for e.g. stdlib functions we
        # can't pickle (will there be any????)
        # try:
        #     return self.save_global(obj)
        # except Exception:
        #     if type(obj) != types.FunctionType:   # noqa:E721
        #         raise

        memoed = self.memo.get(id(obj))
        if memoed is not None:
            self.write(self.get(memoed[0]))
            return

        self._save_global_name('types.FunctionType')
        co_names = set(obj.__code__.co_names)
        globals_dict = {}
        # To handle recursive functions at module scope (where f's
        # implementation gets f from f.__globals__), we need to do a similar
        # trick to the one with cells below (see save_cell).
        #
        # For more on all this recursive stuff, see also the comments starting
        # "Subtle." in stdlib's save_tuple.
        self.save((obj.__code__, globals_dict, obj.__name__,
                   obj.__defaults__, obj.__closure__))
        # We also need to early-out for non-module-scope recursive functions
        # (where the self-reference is in obj.__closure__); in that case the
        # cycle gets broken in save_cell, so we have already been pickled by
        # the time we get there.  So instead of proceeding, we need to pop this
        # tuple, and return that.
        memoed = self.memo.get(id(obj))
        if memoed is not None:
            self.write(pickle.POP + self.get(memoed[0]))
            return

        # Now build the function itself.
        self.write(pickle.REDUCE)
        # TODO: need to fix up __kwdefaults__ and potentially __dict__ -- can
        # probably just call _batch_setitems.
        self.memoize(obj)

        # Finally, we have to find the globals in the memo, and fix them up.
        self.write(self.get(self.memo[id(globals_dict)][0]))
        # Only pickle globals we actually need, to save size and reduce the
        # chances that some weird object somewhere in the codebase crashes us.
        relevant_globals = {k: v for k, v in obj.__globals__.items()
                            # co_names can also refer to a name from
                            # __builtins__, so we need to save that too.
                            # Luckily even normal-pickle knows how to pickle
                            # everything that's normally there, so we don't
                            # bother to filter.
                            if k in co_names or k == '__builtins__'}
        self._batch_setitems(relevant_globals.items())
        # Get the function back on top of the stack.
        self.write(pickle.POP)

    dispatch[types.FunctionType] = save_function

    def save_code(self, obj, name=None):
        """A saver for types.CodeType, which is the function's code.

        Like save_function, this has to hook in to the internal dispatch.
        """
        memoed = self.memo.get(id(obj))
        if memoed is not None:
            self.write(self.get(memoed[0]))
            return

        self._save_global_name('types.CodeType')
        self.save(tuple(getattr(obj, attr) for attr in _CODE_ATTRS))

        # Same case with recursive functions as in save_function.
        # TODO: is this actually necessary?  maybe to get code-object identity
        # right, not that it really matters?
        memoed = self.memo.get(id(obj))
        if memoed is not None:
            self.write(pickle.POP + self.get(memoed[0]))
            return

        self.write(pickle.REDUCE)
        self.memoize(obj)

    dispatch[types.CodeType] = save_code

    def save_cell(self, obj, name=None):
        """A saver for types.CellType, which is used for closures.

        Specifically, this is the type of elements of func.__closure__.

        Like save_function, this has to hook in to the internal dispatch.
        """
        memoed = self.memo.get(id(obj))
        if memoed is not None:
            self.write(self.get(memoed[0]))
            return

        # To make recursive functions not at module scope work, we need to
        # break the recursive cycle somewhere.  (For module-scoped functions,
        # it gets broken when we serialize the globals dict, I think.)  For
        # recursion via closures, this is that somewhere, because cells are
        # nice and mutable!  So we init the cell, and set its contents later.
        self._save_global_name('types.CellType')
        self.save(())
        self.write(pickle.REDUCE)
        self.memoize(obj)

        # Normally, BUILD takes a dict, state, and does basically
        #   obj.__dict__.udpate(state)
        # But to handle __slots__, it also allows a pair (state, slotstate),
        # and does setattrs for the elements of slotstate.
        self.save((None, {'cell_contents': obj.cell_contents}))
        self.write(pickle.BUILD)

    dispatch[types.CellType] = save_cell


def dumps(obj, protocol=None, *, fix_imports=True):
    assert protocol is None or protocol >= 2
    # cribbed from pickle.dumps:
    f = io.BytesIO()
    Pickler(f, protocol, fix_imports=fix_imports).dump(obj)
    res = f.getvalue()
    assert isinstance(res, pickle.bytes_types)
    return res
