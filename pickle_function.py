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

# These are the attrs of types.FuncType that aren't arguments to the
# constructor (they are mutable and we copy them separately).
_FUNC_ATTRS = (
    '__dict__',
    '__kwdefaults__',
    '__module__',
    '__qualname__',
)


class Pickler(pickle._Pickler):
    """A pickler that can save lambdas, inline functions, and other garbage.

    GENERAL NOTE: Lots of the things we pickle can be recursive, which requires
    some care to handle.  In general, pickling an object looks like:
    0. check if the object is in the memo, and if so use that
    1. pickle the object's members/args/items/...
    2. build the object from them, put it in the memo
    Whenever an object (directly or indirectly) may reference itself, we need
    to do one of two things:
    A. In between steps 1 and 2, repeat step 0, in case step 1 indirectly
       pickled the object.  (Additionally before we use the object in the memo,
       we need to pop whatever we added in step 1.)
    B. Instead of steps 1 and 2, do:
       1. build an empty object, put it in the memo
       2. pickle the object's members/items/...
       3. set those members/items/... on the object

    Now, B is not always possible, if the object is immutable, or some of the
    arguments/... are needed at init-time.  But A is insufficient on its own:
    we need to do B for *some* object that participates in the cycle, because
    otherwise step 1 is already infinitely recursive, and we never even get to
    the second version of step 0.  (As long as there's a B somewhere, its step
    2 will not be infinitely recursive, since that object is already in the
    memo.)

    Luckily, we can always solve those constraints, by just doing A whenever
    necessary and B everywhere else.  We can't have a cycle only among
    immutable objects (or those arguments/attrs needed at init-time) because
    it's impossible to create, so there must be some mutable object (or attr)
    that will use B.

    So, for example, if you have a recursive non-module-scoped function, then
    we have a cycle like:
        f.__closure__ = (types.CellType(cell_contents=f),)
    Now f.__closure__ is an immutable attribute of f; and f.__closure__ is
    itself a tuple (thus immutable), but cells are mutable -- and they need to
    be, exactly so that it's possible to write this function!  So we can do
    option A above for functions (except see below) and tuples, but do option B
    for cells.  Then when pickling f, we will:
    0. check if f is in the memo; it's not
    1. pickle f's closure (and other attrs, omitted for simplicity):
        0. check if f.__closure__ is in the memo; it's not
        1. pickle f.__closure__'s item:
            0. check if f.__closure__[0] is in the memo; it's not
            1. create an empty cell, put it in the memo
            2. pickle the cell's member, f:
                0. check if f is in the memo; it's not
                1. pickle f's closure (and other attrs, omitted):
                    0. check if f.__closure__ is in the memo; it's not
                    1. pickle f.__closure__'s item, a cell:
                        0. check if f.__closure__[0] is in the memo; it is!
                           so return it.
                    0. check, again, if f.__closure__ is in the memo; it's not
                    2. build f.__closure__ from its items
                0. check, again, if f is in the memo; it's not
                2. build f from its closure (and other attrs)
            3. set f.cell_contents = f
        0. check, again, if f.__closure__ is in the memo; this time it is!
           so return it.
    0. check, again, if f is in the memo; this time it is!  so return it.

    Note that if we didn't do A with f or f.__closure__, we'd mostly not
    overflow the stack.  But we'd end up with two copies of f floating around.
    And if we didn't do B with the cell, we'd recurse infinitely before putting
    anything in the memo!

    Note also that in reality, some types, like functions, have a mix of
    mutable and immutable attributes; for example f.__closure__ is read-only
    after creation, but f.__kwdefaults__ can be set later.  So in such cases we
    we do some of both: we pickle the immutable attributes, check if we've
    pickled f, build f with just the immutable attributes, add it to the memo,
    then pickle and set the mutable attributes.

    See also the comments starting "Subtle." in stdlib's save_tuple.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # We keep a global map of function -> its globals-map, so that when we
        # pickle recursive functions the object-identity works right w/r/t the
        # pickled version's globals map.  This is necessary because we don't
        # actually pickle all of f.__globals__, just the parts f is likely to
        # need.
        # TODO: once we can pickle modules, revisit that; maybe we should just
        # pickle all of it, in which case we can probably back this out.  That
        # would make for very large pickles, but would also make code that
        # looks at `globals()` work right.  Or, we could look at depickling in
        # caller's globals.  It's not clear to me which is more correct.
        self.function_globals = {}

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

    def _get_obj(self, obj):
        """Write the opcodes to get obj from the memo."""
        self.write(self.get(self.memo[id(obj)][0]))

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

        co_names = set(obj.__code__.co_names)
        globals_dict = self.function_globals.get(id(obj))
        if globals_dict is None:
            # Only pickle globals we actually need, to save size and reduce the
            # chances that some weird object somewhere in the codebase crashes
            # us.
            # TODO: revisit once we can pickle modules and such.
            globals_dict = {
                k: v for k, v in obj.__globals__.items()
                            if k in co_names
                            # co_names can also refer to a name from
                            # __builtins__, which is the builtins module's
                            # dict, so we need to save that too.  Luckily even
                            # normal-pickle knows how to pickle everything
                            # that's normally there, so we don't bother to
                            # filter.
                            # But if we are in __main__, __builtins__ is the
                            # actual module, not its dict [1], in which case we
                            # don't want to do that (although maybe we can once
                            # we know how to pickle modules).
                            # [1] https://docs.python.org/3/reference/executionmodel.html#builtins-and-restricted-execution   # noqa:L501
                            or k == '__builtins__' and isinstance(v, dict)}
            self.function_globals[id(obj)] = globals_dict

        self._save_global_name('types.FunctionType')
        self.save((obj.__code__, globals_dict, obj.__name__,
                   obj.__defaults__, obj.__closure__))
        # Handle recursive functions (we can have self-references via
        # __globals__, __closure__, or via the items of __defaults__).
        # See module docstring for more.
        memoed = self.memo.get(id(obj))
        if memoed is not None:
            self.write(pickle.POP + self.get(memoed[0]))
            return

        # Now build the function itself.
        self.write(pickle.REDUCE)
        self.memoize(obj)

        # Fix up mutable args that aren't in the constructor.
        self._setattrs({k: getattr(obj, k) for k in _FUNC_ATTRS})

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

        # TODO: can anything in a code-type be recursive?  It doesn't seem like
        # it but it's hard to be sure.
        # memoed = self.memo.get(id(obj))
        # if memoed is not None:
        #     self.write(pickle.POP + self.get(memoed[0]))
        #     return

        self.write(pickle.REDUCE)
        self.memoize(obj)

    dispatch[types.CodeType] = save_code

    def _setattrs(self, d):
        """Set all attrs in the dict d on the object on top of the stack.

        This writes opcodes roughly equivalent to `obj.__dict__.update(d)`,
        except they work right for slots.
        """
        # Normally, BUILD takes a dict, state, and does basically
        #   obj.__dict__.update(state)
        # But to handle __slots__, it also allows a pair (state, slotstate),
        # and does setattrs for the elements of slotstate.  We just do that
        # always because it's easier than figuring out which one is right.
        self.save((None, d))
        self.write(pickle.BUILD)

    def save_cell(self, obj, name=None):
        """A saver for types.CellType, which is used for closures.

        Specifically, this is the type of elements of func.__closure__.

        Like save_function, this has to hook in to the internal dispatch.
        """
        memoed = self.memo.get(id(obj))
        if memoed is not None:
            self.write(self.get(memoed[0]))
            return

        # Handle recursive functions; this is where we break the cycle (see
        # module doc, where this is option B).
        self._save_global_name('types.CellType')
        self.save(())
        self.write(pickle.REDUCE)
        self.memoize(obj)

        self._setattrs({'cell_contents': obj.cell_contents})

    dispatch[types.CellType] = save_cell


def dumps(obj, protocol=None, *, fix_imports=True):
    assert protocol is None or protocol >= 2
    # cribbed from pickle.dumps:
    f = io.BytesIO()
    Pickler(f, protocol, fix_imports=fix_imports).dump(obj)
    res = f.getvalue()
    assert isinstance(res, pickle.bytes_types)
    return res
