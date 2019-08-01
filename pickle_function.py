#!/usr/bin/env python3
import io
import pickle
import pickletools
import types


# These are in the order of the CodeType constructor.
_CODE_ATTRS = (
    'co_argcount',
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
# But we can check that the list is correct.
assert set(_CODE_ATTRS) == {attr for attr in dir(types.CodeType)
                            if attr.startswith('co_')}


class Pickler(pickle._Pickler):
    """A pickler that can save lambdas, inline functions, and other garbage."""
    def _save_global_name(self, name):
        """Saves the global with the given name.

        This is like save_global, but it works for names which appear to be
        builtins but aren't available as __builtins__.foo, such as
        types.FunctionType.
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
        try:
            return self.save_global(obj)
        except Exception:
            if type(obj) != types.FunctionType:   # noqa:E721
                raise

        self._save_global_name('types.FunctionType')
        co_names = set(obj.__code__.co_names)
        relevant_globals = {k: v for k, v in obj.__globals__.items()
                            if k in co_names}
        self.save((obj.__code__, relevant_globals, obj.__name__,
                   obj.__defaults__, obj.__closure__))
        self.write(pickle.REDUCE)
        # TODO: need to fix up __kwdefaults__ and potentially __dict__ -- can
        # probably just call _batch_setitems.
        self.memoize(obj)

    dispatch[types.FunctionType] = save_function

    def save_code(self, obj, name=None):
        """A saver for types.CodeType.

        Like save_function, this has to hook in to the internal dispatch.
        """
        self._save_global_name('types.CodeType')
        self.save(tuple(getattr(obj, attr) for attr in _CODE_ATTRS))
        self.write(pickle.REDUCE)
        self.memoize(obj)

    dispatch[types.CodeType] = save_code


def dumps(obj, protocol=None, *, fix_imports=True):
    assert protocol is None or protocol >= 2
    # cribbed from pickle.dumps:
    f = io.BytesIO()
    Pickler(f, protocol, fix_imports=fix_imports).dump(obj)
    res = f.getvalue()
    assert isinstance(res, pickle.bytes_types)
    return res


def test():
    f = lambda x: x + 1  # noqa:E731
    pickled = dumps(f)
    try:
        f_again = pickle._loads(pickled)
        assert f_again(1) == 2
    except Exception:
        pickletools.dis(pickled)
    else:
        print("mwahaha!")


def main():
    test()


if __name__ == '__main__':
    main()
