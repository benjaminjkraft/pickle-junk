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


ONE = 1
def global_add_two(n): return n + ONE + 1
def global_defaults(a, /, b, c=1, *, d, e=2): return a + b + c + d + e
def global_attrs(): pass
global_attrs.x = 1


class TestSimpleFunctions(unittest.TestCase):
    def test_lambda(self):
        add_two = lambda n: n + ONE + 1
        add_two_again = _roundtrip(add_two)
        self.assertEqual(add_two_again(1), 3)

    def test_inline_def(self):
        def add_two(n): return n + ONE + 1
        add_two_again = _roundtrip(add_two)
        self.assertEqual(add_two_again(1), 3)

    def test_global_def(self):
        add_two_again = _roundtrip(global_add_two)
        self.assertEqual(add_two_again(1), 3)

    def test_defaults_lambda(self):
        defaults = lambda a, /, b, c=1, *, d, e=2: a + b + c + d + e

        defaults_again = _roundtrip(defaults)
        self.assertEqual(defaults_again(1, 2, d=3), 9)
        self.assertEqual(defaults_again(1, 2, 3, d=4, e=5), 15)
        with self.assertRaises(TypeError):
            defaults_again()
        with self.assertRaises(TypeError):
            defaults_again(1, 2, 3)
        with self.assertRaises(TypeError):
            defaults_again(a=1, b=2, d=3)
        with self.assertRaises(TypeError):
            defaults_again(1, 2, 3, 4, 5)
        with self.assertRaises(TypeError):
            defaults_again(a=1, b=2, c=3, d=4, e=5)

    def test_defaults_local_def(self):
        def defaults(a, /, b, c=1, *, d, e=2): return a + b + c + d + e

        defaults_again = _roundtrip(defaults)
        self.assertEqual(defaults_again(1, 2, d=3), 9)
        self.assertEqual(defaults_again(1, 2, 3, d=4, e=5), 15)
        with self.assertRaises(TypeError):
            defaults_again()
        with self.assertRaises(TypeError):
            defaults_again(1, 2, 3)
        with self.assertRaises(TypeError):
            defaults_again(a=1, b=2, d=3)
        with self.assertRaises(TypeError):
            defaults_again(1, 2, 3, 4, 5)
        with self.assertRaises(TypeError):
            defaults_again(a=1, b=2, c=3, d=4, e=5)

    def test_defaults_global_def(self):
        defaults_again = _roundtrip(global_defaults)
        self.assertEqual(defaults_again(1, 2, d=3), 9)
        self.assertEqual(defaults_again(1, 2, 3, d=4, e=5), 15)
        with self.assertRaises(TypeError):
            defaults_again()
        with self.assertRaises(TypeError):
            defaults_again(1, 2, 3)
        with self.assertRaises(TypeError):
            defaults_again(a=1, b=2, d=3)
        with self.assertRaises(TypeError):
            defaults_again(1, 2, 3, 4, 5)
        with self.assertRaises(TypeError):
            defaults_again(a=1, b=2, c=3, d=4, e=5)

    def test_attrs_lambda(self):
        attrs = lambda: None
        attrs.x = 1

        attrs_again = _roundtrip(attrs)
        self.assertEqual(attrs_again(), None)
        self.assertEqual(attrs_again.x, 1)

    def test_attrs_local_def(self):
        def attrs(): pass
        attrs.x = 1

        attrs_again = _roundtrip(attrs)
        self.assertEqual(attrs_again(), None)
        self.assertEqual(attrs_again.x, 1)

    def test_attrs_global_def(self):
        attrs_again = _roundtrip(global_attrs)
        self.assertEqual(attrs_again(), None)
        self.assertEqual(attrs_again.x, 1)


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
    def test_lambda(self):
        f = lambda n: n * f(n - 1) if n > 0 else 1
        f_again = _roundtrip(f)
        self.assertEqual(f_again(1), 1)
        self.assertEqual(f_again(4), 24)

    def test_inline_def(self):
        def f(n): return n * f(n - 1) if n > 0 else 1
        f_again = _roundtrip(f)
        self.assertEqual(f_again(1), 1)
        self.assertEqual(f_again(4), 24)

    def test_global_def(self):
        factorial_again = _roundtrip(global_factorial)
        self.assertEqual(factorial_again(1), 1)
        self.assertEqual(factorial_again(4), 24)

    def test_identity_lambda(self):
        """Test we get object-identity right in recursive functions."""
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

        self_attr_again = _roundtrip(self_attr)
        self.assertEqual(self_attr_again(1), 2)
        self.assertEqual(self_attr_again(5), 2)
        self.assertEqual(self_attr_again.x, 2)

    def test_identity_inline_def(self):
        def self_attr(n):
            x = getattr(self_attr, 'x', None)
            if x is not None:
                return x
            self_attr.x = n + 1
            return self_attr(0)

        self_attr_again = _roundtrip(self_attr)
        self.assertEqual(self_attr_again(1), 2)
        self.assertEqual(self_attr_again(5), 2)
        self.assertEqual(self_attr_again.x, 2)

    def test_identity_global_def(self):
        # just in case...
        if hasattr(global_self_attr, 'x'):
            del global_self_attr.x

        self_attr_again = _roundtrip(global_self_attr)
        self.assertEqual(self_attr_again(1), 2)
        self.assertEqual(self_attr_again(5), 2)
        self.assertEqual(self_attr_again.x, 2)

    def test_defaults_lambda(self):
        default_g = {}
        default_h = {}
        recursive_defaults = (
            lambda g=default_g, *, h=default_h: (g['f'], h['f']))
        default_g['f'] = recursive_defaults
        default_h['f'] = recursive_defaults

        recursive_defaults_again = _roundtrip(recursive_defaults)
        self.assertEqual(
            recursive_defaults_again(),
            (recursive_defaults_again, recursive_defaults_again))
        self.assertEqual(
            recursive_defaults_again({'f': 1}, h={'f': 1}),
            (1, 1))
        with self.assertRaises(TypeError):
            recursive_defaults_again({'f': 1}, {'f': 1})

    def test_defaults_local_def(self):
        default_g = {}
        default_h = {}
        def recursive_defaults(g=default_g, *, h=default_h):
            return (g['f'], h['f'])
        default_g['f'] = recursive_defaults
        default_h['f'] = recursive_defaults

        recursive_defaults_again = _roundtrip(recursive_defaults)
        self.assertEqual(
            recursive_defaults_again(),
            (recursive_defaults_again, recursive_defaults_again))
        self.assertEqual(
            recursive_defaults_again({'f': 1}, h={'f': 1}),
            (1, 1))
        with self.assertRaises(TypeError):
            recursive_defaults_again({'f': 1}, {'f': 1})

    def test_defaults_global_def(self):
        recursive_defaults_again = _roundtrip(global_recursive_defaults)
        self.assertEqual(
            recursive_defaults_again(),
            (recursive_defaults_again, recursive_defaults_again))
        self.assertEqual(
            recursive_defaults_again({'f': 1}, h={'f': 1}),
            (1, 1))
        with self.assertRaises(TypeError):
            recursive_defaults_again({'f': 1}, {'f': 1})

    def test_attrs_lambda(self):
        recursive_attrs = lambda: None
        recursive_attrs.self = recursive_attrs

        recursive_attrs_again = _roundtrip(recursive_attrs)
        self.assertEqual(recursive_attrs_again(), None)
        self.assertEqual(recursive_attrs_again.self, recursive_attrs_again)

    def test_attrs_local_def(self):
        def recursive_attrs(): pass
        recursive_attrs.self = recursive_attrs

        recursive_attrs_again = _roundtrip(recursive_attrs)
        self.assertEqual(recursive_attrs_again(), None)
        self.assertEqual(recursive_attrs_again.self, recursive_attrs_again)

    def test_attrs_global_def(self):
        recursive_attrs_again = _roundtrip(global_recursive_attrs)
        self.assertEqual(recursive_attrs_again(), None)
        self.assertEqual(recursive_attrs_again.self, recursive_attrs_again)
