#!/usr/bin/env python3
import pickle
import struct


# So here's the plan.  We're going to make a pickle which will consist of two
# parts, each of which will be repeated twice to form the whole pickle.

# Part 1 is pretty simple: it consists of the pickle version 3 header
# followed by the preamble to the string consisting of part 1 followed by part
# 2.  (We'll fill in its length later.)
PART_1 = (
    b'\x80\x03'                                 # pickle version 3 header
    b'B'                                        # bytestring (no length)
)

# After part 1 executes, our stack will have a single value, which will be the
# string consisting of part 1 + part 2 (hereafter "the string").  Part 2 will
# consist of everything we need to assemble that into the whole pickle: namely
# we need to split it at index 7 and then concatenate each half twice.

# Conveniently, pickle has a way of calling an arbitrary function.  First, we
# load it with c<module>\n<name>\n.  Then, we put the arg-tuple on the stack.
# Finally, we call "R" (for reduce) which calls the function on the arguments.
# To do the string slicing, we'll call
#   operator.getitem(<str>, builtins.slice(start, end))
# and we'll then add those up with operator.add.
# So here we go:
PART_2 = (
    b'q\x00'                                    # store the string in memo 0
    b'coperator\ngetitem\n'                     # put operator.getitem on stack
    b'q\x01'                                    # store it in memo 1
    b'cbuiltins\nslice\n'                       # put slice on stack
    b'q\x02'                                    # store it in memo 2
    b'K\x00K\x07\x86'                           # put (0, 7) on stack
    b'R'                                        # reduce --> slice(0, 7)
    b'q\x03'                                    # store that in memo 3
    b'h\x02'                                    # load slice from memo
    b'K\x07N\x86'                               # put (7, None) on stack
    b'R'                                        # reduce -> slice(7, None)
    b'q\x04'                                    # store that in memo 4
    b'h\x01'                                    # load getitem from memo
    b'h\x00h\x03\x86R'                          # ... and call --> string[:7]
    b'q\x05'                                    # store that in memo 5
    b'h\x01'                                    # load getitem from memo again
    b'h\x00h\x04\x86R'                          # ... and call --> string[7:]
    b'q\x06'                                    # store that in memo 6
    b'coperator\nadd\n'                         # put operator.add on stack
    b'2'                                        # make 2 copies
    b'h\x05h\x00\x86R'                          # add string[:7] + string
    b'h\x06\x86R'                               # add string[7:] to that
    b'.'                                        # STOP
)


def make_pickle():
    # Now, we just have to swap in the correct length (of the string) as bytes
    # 3:7, and duplicate everything appropriately.
    length = len(PART_1) + 4 + len(PART_2)
    return (PART_1 + struct.pack('<I', length)) * 2 + PART_2 * 2


def check_pickle(data):
    assert data == pickle.loads(data)


def main(filename='quine.pickle'):
    data = make_pickle()
    check_pickle(data)
    with open(filename, 'wb') as f:
        f.write(data)
    print(f'Quine works!  Wrote to {filename}.')


if __name__ == '__main__':
    main()
