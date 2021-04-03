# flake8: noqa  # we do lots of weird things to test them!
import pickle
import unittest

import pickle_function

# TODO:
# - more closures
# - args, defaults, etc. -- generally go through the list of attrs
# - pickle some actual real functions


ONE = 1


def add_one(n):
    return n + ONE


def factorial(n):
    if n == 0:
        return 1
    return n * factorial(n - 1)


def self_attr(n):
    x = getattr(self_attr, 'x', None)
    if x is not None:
        return x
    self_attr.x = n + 1
    return self_attr(0)


class TestPicklingFunctions(unittest.TestCase):
    def _roundtrip(self, val):
        pickled = pickle_function.dumps(val)
        # use _loads (the python implementation) for better stacktraces
        return pickle._loads(pickled)

    def test_simple_lambda(self):
        f = lambda n: n + 1
        f_again = self._roundtrip(f)
        self.assertEqual(f_again(1), 2)

    def test_simple_inline_def(self):
        def f(n): return n + 1
        f_again = self._roundtrip(f)
        self.assertEqual(f_again(1), 2)

    def test_simple_global_def(self):
        add_one_again = self._roundtrip(add_one)
        self.assertEqual(add_one_again(1), 2)

    def test_recursive_lambda(self):
        f = lambda n: n * f(n - 1) if n > 0 else 1
        f_again = self._roundtrip(f)
        self.assertEqual(f_again(1), 1)
        self.assertEqual(f_again(4), 24)

    def test_recursive_inline_def(self):
        def f(n): return n * f(n - 1) if n > 0 else 1
        f_again = self._roundtrip(f)
        self.assertEqual(f_again(1), 1)
        self.assertEqual(f_again(4), 24)

    def test_recursive_global_def(self):
        factorial_again = self._roundtrip(factorial)
        self.assertEqual(factorial_again(1), 1)
        self.assertEqual(factorial_again(4), 24)

    def test_recursive_identity_lambda(self):
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

        self_attr_again = self._roundtrip(self_attr)
        self.assertEqual(self_attr_again(1), 2)
        self.assertEqual(self_attr_again(5), 2)

    def test_recursive_identity_inline_def(self):
        def self_attr(n):
            x = getattr(self_attr, 'x', None)
            if x is not None:
                return x
            self_attr.x = n + 1
            return self_attr(0)

        self_attr_again = self._roundtrip(self_attr)
        self.assertEqual(self_attr_again(1), 2)
        self.assertEqual(self_attr_again(5), 2)

    def test_recursive_identity_global_def(self):
        if hasattr(self_attr, 'x'):
            del self_attr.x
        self_attr_again = self._roundtrip(self_attr)
        self.assertEqual(self_attr_again(1), 2)
        self.assertEqual(self_attr_again(5), 2)

