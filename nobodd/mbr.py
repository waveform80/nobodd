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
    """
    A :func:`~collections.namedtuple` representing the fields of the `MBR
    header`_.

    .. _MBR header:
        https://en.wikipedia.org/wiki/Master_boot_record#Sector_layout
    """
    __slots__ = ()
    _FORMAT = struct.Struct(formats(MBR_HEADER))

    def __bytes__(self):
        return self._FORMAT.pack(*self)

    @classmethod
    def from_bytes(cls, s):
        """
        Construct a :class:`MBRHeader` from the byte-string *s*.
        """
        return cls(*cls._FORMAT.unpack(s))

    @classmethod
    def from_buffer(cls, buf, offset=0):
        """
        Construct a :class:`MBRHeader` from the specified *offset* (which
        defaults to 0) in the buffer protocol object, *buf*.
        """
        return cls(*cls._FORMAT.unpack_from(buf, offset))

    @property
    def partitions(self):
        """
        Returns a sequence of the partitions defined by the header. This is
        always 4 elements long, and not all elements are guaranteed to be
        valid, or in order on the disk.
        """
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
I     first_lba
I     part_size
"""

class MBRPartition(namedtuple('MBRPartition', labels(MBR_PARTITION))):
    """
    A :func:`~collections.namedtuple` representing the fields of an `MBR
    partition entry`_.

    .. _MBR partition entry:
        https://en.wikipedia.org/wiki/Master_boot_record#Partition_table_entries
    """
    __slots__ = ()
    _FORMAT = struct.Struct(formats(MBR_PARTITION))

    def __bytes__(self):
        return self._FORMAT.pack(*self)

    @classmethod
    def from_bytes(cls, s):
        """
        Construct a :class:`MBRPartition` from the byte-string *s*.
        """
        return cls(*cls._FORMAT.unpack(s))

    @classmethod
    def from_buffer(cls, buf, offset=0):
        """
        Construct a :class:`MBRPartition` from the specified *offset* (which
        defaults to 0) in the buffer protocol object, *buf*.
        """
        return cls(*cls._FORMAT.unpack_from(buf, offset))
