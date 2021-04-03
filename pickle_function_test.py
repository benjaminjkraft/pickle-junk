# flake8: noqa  # we do lots of weird things to test them!
import pickle
import re
import unittest
import types
import typing

import pickle_function
import pickle_util


_REPR_ADDRESS = re.compile(' at 0x[0-9a-f]+>$')


def _repr_without_address(val):
    return _REPR_ADDRESS.sub('>', repr(val))


def _roundtrip_test(testcase, val, assertion_func):
    assertion_func(val)
    val_again = pickle_util.roundtrip(val)
    testcase.assertEqual(_repr_without_address(val),
                         _repr_without_address(val_again))
    assertion_func(val_again)


class TestConsts(unittest.TestCase):
    _IGNORED_TYPES = (
        # we aren't trying to pickle the types.CodeType/types.FunctionType
        # themselves, so we don't need to pickle their methods
        types.BuiltinMethodType, types.MethodDescriptorType,
        types.WrapperDescriptorType,
        # nor their __class__
        type,
    )

    _INCLUDED_TYPES = (
        # we want to pickle all the members
        types.MemberDescriptorType,
        # in the case of FunctionTypes, some of the members are proxies
        types.GetSetDescriptorType, types.MappingProxyType,
        # types.FunctionType itself has __module__, __qualname__, __doc__,
        # etc., but really those are members we need to include.
        str,
    )

    def _get_attrs(self, typ):
        retval = set()
        for attr in dir(typ):
            val = getattr(typ, attr)
            if type(val) in self._INCLUDED_TYPES:
                retval.add(attr)
            else:
                # Everything should either be mentioned or explicitly ignored.
                self.assertIn(type(val), self._IGNORED_TYPES)
        return retval

    def test_code_attrs(self):
        # We can't check that the order is correct (the constructor is in C so
        # we can't introspect it) but we can check that the set is correct.
        self.assertEqual(
            # doc is only a class-attr here, no need to pickle.
            set(pickle_function._CODE_ARGS) | {'__doc__'},
            self._get_attrs(types.CodeType))

    def test_func_attrs(self):
        self.assertEqual(
            set(pickle_function._FUNC_ARGS) | pickle_function._FUNC_ATTRS,
            self._get_attrs(types.FunctionType))


ONE = 1
def global_add_two(n): return n + ONE + 1
def global_make_add_two():
    def add_two(n): return n + ONE + 1
    return add_two
def global_defaults(a, /, b, c=1, *, d, e=2): return a + b + c + d + e
def global_attrs(): pass
global_attrs.x = 1
def global_annotations(x: int) -> int: return x
def global_doc():
    """This function has a docstring."""
    pass


class TestSimpleFunctions(unittest.TestCase):
    def test_simple(self):
        def test(f):
            self.assertEqual(f(1), 3)

        add_two = lambda n: n + ONE + 1
        _roundtrip_test(self, add_two, test)

        def add_two(n): return n + ONE + 1
        _roundtrip_test(self, add_two, test)

        def make_add_two():
            def add_two(n): return n + ONE + 1
            return add_two
        _roundtrip_test(self, make_add_two(), test)

        _roundtrip_test(self, global_add_two, test)
        _roundtrip_test(self, global_make_add_two(), test)

    def test_defaults(self):
        def test(f):
            self.assertEqual(f(1, 2, d=3), 9)
            self.assertEqual(f(1, 2, 3, d=4, e=5), 15)
            with self.assertRaises(TypeError):
                f()
            with self.assertRaises(TypeError):
                f(1, 2, 3)
            with self.assertRaises(TypeError):
                f(a=1, b=2, d=3)
            with self.assertRaises(TypeError):
                f(1, 2, 3, 4, 5)
            with self.assertRaises(TypeError):
                f(a=1, b=2, c=3, d=4, e=5)

        defaults = lambda a, /, b, c=1, *, d, e=2: a + b + c + d + e
        _roundtrip_test(self, defaults, test)

        def defaults(a, /, b, c=1, *, d, e=2): return a + b + c + d + e
        _roundtrip_test(self, defaults, test)

        _roundtrip_test(self, global_defaults, test)

    def test_attrs(self):
        def test(f):
            self.assertEqual(f(), None)
            self.assertEqual(f.x, 1)

        attrs = lambda: None
        attrs.x = 1
        _roundtrip_test(self, attrs, test)

        def attrs(): pass
        attrs.x = 1
        _roundtrip_test(self, attrs, test)

        _roundtrip_test(self, global_attrs, test)

    def test_annotations(self):
        def test(f):
            self.assertEqual(f(1), 1)
            self.assertEqual(typing.get_type_hints(f),
                             {'x': int, 'return': int})

        def annotations(x: int) -> int: return x
        _roundtrip_test(self, annotations, test)

        _roundtrip_test(self, global_annotations, test)

    def test_doc(self):
        def test(f):
            self.assertEqual(f(), None)
            self.assertEqual(f.__doc__, "This function has a docstring.")

        doc = lambda: None
        doc.__doc__ = """This function has a docstring."""
        _roundtrip_test(self, doc, test)

        def doc():
            """This function has a docstring."""
            pass
        _roundtrip_test(self, doc, test)

        _roundtrip_test(self, global_doc, test)


