import struct
from collections import namedtuple

from .tools import labels, formats


# Structures sourced from the indispensible Wikipedia page on the Design of the
# FAT file system [1]. Note that we're using the DOS 3.31 BPB definition below
# as it's used in all modern FAT-12/16/32 implementations (and we're not
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
        namedtuple('BIOSParameterBlock', labels(BIOS_PARAMETER_BLOCK))):
    """
    A :func:`~collections.namedtuple` representing the `BIOS Parameter Block`_
    found at the very start of a FAT file system (of any type). This provides
    several (effectively unused) legacy fields, but also several fields still
    used exclusively in later FAT variants (like the count of FAT-32 sectors).

    .. _BIOS Parameter Block: https://en.wikipedia.org/wiki/Design_of_the_FAT_file_system#BIOS_Parameter_Block
    """
    __slots__ = ()
    _FORMAT = struct.Struct(formats(BIOS_PARAMETER_BLOCK))

    def __bytes__(self):
        return self._FORMAT.pack(*self)

    @classmethod
    def from_bytes(cls, s):
        """
        Construct a :class:`BIOSParameterBlock` from the byte-string *s*.
        """
        return cls(*cls._FORMAT.unpack(s))

    @classmethod
    def from_buffer(cls, buf, offset=0):
        """
        Construct a :class:`BIOSParameterBlock` from the specified *offset*
        (which defaults to 0) in the buffer protocol object, *buf*.
        """
        return cls(*cls._FORMAT.unpack_from(buf, offset))


EXTENDED_BIOS_PARAMETER_BLOCK = """
B     drive_number
1x    reserved
B     extended_boot_sig
4s    volume_id
11s   volume_label
8s    file_system
"""

class ExtendedBIOSParameterBlock(
        namedtuple('ExtendedBIOSParameterBlock',
                   labels(EXTENDED_BIOS_PARAMETER_BLOCK))):
    """
    A :func:`~collections.namedtuple` representing the `Extended BIOS Parameter
    Block`_ found either immediately after the `BIOS Parameter Block`_ (in
    FAT-12 and FAT-16 formats), or after the `FAT32 BIOS Parameter Block`_ (in
    FAT-32 formats).

    This provides several (effectively unused) legacy fields, but also provides
    the "file_system" field which is used as the primary means of
    distinguishing the different FAT types (see :func:`nobodd.fs.fat_type`),
    and the self-explanatory "volume_label" field.

    .. _BIOS Parameter Block: https://en.wikipedia.org/wiki/Design_of_the_FAT_file_system#BIOS_Parameter_Block
    .. _Extended BIOS Parameter Block: https://en.wikipedia.org/wiki/Design_of_the_FAT_file_system#Extended_BIOS_Parameter_Block
    .. _FAT32 BIOS Parameter Block: https://en.wikipedia.org/wiki/Design_of_the_FAT_file_system#FAT32_Extended_BIOS_Parameter_Block
    """
    __slots__ = ()
    _FORMAT = struct.Struct(formats(EXTENDED_BIOS_PARAMETER_BLOCK))

    def __bytes__(self):
        return self._FORMAT.pack(*self)

    @classmethod
    def from_bytes(cls, s):
        """
        Construct a :class:`ExtendedBIOSParameterBlock` from the byte-string
        *s*.
        """
        return cls(*cls._FORMAT.unpack(s))

    @classmethod
    def from_buffer(cls, buf, offset=0):
        """
        Construct a :class:`ExtendedBIOSParameterBlock` from the specified
        *offset* (which defaults to 0) in the buffer protocol object, *buf*.
        """
        return cls(*cls._FORMAT.unpack_from(buf, offset))


