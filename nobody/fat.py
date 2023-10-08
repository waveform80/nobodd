import struct
from collections import namedtuple

from .tools import labels, formats


# Structures sourced from the indispensible Wikipedia page on the Design of the
# FAT file system [1]. Note that we're using the DOS 3.31 BPB definition below
# as it's used in all modern FAT12/16/32 implementations (and we're not
# interested in supporting ancient FAT images here).
#
# [1]: https://en.wikipedia.org/wiki/Design_of_the_FAT_file_system

BOOT_PARAMETER_BLOCK = """
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

class BootParameterBlock(
        namedtuple('BootParameterBlock', labels(BOOT_PARAMETER_BLOCK))):
    __slots__ = ()
    _FORMAT = struct.Struct(formats(BOOT_PARAMETER_BLOCK))

    @classmethod
    def from_string(cls, s):
        return cls(*cls._FORMAT.unpack(s))

    @classmethod
    def from_buffer(cls, buf, offset=0):
        return cls(*cls._FORMAT.unpack_from(buf, offset))


EXTENDED_BOOT_PARAMETER_BLOCK = """
B     drive_number
1x    reserved
B     extended_boot_sig
4s    volume_id
11s   volume_label
8s    file_system
"""

class ExtendedBootParameterBlock(
        namedtuple('ExtendedBootParameterBlock',
                   labels(EXTENDED_BOOT_PARAMETER_BLOCK))):
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

class FAT32BootParameterBlock(
        namedtuple('FAT32BootParameterBlock',
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
