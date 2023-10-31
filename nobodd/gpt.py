import struct
from collections import namedtuple

from .tools import labels, formats


# Structures sourced from the Wikipedia page on the GUID Partition Table [1].
#
# [1]: https://en.wikipedia.org/wiki/GUID_Partition_Table

GPT_HEADER = """
8s   signature
4s   revision
I    header_size
I    header_crc32
4x   reserved
Q    current_lba
Q    backup_lba
Q    first_usable_lba
Q    last_usable_lba
16s  disk_guid
Q    part_table_lba
I    part_table_size
I    part_entry_size
I    part_table_crc32
"""

class GPTHeader(namedtuple('GPTHeader', labels(GPT_HEADER) + ('raw',))):
    __slots__ = ()
    _FORMAT = struct.Struct(formats(GPT_HEADER))

    @classmethod
    def from_string(cls, s):
        return cls(*cls._FORMAT.unpack(s), s)

    @classmethod
    def from_buffer(cls, buf, offset=0):
        return cls(*cls._FORMAT.unpack_from(buf, offset),
                   buf[offset:offset + cls._FORMAT.size])


GPT_PARTITION = """
16s  type_guid
16s  part_guid
Q    first_lba
Q    last_lba
Q    flags
72s  part_label
"""

class GPTPartition(namedtuple('GPTPartition', labels(GPT_PARTITION))):
    __slots__ = ()
    _FORMAT = struct.Struct(formats(GPT_PARTITION))

    @classmethod
    def from_string(cls, s):
        return cls(*cls._FORMAT.unpack(s))

    @classmethod
    def from_buffer(cls, buf, offset=0):
        return cls(*cls._FORMAT.unpack_from(buf, offset))
