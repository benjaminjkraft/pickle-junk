# flake8: noqa  # we do lots of weird things to test them!
import itertools
import pickle
import re
import unittest
import types
import typing

import pickle_function
import pickle_util


class TestConsts(unittest.TestCase):
    def test_code_attrs(self):
        # We can't check that the order is correct (the constructor is in C so
        # we can't introspect it) but we can check that the set is correct.
        self.assertEqual(
            # doc is only a class-attr here, no need to pickle.
            set(pickle_function._CODE_ARGS) | {'__doc__'},
            pickle_util.interesting_attrs(types.CodeType))

    def test_func_attrs(self):
        self.assertEqual(
            set(pickle_function._FUNC_ARGS) | pickle_function._FUNC_ATTRS,
            pickle_util.interesting_attrs(types.FunctionType))


def _repr_without_address(val):
    return re.sub(' at 0x[0-9a-f]+>$', '>', repr(val))


def _roundtrip_test(testcase, val, assertion_func):
    assertion_func(val)
    val_again = pickle_util.roundtrip(val)
    testcase.assertEqual(_repr_without_address(val),
                         _repr_without_address(val_again))
    assertion_func(val_again)


def _simple_roundtrip_test(testcase, val):
    def test(val_again):
        testcase.assertEqual(val, val_again)


class TestBuiltins(unittest.TestCase):
    def test_basic(self):
        for val in [
                1, 2 ** 1000, 1.2e34,
                'str', b'bytes',
                None, True, NotImplemented, ...,
                Exception("hello"),
                object,
        ]:
            _simple_roundtrip_test(self, val)
            _simple_roundtrip_test(self, type(val))


    def test_list(self):
        _simple_roundtrip_test(self, [1, [], [2, [3]]])

        x = []
        x.append(x)
        _simple_roundtrip_test(self, x)

    def test_tuple(self):
        _simple_roundtrip_test(self, (1, 2, (3, 4)))

    def test_dict(self):
        _simple_roundtrip_test(self, {1: {2: {}, 3: {4: {5: 6}}}})

        x = {}
        x[1] = x
        _simple_roundtrip_test(self, x)

    def test_set(self):
        _simple_roundtrip_test(
            self, {frozenset([1, 2, frozenset([3, 4])]), 5})


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


class SimpleGlobalClass:
    """A good class."""
    CLASS_VAR = 1

    def __init__(self, x):
        self.init_arg = x
        self.instance_var = 2

    def method(self):
        return 3


class GlobalMethodfulClass:
    @staticmethod
    def s():
        """A staticmethod"""
        return 2

    @classmethod
    def c(cls):
        """A classmethod"""
        return cls

    def m(self):
        """A method"""
        return self

    @property
    def p(self):
        return self

    def get(self):
        return self._p2

    def set(self, v):
        self._p2 = v

    def delete(self):
        del self._p2

    p2 = property(get, set, delete, "A property")


class GlobalMetaclass(type): pass
class GlobalBaseClass(metaclass=GlobalMetaclass): pass
class GlobalFancyClass(GlobalBaseClass): pass

class GlobalSlotsClass:
    __slots__ = ('myslot',)

    def __init__(self, val):
        self.myslot = val


class GlobalReduceClass:
    def __init__(self):
        self.times_pickled = 0

    @classmethod
    def _load(cls, times_pickled):
        self = cls()
        self.times_pickled = times_pickled
        return self

    def __reduce__(self):
        return (self._load, (self.times_pickled + 1,))


