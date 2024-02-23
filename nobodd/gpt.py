# nobodd: a boot configuration tool for the Raspberry Pi
#
# Copyright (c) 2023-2024 Dave Jones <dave.jones@canonical.com>
# Copyright (c) 2023-2024 Canonical Ltd.
#
# SPDX-License-Identifier: GPL-3.0

import struct
from collections import namedtuple

from .tools import labels, formats


# Structures sourced from the Wikipedia page on the GUID Partition Table [1].
#
# [1]: https://en.wikipedia.org/wiki/GUID_Partition_Table

GPT_HEADER = """
8s   signature
I    revision
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

class GPTHeader(namedtuple('GPTHeader', labels(GPT_HEADER))):
    """
    A :func:`~collections.namedtuple` representing the fields of the `GPT
    header`_.

    .. _GPT header:
        https://en.wikipedia.org/wiki/GUID_Partition_Table#Partition_table_header_(LBA_1)
    """
    __slots__ = ()
    _FORMAT = struct.Struct(formats(GPT_HEADER))

    def __bytes__(self):
        return self._FORMAT.pack(*self)

    @classmethod
    def from_bytes(cls, s):
        """
        Construct a :class:`GPTHeader` from the byte-string *s*.
        """
        return cls(*cls._FORMAT.unpack(s))

    @classmethod
    def from_buffer(cls, buf, offset=0):
        """
        Construct a :class:`GPTHeader` from the specified *offset* (which
        defaults to 0) in the buffer protocol object, *buf*.
        """
        return cls(*cls._FORMAT.unpack_from(buf, offset))


GPT_PARTITION = """
16s  type_guid
16s  part_guid
Q    first_lba
Q    last_lba
Q    flags
72s  part_label
"""

class GPTPartition(namedtuple('GPTPartition', labels(GPT_PARTITION))):
    """
    A :func:`~collections.namedtuple` representing the fields of a `GPT
    entry`_.

    .. _GPT entry:
        https://en.wikipedia.org/wiki/GUID_Partition_Table#Partition_entries_(LBA_2%E2%80%9333)
    """
    __slots__ = ()
    _FORMAT = struct.Struct(formats(GPT_PARTITION))

    def __bytes__(self):
        return self._FORMAT.pack(*self)

    @classmethod
    def from_bytes(cls, s):
        """
        Construct a :class:`GPTPartition` from the byte-string *s*.
        """
        return cls(*cls._FORMAT.unpack(s))

    @classmethod
    def from_buffer(cls, buf, offset=0):
        """
        Construct a :class:`GPTPartition` from the specified *offset* (which
        defaults to 0) in the buffer protocol object, *buf*.
        """
        return cls(*cls._FORMAT.unpack_from(buf, offset))
