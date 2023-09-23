import struct
from collections import namedtuple


# Structures sourced from the Wikipedia page on the Master Boot Record [1],
# specifically the "structure of a classic generic MBR". We don't bother with
# of the later more complicated variants because the only thing we care about
# is the four primary partitions anyway.
#
# [1]: https://en.wikipedia.org/wiki/Master_boot_record

MBR_HEADER = """
446x  bootstrap_code
16s   partition_1
16s   partition_2
16s   partition_3
16s   partition_4
H     boot_sig
"""

class MBRHeader(namedtuple('MBRHeader', tuple(
    label
    for line in MBR_HEADER.splitlines()
    if line
    for fmt, label in (line.split(None, 1),)
    if not fmt.endswith('x')
))):
    __slots__ = ()

    _FORMAT = struct.Struct('<' + ''.join(
        fmt
        for line in MBR_HEADER.splitlines()
        if line
        for fmt, label in (line.split(None, 1),)
    ))

    @classmethod
    def from_string(cls, s):
        return cls(*cls._FORMAT.unpack(s))

    @classmethod
    def from_buffer(cls, buf, offset=0):
        return cls(*cls._FORMAT.unpack_from(buf, offset))


MBR_PARTITION = """
B     status
3s    first_chs
B     part_type
3s    last_chs
L     first_lba
L     part_size
"""

class MBRPartition(namedtuple('MBRPartition', tuple(
    label
    for line in MBR_PARTITION.splitlines()
    if line
    for fmt, label in (line.split(None, 1),)
    if not fmt.endswith('x')
))):
    __slots__ = ()

    _FORMAT = struct.Struct('<' + ''.join(
        fmt
        for line in MBR_PARTITION.splitlines()
        if line
        for fmt, label in (line.split(None, 1),)
    ))

    @classmethod
    def from_string(cls, s):
        return cls(*cls._FORMAT.unpack(s))

    @classmethod
    def from_buffer(cls, buf, offset=0):
        return cls(*cls._FORMAT.unpack_from(buf, offset))
