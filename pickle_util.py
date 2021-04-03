#!/usr/bin/env python3
import pickle

import pickle_function


def roundtrip(val):
    pickled = pickle_function.dumps(val)
    # use _loads (the python implementation) for better stacktraces
    return pickle._loads(pickled)


def full_dict(val):
    return {k: getattr(val, k)
            for k in dir(val)
            if k not in dir(object())}