class TestClasses(unittest.TestCase):
    class SimpleClassLevelClass:
        """A good class."""
        CLASS_VAR = 1

        def __init__(self, x):
            self.init_arg = x
            self.instance_var = 2

        def method(self):
            return 3

    class ClassLevelMethodfulClass:
        @staticmethod
        def s():
            """A staticmethod"""
            return 2

        @classmethod
        def c(cls):
            """A classmethod"""
            return cls

        def m(self):
            """A method"""
            return self

        @property
        def p(self):
            return self

        def get(self):
            return self._p2

        def set(self, v):
            self._p2 = v

        def delete(self):
            del self._p2

        p2 = property(get, set, delete, "A property")

    class ClassLevelMetaclass(type): pass
    class ClassLevelBaseClass(metaclass=ClassLevelMetaclass): pass
    class ClassLevelFancyClass(ClassLevelBaseClass): pass

    class ClassLevelSlotsClass:
        __slots__ = ('myslot',)

        def __init__(self, val):
            self.myslot = val

    class ClassLevelReduceClass:
        def __init__(self):
            self.times_pickled = 0

        @classmethod
        def _load(cls, times_pickled):
            self = cls()
            self.times_pickled = times_pickled
            return self

        def __reduce__(self):
            return (self._load, (self.times_pickled + 1,))

    def test_simple(self):
        def test(c):
            self.assertEqual(c.CLASS_VAR, 1)
            self.assertEqual(c(0).instance_var, 2)
            self.assertEqual(c(0).method(), 3)
            self.assertEqual(c(0).init_arg, 0)
            self.assertEqual(c.__doc__, """A good class.""")

        class SimpleLocalClass:
            """A good class."""
            CLASS_VAR = 1

            def __init__(self, x):
                self.init_arg = x
                self.instance_var = 2

            def method(self):
                return 3

        _roundtrip_test(self, SimpleLocalClass, test)
        _roundtrip_test(self, self.SimpleClassLevelClass, test)
        _roundtrip_test(self, SimpleGlobalClass, test)

    def test_methods(self):
        def test(c):
            self.assertEqual(c.s(), 2)
            self.assertEqual(c.s.__doc__, "A staticmethod")
            self.assertIs(c.c(), c)
            self.assertEqual(c.c.__doc__, "A classmethod")
            v = c()
            self.assertIs(v.m(), v)
            self.assertEqual(v.m.__doc__, "A method")
            self.assertIs(v.p, v)

            self.assertFalse(hasattr(v, 'p2'))
            v.p2 = 1
            self.assertEqual(v.p2, 1)
            del v.p2
            self.assertFalse(hasattr(v, 'p2'))
            self.assertEqual(c.p2.__doc__, "A property")

        class LocalMethodfulClass:
            @staticmethod
            def s():
                """A staticmethod"""
                return 2

            @classmethod
            def c(cls):
                """A classmethod"""
                return cls

            def m(self):
                """A method"""
                return self

            @property
            def p(self):
                return self

            def get(self):
                return self._p2

            def set(self, v):
                self._p2 = v

            def delete(self):
                del self._p2

            p2 = property(get, set, delete, "A property")

        _roundtrip_test(self, GlobalMethodfulClass, test)
        _roundtrip_test(self, self.ClassLevelMethodfulClass, test)
        _roundtrip_test(self, LocalMethodfulClass, test)

    def test_fancy(self):
        def make_test(expected):
            def test(actual):
                e = expected
                a = actual
                for i in itertools.count():
                    wrapper = "type(" * i + "%s" + ")" * i
                    err = ("expected %s to be %s, but got %s = %s" % (
                        wrapper % expected, e, wrapper % actual, a))
                    if e is type:
                        self.assertEqual(a, type, err)
                        break
                    self.assertEqual(e.__name__, a.__name__, err)
                    e = type(e)
                    a = type(a)
            return test

        class LocalMetaclass(type): pass
        class LocalBaseClass(metaclass=LocalMetaclass): pass
        class LocalFancyClass(LocalBaseClass): pass

        for cls in [
                GlobalMetaclass,
                GlobalBaseClass,
                GlobalFancyClass,
                self.ClassLevelMetaclass,
                self.ClassLevelBaseClass,
                self.ClassLevelFancyClass,
                LocalMetaclass,
                LocalBaseClass,
                LocalFancyClass,
        ]:
            _roundtrip_test(self, cls, make_test(cls))

    def test_slots(self):
        def testcls(c):
            self.assertEqual(c.__slots__, ('myslot',))
        def testinst(v):
            self.assertEqual(v.myslot, 1)

        class LocalSlotsClass:
            __slots__ = ('myslot',)

            def __init__(self, val):
                self.myslot = val

        _roundtrip_test(self, GlobalSlotsClass, testcls)
        _roundtrip_test(self, GlobalSlotsClass(1), testinst)
        _roundtrip_test(self, self.ClassLevelSlotsClass, testcls)
        _roundtrip_test(self, self.ClassLevelSlotsClass(1), testinst)
        _roundtrip_test(self, LocalSlotsClass, testcls)
        _roundtrip_test(self, LocalSlotsClass(1), testinst)

    def test_reduce_class(self):
        def test(cls):
            v = cls()
            for i in range(3):
                self.assertEqual(v.times_pickled, i)
                v = pickle_util.roundtrip(v)

        class LocalReduceClass:
            def __init__(self):
                self.times_pickled = 0

            @classmethod
            def _load(cls, times_pickled):
                self = cls()
                self.times_pickled = times_pickled
                return self

            def __reduce__(self):
                return (self._load, (self.times_pickled + 1,))

        test(GlobalReduceClass)
        test(self.ClassLevelReduceClass)
        test(LocalReduceClass)


class TestModules(unittest.TestCase):
    def test_pickle_function(self):
        def test(mod):
            self.assertEqual(pickle.loads(mod.dumps(1)), 1)

        _roundtrip_test(self, pickle_function, test)
