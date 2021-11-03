#!/usr/bin/env python3
import pickle
import types

import pickle_function


def roundtrip(val):
    pickled = pickle_function.dumps(val)
    # use _loads (the python implementation) for better stacktraces
    return pickle._loads(pickled)


_IGNORED_TYPES = (
    # we aren't trying to pickle the types.CodeType/types.FunctionType
    # themselves, so we don't need to pickle their methods
    types.BuiltinMethodType, types.MethodDescriptorType,
    types.WrapperDescriptorType,
)


def interesting_attrs(typ):
    not_found = object()
    retval = set()
    for attr in dir(typ):
        # not_found happens, strangely, for several attrs of type!
        val = getattr(typ, attr, not_found)
        # usually we are only interested in member-descriptors, or similar
        # proxies (e.g. FunctionType.__dict__ is MappingProxyType), but
        # type is itself a valid type, so it has all sorts of other types
        # instead.  so we ignore types rather than listing the ones we want.
        # __class__ is irrelevant except type.__class__, which is specially
        # handled (but we can't tell this by the type; type.__base__ also has
        # type type, and we do want that).
        if (type(val) not in _IGNORED_TYPES and attr != '__class__'):
            retval.add(attr)
    return retval


def full_dict(val):
    return {k: getattr(val, k, '*** UNSET ***')
            for k in interesting_attrs(type(val))}