FAT32_BIOS_PARAMETER_BLOCK = """
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
                   labels(FAT32_BIOS_PARAMETER_BLOCK))):
    """
    A :func:`~collections.namedtuple` representing the `FAT32 BIOS Parameter
    Block`_ found immediately after the `BIOS Parameter Block`_ in FAT-32
    formats. In FAT-12 and FAT-16 formats it should not occur.

    This crucially provides the cluster containing the root directory (which is
    structured as a normal sub-directory in FAT-32) as well as the number of
    sectors per FAT, specifically for FAT-32. All other fields are ignored by
    this implementation.

    .. _FAT32 BIOS Parameter Block: https://en.wikipedia.org/wiki/Design_of_the_FAT_file_system#FAT32_Extended_BIOS_Parameter_Block
    """
    __slots__ = ()
    _FORMAT = struct.Struct(formats(FAT32_BIOS_PARAMETER_BLOCK))

    def __bytes__(self):
        return self._FORMAT.pack(*self)

    @classmethod
    def from_bytes(cls, s):
        """
        Construct a :class:`FAT32BIOSParameterBlock` from the byte-string *s*.
        """
        return cls(*cls._FORMAT.unpack(s))

    @classmethod
    def from_buffer(cls, buf, offset=0):
        """
        Construct a :class:`FAT32BIOSParameterBlock` from the specified
        *offset* (which defaults to 0) in the buffer protocol object, *buf*.
        """
        return cls(*cls._FORMAT.unpack_from(buf, offset))


DIRECTORY_ENTRY = """
8s    filename
3s    ext
B     attr
B     attr2
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
    """
    A :func:`~collections.namedtuple` representing a FAT `directory entry`_.
    This is a fixed-size structure which repeats up to the size of a cluster
    within a FAT root or sub-directory.

    It contains the (8.3 sized) filename of an entry, the size in bytes, the
    cluster at which the entry's data starts, the entry's attributes (which
    determine whether the entry represents a file or another sub-directory),
    and (depending on the format), the creation, modification, and access
    timestamps.

    Entries may represent deleted items in which case the first character of
    the *filename* will be 0xE5. If the *attr* is 0x0F, the entry is actually a
    long-filename entry and should be converted to :class:`LongFilenameEntry`.
    If *attr* is 0x10, the entry represents a sub-directory. See `directory
    entry`_ for more details.

    .. _directory entry: https://en.wikipedia.org/wiki/Design_of_the_FAT_file_system#Directory_entry
    """
    __slots__ = ()
    _FORMAT = struct.Struct(formats(DIRECTORY_ENTRY))

    def __bytes__(self):
        return self._FORMAT.pack(*self)

    @classmethod
    def from_bytes(cls, s):
        """
        Construct a :class:`DirectoryEntry` from the byte-string *s*.
        """
        return cls(*cls._FORMAT.unpack(s))

    @classmethod
    def from_buffer(cls, buf, offset=0):
        """
        Construct a :class:`DirectoryEntry` from the specified *offset* (which
        defaults to 0) in the buffer protocol object, *buf*.
        """
        return cls(*cls._FORMAT.unpack_from(buf, offset))

    def to_buffer(self, buf, offset=0):
        """
        Write this :class:`DirectoryEntry` to *buf*, a buffer protocol object,
        at the specified *offset* (which defaults to 0).
        """
        self._FORMAT.pack_into(buf, offset, *self)

    @classmethod
    def iter_over(cls, buf):
        """
        Iteratively yields successive :class:`DirectoryEntry` instances from
        the buffer protocol object, *buf*.

        .. note::

            This method is entirely dumb and does not check whether the yielded
            instances are valid; it is up to the caller to determine the
            validity of entries.
        """
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
    """
    A :func:`~collections.namedtuple` representing a FAT `long filename`_. This
    is a variant of the FAT `directory entry`_ where the *attr* field is 0x0F.

    Several of these entries will appear before their corresponding
    :class:`DirectoryEntry`, but will be in *reverse* order. A *checksum* is
    incorporated for additional verification, and a *sequence* number
    indicating the number of segments, and which one is "last" (first in the
    byte-stream, but last in character order).

    .. _directory entry: https://en.wikipedia.org/wiki/Design_of_the_FAT_file_system#Directory_entry
    .. _long filename: https://en.wikipedia.org/wiki/Design_of_the_FAT_file_system#VFAT_long_file_names
    """
    __slots__ = ()
    _FORMAT = struct.Struct(formats(LONG_FILENAME_ENTRY))

    def __bytes__(self):
        return self._FORMAT.pack(*self)

    @classmethod
    def from_bytes(cls, s):
        """
        Construct a :class:`LongFilenameEntry` from the byte-string *s*.
        """
        return cls(*cls._FORMAT.unpack(s))

    @classmethod
    def from_buffer(cls, buf, offset=0):
        """
        Construct a :class:`LongFilenameEntry` from the specified *offset*
        (which defaults to 0) in the buffer protocol object, *buf*.
        """
        return cls(*cls._FORMAT.unpack_from(buf, offset))

    def to_buffer(self, buf, offset=0):
        """
        Write this :class:`LongFilenameEntry` to *buf*, a buffer protocol
        object, at the specified *offset* (which defaults to 0).
        """
        self._FORMAT.pack_into(buf, offset, *self)

    @classmethod
    def iter_over(cls, buf):
        """
        Iteratively yields successive :class:`LongFilenameEntry` instances from
        the buffer protocol object, *buf*.

        .. note::

            This method is entirely dumb and does not check whether the yielded
            instances are valid; it is up to the caller to determine the
            validity of entries.
        """
        return cls._FORMAT.iter_unpack(buf)
