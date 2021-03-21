#!/usr/bin/env python3
from pickle import *
import struct

# For explanation, see my blog post:
#   https://www.benkraft.org/2021/03/21/pickle-quine/

# Part 1 is the part before the string itself.  It's just the version header,
# and the setup for the string.
PART_1 = (
    PROTO, b'\x03',                             # pickle version 3 header
    SHORT_BINBYTES,                             # bytestring (length TBD)
)

# Part 2 is what comes after the string itself: it assumes we have the string
# on the stack, and runs code equivalent to
#   the_string[4:] + the_string + the_string[:4]
# leaving the result on the stack to be returned.  (See the blog post for
# more.)
PART_2 = (
    BINPUT, b'\x00',                        # store the string in memo 0

    GLOBAL, b'builtins\nslice\n',           # put slice on stack
    BINPUT, b'\x01',                        # store it in memo 1

    GLOBAL, b'operator\ngetitem\n',         # put operator.getitem on stack
    BINPUT, b'\x02',                        # store it in memo 2

    GLOBAL, b'operator\nadd\n',             # put operator.add on stack
    BINPUT, b'\x03',                        # store it in memo 3

    BINGET, b'\x01',                        # load slice from memo 1
    NONE,                                   # put None on stack
    BININT1, b'\x04',                       # put 4 on stack
    TUPLE2, REDUCE,                         # call --> slice(None, 4)
    BINPUT, b'\x04',                        # store that in memo 4

    BINGET, b'\x01',                        # load slice from memo 1 again
    BININT1, b'\x04',                       # put 4 on stack
    NONE,                                   # put None on stack
    TUPLE2, REDUCE,                         # call --> slice(4, None)
    BINPUT, b'\x05',                        # store that in memo 5

    BINGET, b'\x02',                        # load getitem from memo 2
    BINGET, b'\x00',                        # load the string from memo 0
    BINGET, b'\x04',                        # load slice(None, 4) from memo 4
    TUPLE2, REDUCE,                         # call --> the_string[:4]
    BINPUT, b'\x06',                        # store that in memo 6

    BINGET, b'\x02',                        # load getitem from memo 2 again
    BINGET, b'\x00',                        # load the string from memo 0
    BINGET, b'\x05',                        # slice(4, None) from memo 5
    TUPLE2, REDUCE,                         # call --> the_string[4:]
    BINPUT, b'\x07',                        # store that in memo 7

    BINGET, b'\x03',                        # load operator.add from memo 3
    BINGET, b'\x06',                        # load the_string[:4] from memo 6
    BINGET, b'\x00',                        # load the_string from memo 0
    TUPLE2, REDUCE,                         # call
    BINPUT, b'\x08',                        # store that in memo 8

    BINGET, b'\x03',                        # load operator.add from memo 3
    BINGET, b'\x08',                        # load the_string[:4] + the_string
    BINGET, b'\x07',                        # load the_string[4:] from memo 7
    TUPLE2, REDUCE,                         # call

    STOP,                                   # STOP
)


def make_pickle(golfed=False):
    """Returns the pickle-quine.

    If "golfed" is true, we return the minimized version; if false we return
    the one that's easier to understand.
    """
    part_1 = b''.join(PART_1)
    part_2 = b''.join(GOLFED_PART_2 if golfed else PART_2)
    # We tack the length onto part 1:
    length = len(part_1) + 1 + len(part_2)
    part_1 = part_1 + b'%c' % length
    # Now glue everything together.
    the_string = part_1 + part_2
    return part_1 + the_string + part_2


# Now we golf it.  Only part 2 has anything interesting to golf.  Our main
# technique is to inline a value at its place of use, and if that's its only
# use, don't memoize it at all.  This relies on the stack a lot more, and it
# can be harder to see what is the argument to what.  We also use MEMOIZE,
# which is shorthand for BINPUT [next unused value].
GOLFED_PART_2 = (
    MEMOIZE,                                # store the string in memo 0

    # Here we use an extra trick: since we load two globals from operator we
    # can save a few bytes by storing 'operator' only once, and calling
    # STACK_GLOBAL (which is otherwise marginally less efficient) twice.
    SHORT_BINSTRING, b'\x08', b'operator',
    MEMOIZE,                                # store it in memo 1

    SHORT_BINSTRING, b'\x03', b'add',
    STACK_GLOBAL,                           # operator.add
    DUP,                                    # copy it

    BINGET, b'\x01',                        # operator
    SHORT_BINSTRING, b'\x07', b'getitem',
    STACK_GLOBAL,                           # operator.getitem
    MEMOIZE,                                # store it in memo 2

    BINGET, b'\x00',                        # the string
    GLOBAL, b'builtins\nslice\n',           # slice
    MEMOIZE,                                # store it in memo 3
    NONE,                                   # None
    BININT1, b'\x04',                       # 4
    TUPLE2, REDUCE,                         # call slice --> slice(None, 4)
    TUPLE2, REDUCE,                         # call getitem --> string[:4]

    BINGET, b'\x00',                        # the string
    TUPLE2, REDUCE,                         # call add

    BINGET, b'\x02',                        # getitem
    BINGET, b'\x00',                        # the string
    BINGET, b'\x03',                        # slice
    BININT1, b'\x04',                       # 4
    NONE,                                   # None
    TUPLE2, REDUCE,                         # call slice --> slice(4, None)
    TUPLE2, REDUCE,                         # call getitem --> string[4:]

    TUPLE2, REDUCE,                         # call add

    STOP,                                   # STOP
)


def check_pickle(data):
    """Checks that the input is a pickle-quine."""
    assert data == loads(data)


def main(filename, golfed=False):
    """Generates the pickle quine, checks it, and writes to file."""
    data = make_pickle(golfed)
    check_pickle(data)
    with open(filename, 'wb') as f:
        f.write(data)
    if golfed:
        print(f'Golfed to {len(data)} bytes!  Wrote to {filename}.')
    else:
        print(f'Quine works!  Wrote to {filename}.')


if __name__ == '__main__':
    main('quine.pickle', golfed=False)
    main('golfed_quine.pickle', golfed=True)
