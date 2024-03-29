#!/usr/bin/env python3
# Tested in Python 3.9.  This uses a lot of internals, so it may break in
# earlier or later versions!
import _collections_abc
import importlib
import importlib.machinery
import io
import pickle
import sys
import types


# known-ish TODO:
# - modules
#   - do we need to handle __loader__, __package__, __spec__?
# - can we simpplify our control flow re save_global etc. as a
#   reducer_override?
#   https://docs.python.org/3/library/pickle.html#custom-reduction-for-types-functions-and-other-objects
# - fuzz-test by pickling real modules/functions/etc.
# - blog post:
#   - intro/problem-statement
#   - what is a function, and the basic (non-recursive/ignoring globals) method
#   - recursion is a mess
#   - don't use this (but read the code), maybe don't use pickle either
#
# Open problems:
# - generators, async generators, and coroutines -- unclear if it's possible to
#   init from Python; maybe make an iterable that fakes them (sad)?
# - custom __prepare__ or metaclass arguments


# Arguments (in order) to the types.CodeType constructor.  See also
# https://github.com/python/cpython/blob/3.9/Objects/codeobject.c#L117
_CODE_ARGS = (
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

# Arguments (in order) to the types.FunctionType constructor.
_FUNC_ARGS = (
    '__code__',
    '__globals__',
    '__name__',
    '__defaults__',
    '__closure__',
)

# Interesting attributes of types.FunctionType that aren't arguments to the
# constructor (they are mutable and we copy them separately).
_FUNC_ATTRS = {
    '__annotations__',
    '__dict__',
    '__kwdefaults__',
    '__module__',
    '__qualname__',
    # Note __doc__ is actually only needed when set explicitly (which in
    # practice happens with things like @functools.wraps); the FunctionType
    # constructor initializes it [1] as f.__code__.co_consts[0], so if you
    # define it the normal way that happens on the other side too.  Anyway it's
    # easier to just explicitly pickle it than to worry about all that.
    # [1] https://github.com/python/cpython/blob/cbfa09b70b745c9d7393c03955600f6d1cf019e3/Objects/funcobject.c#L56    # noqa:L501
    '__doc__',
}

# Like _FUNC_ATTRS, but for types.
_TYPE_ATTRS = {
    '__qualname__',
    # Attributes you might think we need (e.g. from
    # pickle_util.interesting_attrs) that we don't:
    # Included in __dict__:
    # '__doc__',
    # '__module__',
    # CPython implementation details, read-only:
    # '__abstractmethods__',
    # '__base__',
    # '__basicsize__',
    # '__dictoffset__',
    # '__flags__',
    # '__itemsize__',
    # '__mro__',
    # '__text_signature__',
    # '__weakrefoffset__',
    # Constructor arguments:
    # '__bases__',
    # '__dict__',
    # '__name__',
}


_TRUE_NAMES = {
    '_thread.LockType',
    'threading.ExceptHookArgs',
    'weakref.ref',
    'weakref.ProxyType',
    'weakref.CallableProxyType',
    'functools._lru_cache_wrapper',
} | {
    'types.%s' % name for name in types.__all__
} | {
    # Not everything we want is in __all__...
    '_collections_abc.%s' % name for name in _collections_abc.__dict__
}


_TYPE_TO_TRUE_NAME = {}
for name in _TRUE_NAMES:
    module_name, symbol_name = name.rsplit('.', 1)
    module = importlib.import_module(module_name)
    symbol = getattr(module, symbol_name)
    if isinstance(symbol, type):
        _TYPE_TO_TRUE_NAME[symbol] = name


def _type_is_C(cls):
    """Return true if the type is defined in C.

    Types (and functions) defined in C are some of the few truly unpicklable
    objects!  At least, as yet....

    For functions, it's easy to tell:
        type(f) == types.FunctionType
    means you're a Python function (builtins and C functions have type
    types.BuiltinFunctionType or types.BuiltinMethodType or whatnot).  But for
    classes, it's surprisingly hard.  We crib from this SO answer:
        https://stackoverflow.com/a/60953150
    """
    modulename = cls.__module__
    if modulename in (
            # Don't try to get smart with builtins:
            'builtins',
            # Nor quasi-builtins:
            '_frozen_importlib', 'importlib.abc', '_sitebuiltins', 'types',
            # Contain some builtins, and very system-specific anyway:
            'os', 'sys', 'signal',
            # TODO: figure out how to pickle weakrefs; until such time treat
            # them as builtins.
            'weakref', 'unittest.main', 'unittest.signals',
            # TODO: figure out how to pickle typing.Gneric.__class_getitem__
            'typing',
    ):
        return True

    module = sys.modules.get(modulename)
    if not isinstance(module, types.ModuleType):
        return True

    if isinstance(getattr(module, '__loader__', None),
                  importlib.machinery.ExtensionFileLoader):
        return False

    if getattr(cls, '__slots__', None) is None:
        for k, v in cls.__dict__.items():
            # member/slot descriptors should go with __slots__ (I think?), if
            # they don't, that seems to mean a type with both C and Python
            # implementations where the C implementation doesn't bother to fake
            # __slots__.
            if isinstance(v, (types.MemberDescriptorType,
                              types.WrapperDescriptorType)):
                return True

    filename = getattr(module, '__file__', None)
    if filename is None:
        return True
    return filename.endswith(tuple(importlib.machinery.EXTENSION_SUFFIXES))


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

    dispatch = pickle._Pickler.dispatch.copy()

    def _get_obj(self, obj):
        """Write the opcodes to get obj from the memo."""
        self.write(self.get(self.memo[id(obj)][0]))

    def save_function(self, obj):
        """An "improved" version of save_global that can save functions.

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

        # Figure out the args to the FunctionType constructor.
        args = [getattr(obj, arg_name) for arg_name in _FUNC_ARGS]

        # We specially handle the globals-dict.
        co_names = set(obj.__code__.co_names)
        globals_dict = self.function_globals.get(id(obj))
        if globals_dict is None:
            # Only pickle globals we actually need, to save size and reduce the
            # chances that some weird object somewhere in the codebase crashes
            # us.
            # TODO: revisit once we can pickle modules and such.
            globals_dict = {k: v for k, v in obj.__globals__.items()
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
        args[_FUNC_ARGS.index('__globals__')] = globals_dict

        # Save the function!
        self._save_global_name('types.FunctionType')
        self.save(tuple(args))
        # Handle recursive functions (we can have self-references via
        # __globals__, __closure__, or via the items of __defaults__).
        # See class docstring for more.
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

    def save_global(self, obj, name=None):
        """Wires up save_type.

        You might expect that we would wire up save_type like upstream does,
        and like we do for save_function, namely:
            dispatch[type] = save_type
        But this doesn't work for types with (nontrivial) metaclasses: we'd end
        up looking for `dispatch[<metaclass>]` which is of course not set.
        Luckily, upstream already checks for this case in save(), and calls
        directly to save_global for objects whose type isn't in dispatch but
        inherits from type.  We want to apply our usual nonsense to that call,
        so we override save_global to do that.
        """
        cls = type(obj)
        if name is not None:
            # __reduce__ can return a string, which means, "save me as this
            # global name"; respect that by delegating to upstream.
            super().save_global(obj, name)
        elif issubclass(cls, type):
            # TODO: flag to try/except this for all types:
            if _type_is_C(obj):
                name = _TYPE_TO_TRUE_NAME.get(obj)
                if name is not None:
                    return self._save_global_name(name)
                # C types we give up and save as globals.  (I mean, we could
                # try to serialize the .so, but, even more yikes.)
                return super().save_global(obj)
            # Else, do our magic.
            self._save_type(obj)
        else:
            # (Should never happen, unless upstream changed.)
            raise pickle.PicklingError(
                "Unexpected type passed to save_global: %s" % cls)

    def _save_type(self, cls):
        """Saves a user-defined type.

        This is generally like save_function.  We don't bother wiring it in as
        dispatch[type] because upstream's save_type basically just calls
        save_global, which we need to override to call us anyway.
        """
        memoed = self.memo.get(id(cls))
        if memoed is not None:
            self.write(self.get(memoed[0]))
            return

        slots = getattr(cls, '__slots__', ())
        # Apparently `__slots__ = "the_slot"` is legal???
        if isinstance(slots, str):
            slots = (slots,)
        elif not isinstance(slots, tuple):  # an iterable, I hope
            slots = tuple(slots)

        # Else, we save the type as a call to type(name, bases, dict).  
        # The arguments to type() are simple: type(name, bases, dict).  We'll
        # fill in __dict__ specially below.
        args = (cls.__name__, cls.__bases__,
                # __dict__ and __weakref__ are a bit special (they're
                # getset_descriptor objects), and will get initialized just
                # fine automagically, so omit them to avoid infinite recursion
                # or other strange nonsense.  Similarly any attr in __slots__
                # is a member_descriptor.  God knows what's happening with
                # _abc_impl, I've never understood the implementation of abc.
                {k: v for k, v in cls.__dict__.items()
                 if k not in ('__dict__', '__weakref__', '_abc_impl') + slots})

        # Now save the class, similar to functions.
        if type(cls) is type:
            # Normally the constructor is type.
            self._save_global_name('builtins.type')
        else:
            # But if you have a metaclass, that's the constructor.
            self._save_type(type(cls))
        self.save(args)
        # Handle recursive classes:
        memoed = self.memo.get(id(cls))
        if memoed is not None:
            self.write(pickle.POP + self.get(memoed[0]))
            return
        self.write(pickle.REDUCE)
        self.memoize(cls)
        self._setattrs({k: getattr(cls, k) for k in _TYPE_ATTRS})

    def _make_simple_saver(constructor_name, arg_names, attr_names):
        """Returns a saver for a type which can be saved via REDUCE + BUILD.

        In particular, this works for any type for which:
        - to construct the type, it suffices to call `constructor(*args)`,
          then do some setattrs;
        - the type's constructor is a global (whose name is given in
          constructor_name); and
        - the constructor-arguments and attributes to be set are all attributes
          of the instance (whose names are given in arg_names and attr_names).

        This ultimately works mostly like save_function, just without some of
        the extra-complicated bits around globals.
        """
        def saver(self, obj):
            memoed = self.memo.get(id(obj))
            if memoed is not None:
                self.write(self.get(memoed[0]))
                return

            if isinstance(obj, types.ModuleType) and obj.__name__ == 'sys':
                self._save_global_name('builtins.__import__')
                self.save((obj.__name__,))
                self.write(pickle.REDUCE)
                self.memoize(obj)
                return

            self._save_global_name(constructor_name)
            self.save(tuple(getattr(obj, attr) for attr in arg_names))

            # (This handles if obj is recursive; see class docstring.)
            memoed = self.memo.get(id(obj))
            if memoed is not None:
                self.write(pickle.POP + self.get(memoed[0]))
                return

            self.write(pickle.REDUCE)
            self.memoize(obj)
            if attr_names:
                self._setattrs({k: getattr(obj, k) for k in attr_names})

        return saver

    dispatch[types.CodeType] = _make_simple_saver(
        'types.CodeType', _CODE_ARGS, ())
    dispatch[types.CellType] = _make_simple_saver(
        'types.CellType', (), ('cell_contents',))
    dispatch[staticmethod] = _make_simple_saver(
        'builtins.staticmethod', ('__func__',), ())
    dispatch[classmethod] = _make_simple_saver(
        'builtins.classmethod', ('__func__',), ())
    dispatch[property] = _make_simple_saver(
        'builtins.property', ('fget', 'fset', 'fdel', '__doc__'), ())
    dispatch[types.ModuleType] = _make_simple_saver(
        'types.ModuleType', ('__name__', '__doc__'),
        ('__dict__', '__loader__', '__package__', '__spec__'))


def dumps(obj, protocol=None, *, fix_imports=True):
    assert protocol is None or protocol >= 2
    # cribbed from pickle.dumps:
    f = io.BytesIO()
    Pickler(f, protocol, fix_imports=fix_imports).dump(obj)
    res = f.getvalue()
    assert isinstance(res, pickle.bytes_types)
    return res
