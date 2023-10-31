"""
The data structures used in the FAT file-system.

.. autoclass:: BIOSParameterBlock

.. autoclass:: ExtendedBIOSParameterBlock

.. autoclass:: FAT32BIOSParameterBlock

.. autoclass:: DirectoryEntry

.. autoclass:: LongFilenameEntry
"""

import struct
from collections import namedtuple

from .tools import labels, formats


# Structures sourced from the indispensible Wikipedia page on the Design of the
# FAT file system [1]. Note that we're using the DOS 3.31 BPB definition below
# as it's used in all modern FAT12/16/32 implementations (and we're not
# interested in supporting ancient FAT images here).
#
# [1]: https://en.wikipedia.org/wiki/Design_of_the_FAT_file_system

BIOS_PARAMETER_BLOCK = """
3x    jump_instruction
8s    oem_name
H     bytes_per_sector
B     sectors_per_cluster
H     reserved_sectors
B     fat_count
H     max_root_entries
H     fat16_total_sectors
B     media_descriptor
H     sectors_per_fat
H     sectors_per_track
H     heads_per_disk
I     hidden_sectors
I     fat32_total_sectors
"""

class BIOSParameterBlock(
        namedtuple('BIOSParameterBlock', labels(BOOT_PARAMETER_BLOCK))):
    """
    The `BIOS Parameter Block`_ is found at the very start of a FAT file system
    (of any type). It provides several (effectively unused) legacy fields, but
    also several fields still used exclusively in later FAT variants (like the
    count of FAT-32 sectors).

    .. _BIOS Parameter Block: https://en.wikipedia.org/wiki/Design_of_the_FAT_file_system#BIOS_Parameter_Block
    """
    __slots__ = ()
    _FORMAT = struct.Struct(formats(BOOT_PARAMETER_BLOCK))

    @classmethod
    def from_string(cls, s):
        """
        Construct a BIOSParameterBlock from the byte-string *s* which must be
        of the correct size.
        """
        return cls(*cls._FORMAT.unpack(s))

    @classmethod
    def from_buffer(cls, buf, offset=0):
        """
        Construct a BIOSParameterBlock from the buffer *buf* at the specified
        *offset* which defaults to 0.
        """
        return cls(*cls._FORMAT.unpack_from(buf, offset))


EXTENDED_BOOT_PARAMETER_BLOCK = """
B     drive_number
1x    reserved
B     extended_boot_sig
4s    volume_id
11s   volume_label
8s    file_system
"""

class ExtendedBIOSParameterBlock(
        namedtuple('ExtendedBIOSParameterBlock',
                   labels(EXTENDED_BOOT_PARAMETER_BLOCK))):
    """
    The `Extended BIOS Parameter Block`_ is found either immediately after the
    `BIOS Parameter Block`_ (in FAT-12 and FAT-16 formats), or after the
    `FAT32 BIOS Parameter Block`_ (in FAT-32 formats).

    It provides several (effectively unused) legacy fields, but also provides
    the "file_system" field which is used as the primary means of
    distinguishing the different FAT types (see :func:`nobodd.fs.fat_type`),
    and the self-explanatory "volume_label" field.

    .. _Extended BIOS Parameter Block: https://en.wikipedia.org/wiki/Design_of_the_FAT_file_system#Extended_BIOS_Parameter_Block
    """
    __slots__ = ()
    _FORMAT = struct.Struct(formats(EXTENDED_BOOT_PARAMETER_BLOCK))

    @classmethod
    def from_string(cls, s):
        return cls(*cls._FORMAT.unpack(s))

    @classmethod
    def from_buffer(cls, buf, offset=0):
        return cls(*cls._FORMAT.unpack_from(buf, offset))


FAT32_BOOT_PARAMETER_BLOCK = """
I     sectors_per_fat
H     mirror_flags
H     version
I     root_dir_cluster
H     info_sector
H     backup_sector
12x   reserved
"""

class FAT32BIOSParameterBlock(
        namedtuple('FAT32BIOSParameterBlock',
                   labels(FAT32_BOOT_PARAMETER_BLOCK))):
    __slots__ = ()
    _FORMAT = struct.Struct(formats(FAT32_BOOT_PARAMETER_BLOCK))

    @classmethod
    def from_string(cls, s):
        return cls(*cls._FORMAT.unpack(s))

    @classmethod
    def from_buffer(cls, buf, offset=0):
        return cls(*cls._FORMAT.unpack_from(buf, offset))


DIRECTORY_ENTRY = """
8s    filename
3s    ext
B     attr
1x    reserved
B     ctime_ms
H     ctime
H     cdate
H     adate
H     first_cluster_hi
H     mtime
H     mdate
H     first_cluster_lo
I     size
"""

class DirectoryEntry(namedtuple('DirectoryEntry', labels(DIRECTORY_ENTRY))):
    __slots__ = ()
    _FORMAT = struct.Struct(formats(DIRECTORY_ENTRY))

    @classmethod
    def from_string(cls, s):
        return cls(*cls._FORMAT.unpack(s))

    @classmethod
    def from_buffer(cls, buf, offset=0):
        return cls(*cls._FORMAT.unpack_from(buf, offset))

    @classmethod
    def iter_over(cls, buf):
        return cls._FORMAT.iter_unpack(buf)


LONG_FILENAME_ENTRY = """
B     sequence
10s   name_1
B     attr
1x    reserved
B     checksum
12s   name_2
H     first_cluster
4s    name_3
"""

class LongFilenameEntry(
        namedtuple('LongFilenameEntry', labels(LONG_FILENAME_ENTRY))):
    __slots__ = ()
    _FORMAT = struct.Struct(formats(LONG_FILENAME_ENTRY))

    @classmethod
    def from_string(cls, s):
        return cls(*cls._FORMAT.unpack(s))

    @classmethod
    def from_buffer(cls, buf, offset=0):
        return cls(*cls._FORMAT.unpack_from(buf, offset))

    @classmethod
    def iter_over(cls, buf):
        return cls._FORMAT.iter_unpack(buf)
