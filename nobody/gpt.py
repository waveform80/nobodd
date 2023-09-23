import struct
from collections import namedtuple


# Structures sourced from the Wikipedia page on the GUID Partition Table [1].
#
# [1]: https://en.wikipedia.org/wiki/GUID_Partition_Table

GPT_HEADER = """
8s   signature
4s   revision
L    header_size
L    header_check
4x   reserved
Q    current_lba
Q    backup_lba
Q    first_usable_lba
Q    last_usable_lba
16s  disk_guid
Q    part_table_lba
L    part_table_size
L    part_entry_size
L    part_table_check
"""

class GPTHeader(namedtuple('GPTHeader', tuple(
    label
    for line in GPT_HEADER.splitlines()
    if line
    for fmt, label in (line.split(None, 1),)
    if not fmt.endswith('x')
))):
    __slots__ = ()

    _FORMAT = struct.Struct('<' + ''.join(
        fmt
        for line in GPT_HEADER.splitlines()
        if line
        for fmt, label in (line.split(None, 1),)
    ))

    @classmethod
    def from_string(cls, s):
        return cls(*cls._FORMAT.unpack(s))

    @classmethod
    def from_buffer(cls, buf, offset=0):
        return cls(*cls._FORMAT.unpack_from(buf, offset))


GPT_PARTITION = """
16s  type_guid
16s  part_guid
Q    first_lba
Q    last_lba
Q    flags
72s  part_label
"""

class GPTPartition(namedtuple('GPTPartition', tuple(
    label
    for line in GPT_PARTITION.splitlines()
    if line
    for fmt, label in (line.split(None, 1),)
    if not fmt.endswith('x')
))):
    __slots__ = ()

    _FORMAT = struct.Struct('<' + ''.join(
        fmt
        for line in GPT_PARTITION.splitlines()
        if line
        for fmt, label in (line.split(None, 1),)
    ))

    @classmethod
    def from_string(cls, s):
        return cls(*cls._FORMAT.unpack(s))

    @classmethod
    def from_buffer(cls, buf, offset=0):
        return cls(*cls._FORMAT.unpack_from(buf, offset))
