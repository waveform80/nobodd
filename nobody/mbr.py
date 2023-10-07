import struct
from collections import namedtuple

from .tools import labels, formats


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

class MBRHeader(namedtuple('MBRHeader', labels(MBR_HEADER))):
    __slots__ = ()
    _FORMAT = struct.Struct(formats(MBR_HEADER))

    @classmethod
    def from_string(cls, s):
        return cls(*cls._FORMAT.unpack(s))

    @classmethod
    def from_buffer(cls, buf, offset=0):
        return cls(*cls._FORMAT.unpack_from(buf, offset))

    @property
    def partitions(self):
        return (
            self.partition_1,
            self.partition_2,
            self.partition_3,
            self.partition_4,
        )


MBR_PARTITION = """
B     status
3s    first_chs
B     part_type
3s    last_chs
L     first_lba
L     part_size
"""

class MBRPartition(namedtuple('MBRPartition', labels(MBR_PARTITION))):
    __slots__ = ()
    _FORMAT = struct.Struct(formats(MBR_PARTITION))

    @classmethod
    def from_string(cls, s):
        return cls(*cls._FORMAT.unpack(s))

    @classmethod
    def from_buffer(cls, buf, offset=0):
        return cls(*cls._FORMAT.unpack_from(buf, offset))