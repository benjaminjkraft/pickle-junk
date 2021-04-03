# flake8: noqa  # we do lots of weird things to test them!
import pickle
import unittest

import pickle_function

# TODO:
# - more closures
# - args, defaults, etc. -- generally go through the list of attrs
# - pickle some actual real functions


def _roundtrip(val):
    pickled = pickle_function.dumps(val)
    # use _loads (the python implementation) for better stacktraces
    return pickle._loads(pickled)

def _roundtrip_test(val, assertion_func):
    assertion_func(val)
    val_again = _roundtrip(val)
    # TODO: also assert str(val) == str(val_again), to make sure we get the
    # name and stuff right?  Looks like it's not true now :/
    assertion_func(val_again)



ONE = 1
def global_add_two(n): return n + ONE + 1
def global_defaults(a, /, b, c=1, *, d, e=2): return a + b + c + d + e
def global_attrs(): pass
global_attrs.x = 1


class TestSimpleFunctions(unittest.TestCase):
    def test_simple(self):
        def test(f):
            self.assertEqual(f(1), 3)

        add_two = lambda n: n + ONE + 1
        _roundtrip_test(add_two, test)

        def add_two(n): return n + ONE + 1
        _roundtrip_test(add_two, test)

        _roundtrip_test(global_add_two, test)

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
        _roundtrip_test(defaults, test)

        def defaults(a, /, b, c=1, *, d, e=2): return a + b + c + d + e
        _roundtrip_test(defaults, test)

        _roundtrip_test(global_defaults, test)

    def test_attrs(self):
        def test(f):
            self.assertEqual(f(), None)
            self.assertEqual(f.x, 1)

        attrs = lambda: None
        attrs.x = 1
        _roundtrip_test(attrs, test)

        def attrs(): pass
        attrs.x = 1
        _roundtrip_test(attrs, test)

        _roundtrip_test(global_attrs, test)


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
        _roundtrip_test(factorial, test)

        def factorial(n): return n * factorial(n - 1) if n > 0 else 1
        _roundtrip_test(factorial, test)

        _roundtrip_test(global_factorial, test)

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
        
        _roundtrip_test(self_attr, test)

        def self_attr(n):
            x = getattr(self_attr, 'x', None)
            if x is not None:
                return x
            self_attr.x = n + 1
            return self_attr(0)

        _roundtrip_test(self_attr, test)

        # just in case...
        if hasattr(global_self_attr, 'x'):
            del global_self_attr.x

        _roundtrip_test(global_self_attr, test)

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

        _roundtrip_test(recursive_defaults, test)

        default_g = {}
        default_h = {}
        def recursive_defaults(g=default_g, *, h=default_h):
            return (g['f'], h['f'])
        default_g['f'] = recursive_defaults
        default_h['f'] = recursive_defaults

        _roundtrip_test(recursive_defaults, test)

        _roundtrip_test(global_recursive_defaults, test)

    def test_attrs_lambda(self):
        def test(f):
            self.assertEqual(f(), None)
            self.assertEqual(f.self, f)

        recursive_attrs = lambda: None
        recursive_attrs.self = recursive_attrs
        _roundtrip_test(recursive_attrs, test)

        def recursive_attrs(): pass
        recursive_attrs.self = recursive_attrs
        _roundtrip_test(recursive_attrs, test)

        _roundtrip_test(global_recursive_attrs, test)
