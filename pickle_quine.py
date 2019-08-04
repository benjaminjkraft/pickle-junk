#!/usr/bin/env python3
import pickle
import struct


# So here's the plan.  We're going to make a pickle which will consist of two
# parts, each of which will be repeated twice to form the whole pickle.

# Part 1 is pretty simple: it consists of the pickle version 3 header
# followed by the preamble to the string consisting of part 1 followed by part
# 2.  (We'll fill in its length later.)
PART_1 = (
    pickle.PROTO, b'\x03',                      # pickle version 3 header
    pickle.SHORT_BINBYTES,                      # bytestring (length TBD)
)

# After part 1 (plus one byte of length) executes, our stack will have a single
# value, which will be the string consisting of part 1 + part 2 (hereafter "the
# string").  Part 2 will consist of everything we need to assemble that into
# the whole pickle: namely we need to split it at index 4 and then concatenate
# each half twice.

# Conveniently, pickle has a way of calling an arbitrary function.  First, we
# load it with GLOBAL <module>\n<name>\n.  Then, we put the arg-tuple on the
# stack.  Finally, we call REDUCE (for reduce) which calls the function on the
# arguments.  To do the string slicing, we'll call
#   operator.getitem(<str>, builtins.slice(start, end))
# and we'll then add those up with operator.add.
# So here we go:
PART_2 = (
    pickle.BINPUT, b'\x00',                     # store the string in memo 0

    pickle.GLOBAL, b'operator\ngetitem\n',      # put operator.getitem on stack
    pickle.BINPUT, b'\x01',                     # store it in memo 1

    pickle.GLOBAL, b'builtins\nslice\n',        # put slice on stack
    pickle.BINPUT, b'\x02',                     # store it in memo 2

    pickle.BININT1, b'\x00',                    # put 0 on stack
    pickle.BININT1, b'\x04',                    # put 4 on stack
    pickle.TUPLE2,                              # build those into (0, 4)
    pickle.REDUCE,                              # reduce --> slice(0, 4)
    pickle.BINPUT, b'\x03',                     # store that in memo 3

    pickle.BINGET, b'\x02',                     # load slice from memo 2
    pickle.BININT1, b'\x04',                    # put 4 on stack
    pickle.NONE,                                # put None on stack
    pickle.TUPLE2,                              # build those into (4, None)
    pickle.REDUCE,                              # reduce -> slice(4, None)
    pickle.BINPUT, b'\x04',                     # store that in memo 4

    pickle.BINGET, b'\x01',                     # load getitem from memo 1
    pickle.BINGET, b'\x00',                     # load the string from memo 0
    pickle.BINGET, b'\x03',                     # load slice(0, 4) from memo 3
    pickle.TUPLE2, pickle.REDUCE,               # tuple + call --> string[:4]
    pickle.BINPUT, b'\x05',                     # store that in memo 5

    pickle.BINGET, b'\x01',                     # load getitem from memo again
    pickle.BINGET, b'\x00',                     # load the string from memo 0
    pickle.BINGET, b'\x04',                     # slice(4, None) from memo 4
    pickle.TUPLE2, pickle.REDUCE,               # tuple + call --> string[4:]
    pickle.BINPUT, b'\x06',                     # store that in memo 6

    pickle.GLOBAL, b'operator\nadd\n',          # put operator.add on stack
    pickle.BINPUT, b'\x07',                     # store that in memo 7

    pickle.BINGET, b'\x05',                     # load string[:4] from memo 5
    pickle.BINGET, b'\x00',                     # load string from memo 0
    pickle.TUPLE2, pickle.REDUCE,               # build tuple, call +
    pickle.BINPUT, b'\x08',                     # store that in memo 8

    pickle.BINGET, b'\x07',                     # load operator.add from memo 7
    pickle.BINGET, b'\x08',                     # string[:4] + string from memo
    pickle.BINGET, b'\x06',                     # load string[7:] from memo 6
    pickle.TUPLE2, pickle.REDUCE,               # build tuple, call + again

    pickle.STOP,                                # STOP
)


def make_pickle(golfed):
    part_1 = b''.join(PART_1)
    part_2 = b''.join(GOLFED_PART_2 if golfed else PART_2)
    # Now, we just have to tack the correct length (of the string) onto part 1,
    # and duplicate everything appropriately.
    length = len(part_1) + 1 + len(part_2)
    return (part_1 + b'%c' % length) * 2 + part_2 * 2


# Now we golf it.  Only part 2 has anything interesting to golf.  Our main
# technique is to inline a value at its place of use, and if that's its only
# use, don't memoize it at all.  This relies on the stack a lot more, and it
# can be harder to see what is the argument to what.  We also use MEMOIZE,
# which is shorthand for BINPUT [next unused value].
GOLFED_PART_2 = (
    pickle.MEMOIZE,                             # store the string in memo 0

    # Here we use an extra trick: since we load two globals from operator we
    # can save a few bytes by storing 'operator' only once, and calling
    # STACK_GLOBAL (which is otherwise marginally less efficient) twice.
    pickle.SHORT_BINSTRING, b'\x08', b'operator',
    pickle.MEMOIZE,                             # store it in memo 1

    pickle.SHORT_BINSTRING, b'\x03', b'add',
    pickle.STACK_GLOBAL,                        # operator.add
    pickle.DUP,                                 # copy it

    pickle.BINGET, b'\x01',                     # operator
    pickle.SHORT_BINSTRING, b'\x07', b'getitem',
    pickle.STACK_GLOBAL,                        # operator.getitem
    pickle.MEMOIZE,                             # store it in memo 2

    pickle.BINGET, b'\x00',                     # the string
    pickle.GLOBAL, b'builtins\nslice\n',        # slice
    pickle.MEMOIZE,                             # store it in memo 3
    # The canonical arg here would be 0, but None is valid and saves a byte.
    pickle.NONE,                                # None
    pickle.BININT1, b'\x04',                    # 4
    pickle.TUPLE2, pickle.REDUCE,               # call slice --> slice(None, 4)
    pickle.TUPLE2, pickle.REDUCE,               # call getitem --> string[:4]

    pickle.BINGET, b'\x00',                     # the string
    pickle.TUPLE2, pickle.REDUCE,               # call add

    pickle.BINGET, b'\x02',                     # getitem
    pickle.BINGET, b'\x00',                     # the string
    pickle.BINGET, b'\x03',                     # slice
    pickle.BININT1, b'\x04',                    # 4
    pickle.NONE,                                # None
    pickle.TUPLE2, pickle.REDUCE,               # call slice --> slice(4, None)
    pickle.TUPLE2, pickle.REDUCE,               # call getitem --> string[4:]

    pickle.TUPLE2, pickle.REDUCE,               # call add

    pickle.STOP,                                # STOP
)


def make_golfed_pickle():
    part_1 = b''.join(PART_1)
    part_2 = b''.join(GOLFED_PART_2)
    # Now, we just have to swap in the correct length (of the string) as bytes
    # 3:7, and duplicate everything appropriately.
    length = len(part_1) + 1 + len(part_2)
    return (part_1 + b'%c' % length) * 2 + part_2 * 2


def check_pickle(data):
    assert data == pickle.loads(data)


def main(filename, golfed):
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