def global_factorial(n):
    if n == 0:
        return 1
    return n * global_factorial(n - 1)


def global_self_attr(n):
    x = getattr(global_self_attr, 'x', None)
    if x is not None:
        return x
    global_self_attr.x = n + 1
    return global_self_attr(0)


global_default_g = {}
global_default_h = {}
def global_recursive_defaults(g=global_default_g, *, h=global_default_h):
    return (g['f'], h['f'])
global_default_g['f'] = global_recursive_defaults
global_default_h['f'] = global_recursive_defaults


def global_recursive_attrs(): pass
global_recursive_attrs.self = global_recursive_attrs


class TestRecursiveFunctions(unittest.TestCase):
    def test_simple(self):
        def test(f):
            self.assertEqual(f(1), 1)
            self.assertEqual(f(4), 24)

        factorial = lambda n: n * factorial(n - 1) if n > 0 else 1
        _roundtrip_test(self, factorial, test)

        def factorial(n): return n * factorial(n - 1) if n > 0 else 1
        _roundtrip_test(self, factorial, test)

        _roundtrip_test(self, global_factorial, test)

    def test_identity_lambda(self):
        """Test we get object-identity right in recursive functions."""
        def test(f):
            self.assertEqual(f(1), 2)
            self.assertEqual(f(5), 2)
            self.assertEqual(f.x, 2)

        # TODO: lol maybe actually use onelinerizer
        self_attr = lambda n: (
            (
                lambda x:
                x
                if x is not None
                else (
                    setattr(self_attr, 'x', n + 1),
                    self_attr(0),
                )[1]
            )(
                getattr(self_attr, 'x', None)
            ))
        
        _roundtrip_test(self, self_attr, test)

        def self_attr(n):
            x = getattr(self_attr, 'x', None)
            if x is not None:
                return x
            self_attr.x = n + 1
            return self_attr(0)

        _roundtrip_test(self, self_attr, test)

        # just in case...
        if hasattr(global_self_attr, 'x'):
            del global_self_attr.x

        _roundtrip_test(self, global_self_attr, test)

    def test_defaults_lambda(self):
        def test(f):
            self.assertEqual(f(), (f, f))
            self.assertEqual(f({'f': 1}, h={'f': 1}), (1, 1))
            with self.assertRaises(TypeError):
                f({'f': 1}, {'f': 1})

        default_g = {}
        default_h = {}
        recursive_defaults = (
            lambda g=default_g, *, h=default_h: (g['f'], h['f']))
        default_g['f'] = recursive_defaults
        default_h['f'] = recursive_defaults

        _roundtrip_test(self, recursive_defaults, test)

        default_g = {}
        default_h = {}
        def recursive_defaults(g=default_g, *, h=default_h):
            return (g['f'], h['f'])
        default_g['f'] = recursive_defaults
        default_h['f'] = recursive_defaults

        _roundtrip_test(self, recursive_defaults, test)

        _roundtrip_test(self, global_recursive_defaults, test)

    def test_attrs_lambda(self):
        def test(f):
            self.assertEqual(f(), None)
            self.assertEqual(f.self, f)

        recursive_attrs = lambda: None
        recursive_attrs.self = recursive_attrs
        _roundtrip_test(self, recursive_attrs, test)

        def recursive_attrs(): pass
        recursive_attrs.self = recursive_attrs
        _roundtrip_test(self, recursive_attrs, test)

        _roundtrip_test(self, global_recursive_attrs, test)
