import struct
from collections import namedtuple


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
H     fat16_max_root_entries
H     fat16_total_sectors
B     media_descriptor
H     fat16_sectors_per_fat
H     sectors_per_track
H     heads_per_disk
L     hidden_sectors
L     fat32_total_sectors
"""

class BootParameterBlock(namedtuple('BootParameterBlock', tuple(
    label
    for line in BOOT_PARAMETER_BLOCK.splitlines()
    if line
    for fmt, label in (line.split(None, 1),)
    if not fmt.endswith('x')
))):
    __slots__ = ()

    _FORMAT = struct.Struct('<' + ''.join(
        fmt
        for line in BOOT_PARAMETER_BLOCK.splitlines()
        if line
        for fmt, label in (line.split(None, 1),)
    ))

    @classmethod
    def from_string(cls, s):
        return cls(*cls._FORMAT.unpack(s))

    @classmethod
    def from_buffer(cls, buf, offset=0):
        return cls(*cls._FORMAT.unpack_from(buf, offset))

    @property
    def total_sectors(self):
        return self.fat16_total_sectors or self.fat32_total_sectors or 0

    @property
    def fat_type(self):
        return 'FAT32' if self.fat32_total_sectors else 'FAT16'
