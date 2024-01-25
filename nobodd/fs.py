import io
import os
import re
import errno
import struct
import weakref
import warnings
import datetime as dt
from abc import abstractmethod
from collections import abc
from itertools import islice

from .fat import (
    BIOSParameterBlock,
    ExtendedBIOSParameterBlock,
    FAT32BIOSParameterBlock,
    FAT32InfoSector,
    DirectoryEntry,
    LongFilenameEntry,
    lfn_valid,
    lfn_checksum,
)
from .path import FatPath, get_cluster
from .tools import (
    pairwise,
    encode_timestamp,
    any_match,
    exclude,
)


class FatWarning(Warning):
    """
    Base class for warnings issued by :class:`FatFileSystem`.
    """

class DirtyFileSystem(FatWarning):
    """
    Raised when opening a FAT file-system that has the "dirty" flag set in the
    second entry of the FAT.
    """

class DamagedFileSystem(FatWarning):
    """
    Raised when opening a FAT file-system that has the I/O errors flag set in
    the second entry of the FAT.
    """


# The following references were invaluable in constructing this implementation;
# the wikipedia page on the Design of the FAT File system [1], Jonathan
# de Boyne Pollard's notes on determination of FAT widths [2], the
# Microsoft Extensible Firmware Initiative FAT32 File System Specification [3],
# and Electronic Lives Mfg.'s notes on the FAT File system [4].
#
# [1]: https://en.wikipedia.org/wiki/Design_of_the_FAT_file_system
# [2]: http://homepage.ntlworld.com/jonathan.deboynepollard/FGA/determining-fat-widths.html
# [3]: http://download.microsoft.com/download/1/6/1/161ba512-40e2-4cc9-843a-923143f3456c/fatgen103.doc
# [4]: http://elm-chan.org/docs/fat_e.html
#
# Future maintainers, please note [2] is a dead link at the time of writing;
# use archive.org to retrieve. [1] is the best starting point although it does
# attempt to drown the casual reader in detail, a lot of which can be ignored
# (I have no interest in supporting, for example, DR-DOS' DELWATCH mechanism,
# or CP/M-86's user attributes).
#
# [3] is extremely useful in some places, though you have to put up with the
# slighly condescending tone as the author argues that everyone else habitually
# gets it wrong, and Microsoft's detection algorithms are The One True Way
# (reading [2] provides a good antidote to this).
#
# Unfortunately, in other places [3] is dreadfully vague for a spec (e.g. valid
# SFN / LFN characters). Refer back to [1] for these. [4] is obviously partly
# drawn from [3], but adds some extremely important notes that others have
# omitted (or not noticed), such as the fact that volume labels can
# legitimately duplicate the name of a later file in the root directory.

class FatFileSystem:
    """
    Represents a `FAT`_ file-system, contained at the start of the buffer
    object *mem*. If *atime* is :data:`False`, the default, then accesses to
    files will *not* update the atime field in file meta-data (when the
    underlying *mem* mapping is writable). Finally, *encoding* specifies the
    character set used for decoding and encoding DOS short filenames.

    This class supports the FAT-12, FAT-16, and FAT-32 formats, and will
    automatically determine which to use from the headers found at the start of
    *mem*. The type in use may be queried from :attr:`fat_type`. Of primary use
    is the :attr:`root` attribute which provides a
    :class:`~nobodd.path.FatPath` instance representing the root directory of
    the file-system.

    Instances can (and should) be used as a context manager; exiting the
    context will call the :meth:`close` method implicitly. If certain header
    bits are set, :exc:`DamagedFileSystem` and :exc:`DirtyFileSystem` warnings
    may be generated upon opening.

    .. _FAT: https://en.wikipedia.org/wiki/Design_of_the_FAT_file_system
    """
    def __init__(self, mem, atime=False, encoding='iso-8859-1'):
        mem = memoryview(mem)
        self._fat_type, bpb, ebpb, ebpb_fat32 = fat_type(mem)
        self._atime = atime
        self._encoding = encoding
        # TODO: Replace with root volume label if == b'NO NAME    '
        self._label = ebpb.volume_label.decode(encoding, 'replace').rstrip(' ')

        total_sectors = bpb.fat16_total_sectors or bpb.fat32_total_sectors
        if total_sectors == 0 and ebpb.extended_boot_sig == 0x29:
            # FAT32 with >2**32 sectors uses file-system label as an 8-byte int
            total_sectors, = struct.unpack('<Q', ebpb.file_system)
        fat_size = (
            bpb.sectors_per_fat if ebpb_fat32 is None else
            ebpb_fat32.sectors_per_fat) * bpb.bytes_per_sector
        if fat_size == 0:
            raise ValueError(f'{self._fat_type.upper()} sectors per FAT is 0')
        root_size = bpb.max_root_entries * DirectoryEntry._FORMAT.size
        if root_size % bpb.bytes_per_sector:
            raise ValueError(
                f'Max. root entries, {bpb.max_root_entries} creates a root '
                f'directory region that is not a multiple of sector size, '
                f'{bpb.bytes_per_sector}')
        info_offset = (
            ebpb_fat32.info_sector * bpb.bytes_per_sector
            if ebpb_fat32 is not None
            and ebpb_fat32.info_sector not in (0, 0xFFFF)
            else None)
        end_offset = total_sectors * bpb.bytes_per_sector
        fat_offset = bpb.reserved_sectors * bpb.bytes_per_sector
        root_offset = fat_offset + (fat_size * bpb.fat_count)
        data_offset = root_offset + root_size

        self._fat = {
            'fat12': Fat12Table,
            'fat16': Fat16Table,
            'fat32': Fat32Table,
        }[self._fat_type](
            mem[fat_offset:root_offset], fat_size,
            mem[info_offset:info_offset + bpb.bytes_per_sector]
            if info_offset is not None else None)
        self._data = FatClusters(
            mem[data_offset:end_offset],
            bpb.bytes_per_sector * bpb.sectors_per_cluster)
        if self._fat_type == 'fat32':
            if ebpb_fat32 is None:
                raise ValueError(
                    'File-system claims to be FAT32 but has no FAT32 EBPB')
            self._root = ebpb_fat32.root_dir_cluster
        else:
            self._root = mem[root_offset:root_offset + root_size]

        # Check the root directory is structured as expected. Apparently some
        # "non-mainstream" operating systems can use a variable-sized root
        # directory on FAT-12/16, but we're not expecting to deal with any of
        # those
        if self._fat_type == 'fat32' and bpb.max_root_entries != 0:
            raise ValueError(
                f'Max. root entries must be 0 for {self._fat_type.upper()}')
        elif self._fat_type != 'fat32' and bpb.max_root_entries == 0:
            raise ValueError(
                f'Max. root entries must be non-zero for {self._fat_type.upper()}')
        # Check the clean and damaged bits; these are only present on FAT-16
        # and FAT-32 volumes
        if self._fat_type != 'fat12':
            clean = (
                (self._fat_type == 'fat16' and (self._fat[1] & 0x8000)) or
                (self._fat_type == 'fat32' and (self._fat[1] & 0x8000000)))
            errors = not (
                (self._fat_type == 'fat16' and (self._fat[1] & 0x4000)) or
                (self._fat_type == 'fat32' and (self._fat[1] & 0x4000000)))
            if not clean:
                warnings.warn(DirtyFileSystem(
                    'File-system has the dirty bit set'))
            if errors:
                warnings.warn(DamagedFileSystem(
                    'File-system has the I/O errors bit set'))

    def __repr__(self):
        return (
            f'<{self.__class__.__name__} label={self.label!r} '
            f'fat_type={self.fat_type!r}>')

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        """
        Releases the memory references derived from the buffer the instance was
        constructed with. This method is idempotent.
        """
        if self._fat is not None:
            self._fat.close()
            self._data.close()
            if self._fat_type != 'fat32':
                self._root.release()
            self._fat = None
            self._data = None
            self._root = None

    @property
    def readonly(self):
        """
        Returns :data:`True` if the underlying buffer is read-only.
        """
        return self._data.readonly

    def open_dir(self, cluster):
        """
        Opens the sub-directory in the specified *cluster*, returning a
        :class:`FatDirectory` instance representing it.

        .. warning::

            This method is intended for internal use by the
            :class:`~nobodd.path.FatPath` class.
        """
        if cluster == 0:
            if self._fat_type == 'fat32':
                return Fat32Root(self, self._root, self._encoding)
            elif self._fat_type == 'fat16':
                return Fat16Root(self._root, self._encoding)
            else:
                return Fat12Root(self._root, self._encoding)
        else:
            return FatSubDirectory(self, cluster, self._encoding)

    def open_file(self, cluster, mode='rb'):
        """
        Opens the file at the specified *cluster*, returning a :class:`FatFile`
        instance representing it with the specified *mode*. Note that the
        :class:`FatFile` instance returned by this method has no directory
        entry associated with it.

        .. warning::

            This method is intended for internal use by the
            :class:`~nobodd.path.FatPath` class, specifically for "files"
            underlying the sub-directory structure which do not have an
            associated size (other than that dictated by their FAT chain of
            clusters).
        """
        return FatFile.from_cluster(self, cluster, mode)

    def open_entry(self, index, entry, mode='rb'):
        """
        Opens the specified *entry*, which must be a
        :class:`~nobodd.fat.DirectoryEntry` instance, which must be a member of
        *index*, an instance of :class:`FatDirectory`. Returns a
        :class:`FatFile` instance associated with the specified *entry*. This
        permits writes to the file to be properly recorded in the corresponding
        directory entry.

        .. warning::

            This method is intended for internal use by the
            :class:`~nobodd.path.FatPath` class.
        """
        return FatFile.from_entry(self, index, entry, mode)

    @property
    def fat(self):
        """
        A :class:`FatTable` sequence representing the FAT table itself.

        .. warning::

            This attribute is intended for internal use by the :class:`FatFile`
            class.
        """
        return self._fat

    @property
    def clusters(self):
        """
        A :class:`FatClusters` sequence representing the clusters containing
        the data stored in the file-system.

        .. warning::

            This attribute is intended for internal use by the :class:`FatFile`
            class.
        """
        return self._data

    @property
    def fat_type(self):
        """
        Returns a :class:`str` indicating the type of `FAT`_ file-system
        present. Returns one of "fat12", "fat16", or "fat32".
        """
        return self._fat_type

    @property
    def label(self):
        """
        Returns the label from the header of the file-system. This is an ASCII
        string up to 11 characters long.
        """
        return self._label

    @property
    def sfn_encoding(self):
        """
        The encoding used for short (8.3) filenames. This defaults to
        "iso-8859-1" but unfortunately there's no way of determining the
        correct codepage for these.
        """
        return self._encoding

    @property
    def atime(self):
        """
        If the underlying mapping is writable, then atime (last access time)
        will be updated upon reading the content of files, when this property
        is :data:`True` (the default is :data:`False`).
        """
        return self._atime

    @property
    def root(self):
        """
        Returns a :class:`~nobodd.path.FatPath` instance (a
        :class:`~pathlib.Path`-like object) representing the root directory of
        the FAT file-system. For example::

            from nobodd.disk import DiskImage
            from nobodd.fs import FatFileSystem

            with DiskImage('test.img') as img:
                with FatFileSystem(img.partitions[1].data) as fs:
                    print('ls /')
                    for p in fs.root.iterdir():
                        print(p.name)

        .. note::

            This is intended to be the primary entry-point for querying and
            manipulating the file-system at the high level. Only use the
            :attr:`fat` and :attr:`clusters` attributes if you want to explore
            the file-system at a low level.
        """
        return FatPath._from_index(self, self.open_dir(0))


def fat_type(mem):
    """
    Given a `FAT`_ file-system at the start of the buffer *mem*, determine its
    type, and decode its headers. Returns a four-tuple containing:

    * one of the strings "fat12", "fat16", or "fat32"

    * a :class:`~nobodd.fat.BIOSParameterBlock` instance

    * a :class:`~nobodd.fat.ExtendedBIOSParameterBlock` instance

    * a :class:`~nobodd.fat.FAT32BIOSParameterBlock`, if one is present, or
      :data:`None` otherwise
    """
    fat_types = {
        b'FAT     ': None,
        b'FAT12   ': 'fat12',
        b'FAT16   ': 'fat16',
        b'FAT32   ': 'fat32',
    }
    bpb = BIOSParameterBlock.from_buffer(mem)
    ebpb = ExtendedBIOSParameterBlock.from_buffer(
        mem, BIOSParameterBlock._FORMAT.size)
    try:
        fat_type = fat_types[ebpb.file_system]
        if fat_type is not None:
            return fat_type, bpb, ebpb, None
    except KeyError:
        pass
    if ebpb.extended_boot_sig in (0x28, 0x29):
        fat_type = fat_type_from_count(bpb, ebpb, None)
        return fat_type, bpb, ebpb, None
    ebpb_fat32 = FAT32BIOSParameterBlock.from_buffer(
        mem, BIOSParameterBlock._FORMAT.size)
    ebpb = ExtendedBIOSParameterBlock.from_buffer(
        mem, BIOSParameterBlock._FORMAT.size +
        FAT32BIOSParameterBlock._FORMAT.size)
    try:
        fat_type = fat_types[ebpb.file_system]
        if fat_type is not None:
            return fat_type, bpb, ebpb, ebpb_fat32
    except KeyError:
        pass
    if ebpb.extended_boot_sig in (0x28, 0x29):
        fat_type = fat_type_from_count(bpb, ebpb, ebpb_fat32)
        return fat_type, bpb, ebpb, ebpb_fat32
    raise ValueError(
        'Could not find file-system type or extended boot signature')


def fat_type_from_count(bpb, ebpb, ebpb_fat32):
    """
    Derives the type of the `FAT`_ file-system when it cannot be determined
    directly from the *bpb* and *ebpb* headers (the
    :class:`~nobodd.fat.BIOSParameterBlock`, and
    :class:`~nobodd.fat.ExtendedBIOSParameterBlock` respectively).

    Uses `known limits`_ on the number of clusters to derive the type of FAT in
    use. Returns one of the strings "fat12", "fat16", or "fat32".

    .. _known limits:
        https://en.wikipedia.org/wiki/Design_of_the_FAT_file_system#Size_limits
    """
    total_sectors = bpb.fat16_total_sectors or bpb.fat32_total_sectors
    if total_sectors == 0 and ebpb.extended_boot_sig == 0x29:
        # FAT32 with >2**32 sectors uses file-system label as an 8-byte int
        total_sectors, = struct.unpack('<Q', ebpb.file_system)
    fat_sectors = (
        bpb.fat_count *
        (bpb.sectors_per_fat if ebpb_fat32 is None else
         ebpb_fat32.sectors_per_fat))
    root_sectors = (
        (bpb.max_root_entries * DirectoryEntry._FORMAT.size) +
        (bpb.bytes_per_sector - 1)) // bpb.bytes_per_sector
    data_offset = bpb.reserved_sectors + fat_sectors + root_sectors
    data_clusters = (total_sectors - data_offset) // bpb.sectors_per_cluster
    return (
        'fat12' if data_clusters < 4085 else
        'fat16' if data_clusters < 65525 else
        'fat32')


class FatTable(abc.MutableSequence):
    """
    Abstract :class:`~collections.abc.MutableSequence` class representing the
    FAT table itself.

    This is the basis for :class:`Fat12Table`, :class:`Fat16Table`, and
    :class:`Fat32Table`. While all the implementations are potentially mutable
    (if the underlying memory mapping is writable), only direct replacement of
    FAT entries is valid. Insertion and deletion will raise :exc:`TypeError`.

    A concrete class is constructed by :class:`FatFileSystem` (based on the
    type of FAT format found). The :meth:`chain` method is used by
    :class:`FatFile` (and indirectly :class:`FatSubDirectory`) to discover the
    chain of clusters that make up a file (or sub-directory). The :meth:`free`
    method is used by writable :class:`FatFile` instances to find the next free
    cluster to write to. The :meth:`mark_free` and :meth:`mark_end` methods are
    used to mark a clusters as being free or as the terminal cluster of a
    file.
    """
    min_valid = None
    max_valid = None
    end_mark = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self._tables:
            for table in self._tables:
                table.release()
            self._tables = ()

    def __len__(self):
        return len(self._tables[0])

    def __delitem__(self, cluster):
        raise TypeError('FAT length is immutable')

    @property
    def readonly(self):
        return self._tables[0].readonly

    @abstractmethod
    def get_all(self, cluster):
        """
        Returns the value of *cluster* in all copies of the FAT, as a
        :class:`tuple` (naturally, under normal circumstances, these should all
        be equal).
        """
        raise NotImplementedError

    def insert(self, cluster, value):
        """
        Raises :exc:`TypeError`; the FAT length is immutable.
        """
        raise TypeError('FAT length is immutable')

    def mark_free(self, cluster):
        """
        Marks *cluster* as free (this simply sets *cluster* to 0 in the FAT).
        """
        self[cluster] = 0

    def mark_end(self, cluster):
        """
        Marks *cluster* as the end of a chain. The value used to indicate the
        end of a chain is specific to the FAT size.
        """
        self[cluster] = self.end_mark

    def chain(self, start):
        """
        Generator method which yields all the clusters in the chain starting at
        *start*.
        """
        cluster = start
        while self.min_valid <= cluster <= self.max_valid:
            yield cluster
            cluster = self[cluster]

    def free(self):
        """
        Generator that scans the FAT for free clusters, yielding each as it is
        found. Iterating to the end of this generator raises :exc:`OSError`
        with the code ENOSPC (out of space).
        """
        for cluster, value in enumerate(self):
            if value == 0 and self.min_valid < cluster:
                yield cluster
            if cluster >= self.max_valid:
                break
        # If we reach this point without the caller having broken out of their
        # loop, we've run out of space so raise the appropriate exception
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))


class Fat12Table(FatTable):
    """
    Concrete child of :class:`FatTable` for FAT-12 file-systems.

    .. autoattribute:: min_valid

    .. autoattribute:: max_valid

    .. autoattribute:: end_mark
    """
    min_valid = 0x002
    max_valid = 0xFEF
    end_mark = 0xFFF

    def __init__(self, mem, fat_size, info_mem=None):
        super().__init__()
        assert info_mem is None
        self._tables = tuple(
            mem[offset:offset + fat_size]
            for offset in range(0, len(mem), fat_size)
        )

    def __len__(self):
        return (super().__len__() * 2) // 3

    def get_all(self, cluster):
        try:
            if cluster % 2:
                offset = cluster + (cluster >> 1) + 1
                return tuple(
                    struct.unpack_from('<H', t, offset)[0] >> 4
                    for t in self._tables
                )
            else:
                offset = cluster + (cluster >> 1)
                return tuple(
                    struct.unpack_from('<H', t, offset)[0] & 0x0FFF
                    for t in self._tables
                )
        except struct.error:
            raise IndexError(f'{offset} out of bounds')

    def __getitem__(self, cluster):
        try:
            if cluster % 2:
                offset = cluster + (cluster >> 1) + 1
                return struct.unpack_from(
                    '<H', self._tables[0], offset)[0] >> 4
            else:
                offset = cluster + (cluster >> 1)
                return struct.unpack_from(
                    '<H', self._tables[0], offset)[0] & 0x0FFF
        except struct.error:
            raise IndexError(f'{offset} out of bounds')

    def __setitem__(self, cluster, value):
        if not 0x000 <= value <= 0xFFF:
            raise ValueError(f'{value} is outside range 0x000..0xFFF')
        try:
            if cluster % 2:
                offset = cluster + (cluster >> 1) + 1
                value <<= 4
                value |= struct.unpack_from(
                    '<H', self._tables[0], offset)[0] & 0x000F
            else:
                offset = cluster + (cluster >> 1)
                value |= struct.unpack_from(
                    '<H', self._tables[0], offset)[0] & 0xF000
            for table in self._tables:
                struct.pack_into('<H', table, offset, value)
        except struct.error:
            raise IndexError(f'{offset} out of bounds')


class Fat16Table(FatTable):
    """
    Concrete child of :class:`FatTable` for FAT-16 file-systems.

    .. autoattribute:: min_valid

    .. autoattribute:: max_valid

    .. autoattribute:: end_mark
    """
    min_valid = 0x0002
    max_valid = 0xFFEF
    end_mark = 0xFFFF

    def __init__(self, mem, fat_size, info_mem=None):
        super().__init__()
        assert info_mem is None
        self._tables = tuple(
            mem[offset:offset + fat_size].cast('H')
            for offset in range(0, len(mem), fat_size)
        )

    def get_all(self, cluster):
        return tuple(t[cluster] for t in self._tables)

    def __getitem__(self, cluster):
        return self._tables[0][cluster]

    def __setitem__(self, cluster, value):
        if not 0x0000 <= value <= 0xFFFF:
            raise ValueError(f'{value} is outside range 0x0000..0xFFFF')
        for table in self._tables:
            table[cluster] = value


class Fat32Table(FatTable):
    """
    Concrete child of :class:`FatTable` for FAT-32 file-systems.

    .. autoattribute:: min_valid

    .. autoattribute:: max_valid

    .. autoattribute:: end_mark
    """
    min_valid = 0x00000002
    max_valid = 0x0FFFFFEF
    end_mark = 0x0FFFFFFF

    def __init__(self, mem, fat_size, info_mem=None):
        super().__init__()
        self._tables = tuple(
            mem[offset:offset + fat_size].cast('I')
            for offset in range(0, len(mem), fat_size)
        )
        self._info = None
        self._info_mem = None
        if info_mem is not None:
            info = FAT32InfoSector.from_buffer(info_mem)
            if (
                    info.sig1 == b'RRaA' and
                    info.sig2 == b'rrAa' and
                    info.sig3 == b'\0\0\x55\xAA'):
                self._info = info
                self._info_mem = info_mem

    def close(self):
        super().close()
        if self._info_mem is not None:
            self._info_mem.release()
            self._info_mem = None
            self._info = None

    def _alloc(self, cluster):
        if self._info is not None:
            if 0 < self._info.free_clusters <= len(self):
                self._info = self._info._replace(
                    free_clusters=self._info.free_clusters - 1,
                    last_alloc=cluster)
            self._info.to_buffer(self._info_mem)

    def _dealloc(self, cluster):
        if self._info is not None:
            if 0 <= self._info.free_clusters < len(self):
                self._info = self._info._replace(
                    free_clusters=self._info.free_clusters + 1)
            self._info.to_buffer(self._info_mem)

    def free(self):
        if self._info is not None:
            last_alloc = self._info.last_alloc
            if self.min_valid <= last_alloc < len(self):
                # If we have a valid info-sector, start scanning from the last
                # allocated cluster plus one
                for cluster in range(last_alloc + 1, len(self)):
                    if self[cluster] == 0 and self.min_valid < cluster:
                        yield cluster
                    if cluster >= self.max_valid:
                        break
        yield from super().free()

    def get_all(self, cluster):
        return tuple(t[cluster] & 0x0FFFFFFF for t in self._tables)

    def __getitem__(self, cluster):
        return self._tables[0][cluster] & 0x0FFFFFFF

    def __setitem__(self, cluster, value):
        if not 0x00000000 <= value <= 0x0FFFFFFF:
            raise ValueError(f'{value} is outside range 0x00000000..0x0FFFFFFF')
        old_value = self._tables[0][cluster]
        if not old_value and value:
            self._alloc(cluster)
        elif old_value and not value:
            self._dealloc(cluster)
        for table in self._tables:
            table[cluster] = (old_value & 0xF0000000) | (value & 0x0FFFFFFF)


class FatClusters(abc.MutableSequence):
    """
    :class:`~collections.abc.MutableSequence` representing the clusters of
    the file-system itself.

    While the sequence is mutable, clusters cannot be deleted or inserted, only
    read and (if the underlying buffer is writable) re-written.
    """
    def __init__(self, mem, cluster_size):
        self._mem = mem
        self._cs = cluster_size

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self._mem is not None:
            self._mem.release()
            self._mem = None

    @property
    def size(self):
        """
        Returns the size (in bytes) of clusters in the file-system.
        """
        return self._cs

    @property
    def readonly(self):
        """
        Returns :data:`True` if the underlying buffer is read-only.
        """
        return self._mem.readonly

    def __len__(self):
        return len(self._mem) // self._cs

    def __getitem__(self, cluster):
        # The first data cluster is numbered 2, hence the offset below.
        # Clusters 0 and 1 are special and don't exist in the data portion of
        # the file-system
        if not 2 <= cluster < len(self) + 2:
            raise IndexError(cluster)
        offset = (cluster - 2) * self._cs
        return self._mem[offset:offset + self._cs]

    def __setitem__(self, cluster, value):
        # See above
        if not 2 <= cluster < len(self) + 2:
            raise IndexError(cluster)
        offset = (cluster - 2) * self._cs
        self._mem[offset:offset + self._cs] = value

    def __delitem__(self, cluster):
        raise TypeError('FS length is immutable')

    def insert(self, cluster, value):
        """
        Raises :exc:`TypeError`; the FS length is immutable.
        """
        raise TypeError('FS length is immutable')


class FatDirectory(abc.MutableMapping):
    """
    An abstract :class:`~collections.abc.MutableMapping` representing a `FAT
    directory`_. The mapping is ostensibly from filename to
    :class:`~nobodd.fat.DirectoryEntry` instances, but there are several
    oddities to be aware of.

    In VFAT, all files effectively have *two* filenames: the original DOS
    "short" filename (SFN hereafter) and the VFAT "long" filename (LFN
    hereafter). Even when :class:`~nobodd.fat.LongFilenameEntry` records do
    *not* precede a :class:`~nobodd.fat.DirectoryEntry`, the file may still
    have an LFN that differs from the SFN in case only. Naturally, some files
    still only have one filename because the LFN doesn't vary in case from the
    SFN, e.g. the special directory entries "." and "..". This implementation
    never returns (or accepts) :class:`~nobodd.fat.LongFilenameEntry` records.
    These are managed internally according to the LFNs requested.

    For the purposes of listing files, most FAT implementations (including this
    one) ignore the SFNs. Hence, iterating over this mapping will *not* yield
    the SFNs (unless the SFN is equal to the LFN), and they are *not* counted
    in the length of the mapping. However, for the purposes of testing
    existence, opening, etc., FAT implementations allow the use of SFNs. Hence,
    testing for membership, or manipulating entries via the SFN will work with
    this mapping, and will implicitly manipulate the associated LFNs (e.g.
    deleting an entry via SFN will also delete the associated LFN).

    In other words, if a file has a distinct LFN and SFN, it has *two* entries
    in the mapping (the "visible" LFN entry, and the "invisible" SFN entry).
    Finally, note that FAT is case retentive (for LFNs; SFNs are folded
    uppercase), but not case sensitive. Hence, membership tests and retrieval
    from this mapping are case insensitive with regard to keys.

    .. _FAT directory:
        https://en.wikipedia.org/wiki/Design_of_the_FAT_file_system#Directory_table

    .. autoattribute:: MAX_SFN_SUFFIX
    """
    MAX_SFN_SUFFIX = 0xFFFF
    SFN_VALID = re.compile(b"[^A-Z0-9 !#$%&'()@^_`{}~\x80-\xFF-]")

    __slots__ = ('_encoding',)

    @abstractmethod
    def _get_cluster(self):
        raise NotImplementedError

    @abstractmethod
    def _iter_entries(self):
        """
        Abstract generator that is expected to yield successive offsets and the
        entries at those offsets as :class:`~nobodd.fat.DirectoryEntry`
        instances or :class:`~nobodd.fat.LongFilenameEntry` instances, as
        appropriate.

        All instances must be yielded, in the order they appear on disk,
        regardless of whether they represent deleted, orphaned, corrupted, or
        other entries. Only the terminal entry (with NUL as the first byte),
        and subsequent entries must not be yielded.
        """
        raise NotImplementedError

    @abstractmethod
    def _update_entry(self, offset, entry):
        """
        Abstract method which is expected to (re-)write *entry* (a
        :class:`~nobodd.fat.DirectoryEntry` or
        :class:`~nobodd.fat.LongFilenameEntry` instance) at the specified
        *offset* in the directory.
        """
        raise NotImplementedError

    def _split_entries(self, entries):
        """
        Given *entries*, a sequence of :class:`~nobodd.fat.LongFilenameEntry`
        instances, ending with a single :class:`~nobodd.fat.DirectoryEntry` (as
        would typically be found in a FAT directory index), return the decoded
        long filename, short filename, and the directory entry record as a
        3-tuple.

        If no long filename entries are present, the long filename will be
        equal to the short filename (but may have lower-case parts).

        .. note::

            This function also carries out several checks, including the
            filename checksum, that all checksums match, that the number of
            entries is valid, etc. Any violations found will raise
            :exc:`ValueError`.
        """
        # The extration of the long filename could be simpler, but let's do all
        # the checks we can (the structure includes a *lot* of redundancy for
        # checking things!)
        if not entries:
            raise ValueError('blank dir_entries')
        *lfn_entries, entry = entries
        if not isinstance(entry, DirectoryEntry):
            raise ValueError(
                f'last entry of entries must be a DirectoryEntry, not {entry!r}')

        # TODO The following should only be warning of all the ValueError stuff
        # as LFN entries can be "orphaned". In the event of orphaned/invalid
        # LFN entries, skip to the next terminal LFN entry (if any) and retry
        if lfn_entries:
            head, *tail = lfn_entries
            checksum = head.checksum
            sequence = head.sequence
            if not sequence & 0x40:
                raise ValueError(
                    'first LongFilenameEntry is not marked as terminal')
            sequence = sequence & 0b11111
            lfn = head.name_1 + head.name_2 + head.name_3
            for part in tail:
                if part.first_cluster != 0:
                    raise ValueError(
                        f'first_cluster is non-zero: {part.first_cluster}')
                if part.checksum != checksum:
                    raise ValueError(
                        f'mismatched checksum: {checksum} != {part.checksum}')
                sequence -= 1
                if sequence < 1:
                    raise ValueError('too many LongFilenameEntry items')
                if part.sequence != sequence:
                    raise ValueError(
                        f'incorrect LongFilenameEntry.sequence: {sequence} != '
                        f'{part.sequence}')
                lfn = part.name_1 + part.name_2 + part.name_3 + lfn
            if sequence > 1:
                raise ValueError(f'missing {sequence} LongFilenameEntry items')
            if lfn_checksum(entry.filename, entry.ext) != checksum:
                raise ValueError(
                    f'checksum mismatch in long filename: {sum_} != {checksum}')
            lfn = lfn.decode('utf-16le').rstrip('\uffff')
            # There may be one trailing NUL char, but there may not if the
            # filename fits perfectly in a LFN structure
            if lfn[-1:] == '\x00':
                lfn = lfn[:-1]
            # But there shouldn't be more than one!
            if lfn[-1:] == '\x00':
                raise ValueError(f'excess NUL chars in long filename: {lfn!r}')
            if not lfn:
                raise ValueError('empty long filename')
        else:
            lfn = None

        sfn = entry.filename.rstrip(b' ')
        # If initial char of the filename is 0xE5 (which is reserved to
        # indicate a deleted entry) then it's encoded as 0x05 (since DOS 3.0)
        if sfn[0] == 0x05:
            sfn = b'\xE5' + sfn[1:]
        sfn = sfn.decode(self._encoding)
        ext = entry.ext.rstrip(b' ').decode(self._encoding)
        # Bits 3 & 4 of attr2 are used by Windows NT (basically any modern
        # Windows) to indicate if the short filename (in the absence of long
        # filename entries) has upper / lower-case portions
        if lfn is None:
            lfn = sfn.lower() if entry.attr2 & 0b1000 else sfn
            if ext:
                lfn = lfn + '.' + (ext.lower() if entry.attr2 & 0b10000 else ext)
        if ext:
            sfn = sfn + '.' + ext

        return lfn, sfn, entry

    def _prefix_entries(self, filename, entry):
        """
        Given *entry*, a :class:`~nobodd.fat.DirectoryEntry`, generate the
        necessary `~nobodd.fat.LongFilenameEntry` instances (if any), that are
        necessary to associate *entry* with the specified *filename*.

        This function merely constructs the instances, ensuring the (many,
        convoluted!) rules are followed, including that the short filename, if
        one is generated, is unique in this directory, and the long filename is
        encoded and check-summed appropriately.

        .. note::

            The *filename* and *ext* fields of *entry* are over-written by
            this method. The only filename that is considered is the one
            explicitly passed in which becomes the basis for the long filename
            entries *and* the short filename stored within the *entry* itself.

        The return value is the sequence of long filename entries and the
        directory entry suffix in the order they should appear on disk.
        """
        lfn, sfn, ext, attr2 = self._get_names(filename)
        if lfn:
            checksum = lfn_checksum(sfn, ext)
            entries = [
                LongFilenameEntry(
                    sequence=part,
                    name_1=lfn[offset:offset + 10],
                    attr=0xF,
                    checksum=checksum,
                    name_2=lfn[offset + 10:offset + 22],
                    first_cluster=0,
                    name_3=lfn[offset + 22:offset + 26]
                )
                for part, offset
                in enumerate(range(len(lfn), 26), start=1)
            ]
            entries.reverse()
            # Add terminal marker to "last" entry
            entries[0] = entries[0]._replace(
                sequence=0x40 | entries[0].sequence)
        else:
            entries = []

        entries.append(entry._replace(filename=sfn, ext=ext, attr2=attr2))
        return entries

    def _get_names(self, filename):
        """
        Given a *filename*, generate an appropriately encoded long filename
        (encoded in little-endian UCS-2), a short filename, an extension, and
        the case attributes. The result is a 4-tuple: ``lfn, sfn, ext, attr``.

        ``lfn``, ``sfn``, and ``ext`` will be :class:`bytes` strings, and
        ``attr`` will be an :class:`int`. If *filename* is capable of being
        represented as a short filename only (potentially with non-zero case
        attributes), ``lfn`` in the result will be blank.
        """
        # sfn == short filename, lfn == long filename, ext == extension
        if filename in ('.', '..'):
            sfn, ext = filename.encode(self._encoding), b''
        else:
            sfn = filename.lstrip('.').upper().encode(self._encoding, 'replace')
            sfn = sfn.replace(b' ', b'')
            sfn = self.SFN_VALID.sub(b'_', sfn)
            if b'.' in sfn:
                sfn, ext = sfn.rsplit(b'.', 1)
            else:
                sfn, ext = sfn, b''

        if len(sfn) <= 8 and len(ext) <= 3:
            # NOTE: Huh, a place where match..case might actually be
            # useful! Why isn't this a dict? It was originally, but in
            # purely symbolic cases (e.g. "." and "..") the transformed SFN
            # can be equivalent in all cases and we want to explicitly prefer
            # the case where attr is 0.
            sfn_only = True
            lfn = filename.encode(self._encoding, 'replace')
            make_sfn = lambda s, e: (s + b'.' + e) if e else s
            if lfn == make_sfn(sfn, ext):
                attr = 0
            elif lfn == make_sfn(sfn, ext.lower()):
                attr = 0b10000
            elif lfn == make_sfn(sfn.lower(), ext):
                attr = 0b01000
            elif lfn == make_sfn(sfn.lower(), ext.lower()):
                attr = 0b11000
            else:
                sfn_only = False
                attr = 0
        else:
            sfn_only = False
            attr = 0

        if sfn_only:
            lfn = b''
        else:
            lfn = filename.encode('utf-16le')
            if len(lfn) > 255 * 2:
                raise ValueError(
                    f'{filename} is too long (more than 255 UCS-2 characters)')
            # Always NUL terminate (although it seems some drivers don't if the
            # result fits perfectly in a LongFilenameEntry)
            lfn += b'\0\0'
            if len(lfn) % 26:
                pad = ((len(lfn) + 25) // 26) * 26
                lfn = lfn.ljust(pad, b'\xff')
            assert len(lfn) % 26 == 0
            ext = ext[:3]
            sfn = self._get_unique_sfn(sfn, ext).encode(
                self._encoding, 'replace')
        sfn = sfn.ljust(8, b' ')
        ext = ext.ljust(3, b' ')
        return lfn, sfn, ext, attr

    def _get_unique_sfn(self, prefix, ext):
        """
        Given *prefix* and *ext*, which are :class:`bytes` strings, of the
        short filename prefix and extension, find a suffix that is unique in
        the directory (amongst both long *and* short filenames, because
        anything with a long filename in VFAT effectively has *two* filenames).

        For example, given a file with long filename ``default.conf``, in
        a directory containing ``default.config`` (which has shortname
        ``DEFAUL~1.CON``), this function will return ``DEFAUL~2.CON``.

        Because the search requires enumeration of the whole directory, which
        is expensive, an artificial limit of :data:`MAX_SFN_SUFFIX` is
        enforced. If this is reached, the search will terminate with an error,
        causing the creation of the file/directory to fail.
        """
        ranges = [range(self.MAX_SFN_SUFFIX)]
        regexes = [
            re.compile(
                f'{re.escape(prefix[:i])}~([0-9]{{{i}}}).{re.escape(ext)}',
                re.IGNORECASE)
            for i in range(1, len(str(self.MAX_SFN_SUFFIX)) + 1)
        ]
        for entries in self:
            lfn, sfn, entry = split_filename_entry(entries)
            m = any_match(sfn, regexes)
            if m:
                exclude(ranges, int(m.group(1)))
            m = any_match(lfn, regexes)
            if m:
                exclude(ranges, int(m.group(1)))
        for r in ranges:
            l = len(str(r.start))
            return f'{prefix[:l]}~{r.start}'
        # We cannot create any shortnames that aren't already taken. Given the
        # limit on entries in a dir (MAX_SFN_SUFFIX, roughly) report ENOSPC
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    def _group_entries(self):
        """
        Generator which yields an offset, and a sequence of tuples of either
        :class:`~nobodd.fat.LongFilenameEntry` or
        :class:`~nobodd.fat.DirectoryEntry` instances.

        Each sequence yielded represents a single (extant, non-deleted) file or
        directory entry with its long-filename entries at the start, and the
        directory entry as the final element. The offset associated with the
        sequence is the offset of the *directory entry* (not its preceding long
        filename entries). In other words, for a file with three long-filename
        entries, the following might be yielded::

            (160, [
                <LongFilenameEntry>),
                <LongFilenameEntry>),
                <LongFilenameEntry>),
                <DirectoryEntry>)
            ])

        This indicates that the directory entry is at offset 160, preceded by
        long filename entries at offsets 128, 96, and 64.
        """
        entries = []
        for offset, entry in self._iter_entries():
            if isinstance(entry, LongFilenameEntry):
                if entry.sequence == 0xE5: # deleted entry
                    continue
            entries.append(entry)
            if isinstance(entry, DirectoryEntry):
                if entry.filename[0] == 0: # end of valid entries
                    break
                elif entry.attr & 0x8: # volume label
                    pass
                elif entry.filename[0] != 0xE5: # deleted entry
                    yield offset, entries
                entries = []

    def _clean_entries(self):
        """
        Find and remove all deleted entries from the directory.

        The method scans the directory for all directory entries and long
        filename entries which start with 0xE5, indicating a deleted entry,
        and overwrites them with later (not deleted) entries. Trailing entries
        are then zeroed out. The return value is the new offset of the terminal
        entry.
        """
        write_offset = 0
        for read_offset, entry in self._iter_entries():
            if isinstance(entry, DirectoryEntry):
                if entry.filename[0] == 0: # end of valid entries
                    break
                elif entry.filename[0] == 0xE5: # deleted entry
                    continue
            if isinstance(entry, LongFilenameEntry):
                if entry.sequence == 0xE5: # deleted entry
                    continue
            if read_offset > write_offset:
                self._update_entry(write_offset, entry)
            write_offset += DirectoryEntry._FORMAT.size
        eof = write_offset
        empty = DirectoryEntry.from_bytes(b'\0' * DirectoryEntry._FORMAT.size)
        while write_offset < read_offset:
            self._update_entry(write_offset, empty)
            write_offset += DirectoryEntry._FORMAT.size
        return eof

    def __len__(self):
        return sum(1 for lfn in self)

    def __iter__(self):
        for offset, entries in self._group_entries():
            lfn, sfn, entry = self._split_entries(entries)
            yield lfn

    def __contains__(self, name):
        uname = name.upper()
        for offset, entries in self._group_entries():
            lfn, sfn, entry = self._split_entries(entries)
            if lfn.upper() == uname or sfn == name:
                return True
        return False

    def __getitem__(self, name):
        uname = name.upper()
        for offset, entries in self._group_entries():
            lfn, sfn, entry = self._split_entries(entries)
            if lfn.upper() == uname or sfn == uname:
                return entry
        raise KeyError(name)

    def __setitem__(self, name, entry):
        # NOTE: For the purposes of setting entries, the filename and ext
        # within *entry* are ignored. For new entries, these will be generated
        # from *name*. For existing entries, the existing values will be
        # re-used
        uname = name.upper()
        offset = 0
        for offset, entries in self._group_entries():
            lfn, sfn, old_entry = self._split_entries(entries)
            if lfn.upper() == uname or sfn == uname:
                self._update_entry(offset, entry._replace(
                    filename=old_entry.filename, ext=old_entry.ext))
                return
        # This isn't *necessarily* the actual EOF. It could be orphaned or
        # deleted entries that _group_entries isn't yielding, but that doesn't
        # matter for our purposes. All that matters is that we can safely
        # overwrite these entries
        eof_offset += DirectoryEntry._FORMAT.size
        entries = self._prefix_entries(name, entry)
        entries.append(DirectoryEntry.eof())
        for cleaned in (False, True):
            # We write the entries in reverse order to make it more likely that
            # anything scanning the directory simultaneously sees the append as
            # "atomic" (because the last item written overwrites the old
            # terminal marker entry)
            offsets = range(
                eof_offset,
                eof_offset + len(entries) * DirectoryEntry._FORMAT.size,
                DirectoryEntry._FORMAT.size)
            try:
                for offset, entry in reversed(list(zip(offsets, entries))):
                    self._update_entry(offset, entry)
            except OSError as e:
                # If the directory structure runs out of space (which is more
                # likely under FAT-12 and FAT-16 where the root directory is
                # fixed in size), then all deleted entries will be expunged,
                # and the method will attempt to append the new entries once
                # more
                if e.errno == errno.ENOSPC and not cleaned:
                    eof_offset = self._clean_entries()
                else:
                    raise
            else:
                break

    def __delitem__(self, name):
        uname = name.upper()
        for offset, entries in self._group_entries():
            lfn, sfn, entry = self._split_entries(entries)
            if lfn.upper() == uname or sfn == uname:
                # NOTE: We update the DirectoryEntry first then work backwards,
                # marking the long filename entries. This ensures anything
                # simultaneously scanning the directory shouldn't find a "live"
                # directory entry preceded by "dead" long filenames
                for entry in reversed(entries):
                    if isinstance(entry, DirectoryEntry):
                        self._update_entry(offset, entry._replace(
                            filename=b'\xE5' + entry.filename[1:]))
                    else: # LongFilenameEntry
                        self._update_entry(offset, entry._replace(
                            sequence=0xE5))
                    offset -= DirectoryEntry._FORMAT.size
                return
        raise KeyError(name)

    cluster = property(lambda self: self._get_cluster())


class FatRoot(FatDirectory):
    """
    An abstract derivative of :class:`FatDirectory` representing the
    (fixed-size) root directory of a FAT-12 or FAT-16 file-system. Must be
    constructed with *mem*, which is a buffer object covering the root
    directory clusters, and *encoding*, which is taken from
    :attr:`FatFileSystem.sfn_encoding`. The :class:`Fat12Root` and
    :class:`Fat16Root` classes are (trivial) concrete derivatives of this.
    """
    __slots__ = ('_mem',)

    def __init__(self, mem, encoding):
        self._encoding = encoding
        self._mem = mem

    def _get_cluster(self):
        return 0

    def _update_entry(self, offset, entry):
        if offset >= len(self._mem):
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
        entry.to_buffer(self._mem, offset)

    def _iter_entries(self):
        for offset in range(0, len(self._mem), DirectoryEntry._FORMAT.size):
            entry = DirectoryEntry.from_buffer(self._mem, offset)
            if entry.attr == 0x0F:
                entry = LongFilenameEntry.from_buffer(self._mem, offset)
            yield offset, entry


class FatSubDirectory(FatDirectory):
    """
    A concrete derivative of :class:`FatDirectory` representing a sub-directory
    in a FAT file-system (of any type). Must be constructed with *fs* (a
    :class:`FatFileSystem` instance), *start* (the first cluster of the
    sub-directory), and *encoding*, which is taken from
    :attr:`FatFileSystem.sfn_encoding`.
    """
    __slots__ = ('_cs', '_file', 'fat_type')

    def __init__(self, fs, start, encoding):
        self._encoding = encoding
        self._cs = fs.clusters.size
        # NOTE: We always open sub-directories with a writable mode when
        # possible; this simply parallels the state in FAT-12/16 root
        # directories which are always writable (if the underlying mapping is)
        self._file = fs.open_file(start, mode='rb' if fs.readonly else 'r+b')
        self.fat_type = fs.fat_type

    def _get_cluster(self):
        return self._file._map[0]

    def _update_entry(self, offset, entry):
        pos = self._file.tell()
        try:
            self._file.seek(offset)
            self._file.write(bytes(entry))
        finally:
            self._file.seek(pos)

    def _iter_entries(self):
        buf = bytearray(self._cs)
        self._file.seek(0)
        while self._file.readinto(buf):
            for offset in range(0, len(buf), DirectoryEntry._FORMAT.size):
                entry = DirectoryEntry.from_buffer(buf, offset)
                if entry.attr == 0x0F:
                    entry = LongFilenameEntry.from_buffer(buf, offset)
                yield offset, entry


class Fat12Root(FatRoot):
    """
    This is a trivial derivative of :class:`FatRoot` which simply declares the
    root as belonging to a FAT-12 file-system.

    .. autoattribute:: fat_type
    """
    fat_type = 'fat12'


class Fat16Root(FatRoot):
    """
    This is a trivial derivative of :class:`FatRoot` which simply declares the
    root as belonging to a FAT-16 file-system.

    .. autoattribute:: fat_type
    """
    fat_type = 'fat16'


class Fat32Root(FatSubDirectory):
    """
    This is a trivial derivative of :class:`FatSubDirectory` because, in
    FAT-32, the root directory is represented by the same structure as a
    regular sub-directory.
    """


class FatFile(io.RawIOBase):
    """
    Represents an open file from a :class:`FatFileSystem`.

    You should never need to construct this instance directly. Instead it (or
    wrapped variants of it) is returned by the
    :meth:`~nobodd.path.FatPath.open` method of :class:`~nobodd.path.FatPath`
    instances. For example::

        from nobodd.disk import DiskImage
        from nobodd.fs import FatFileSystem

        with DiskImage('test.img') as img:
            with FatFileSystem(img.partitions[1].data) as fs:
                path = fs.root / 'bar.txt'
                with path.open('r', encoding='utf-8') as f:
                    print(f.read())

    Instances can (and should) be used as context managers to implicitly close
    references upon exiting the context. Instances are readable and seekable,
    and writable, depending on their opening mode and the nature of the
    underlying :class:`FatFileSystem`.

    As a derivative of :class:`io.RawIOBase`, all the usual I/O methods should
    be available.
    """
    __slots__ = ('_fs', '_map', '_index', '_entry', '_pos', '_mode')

    def __init__(self, fs, start, mode='rb', index=None, entry=None):
        super().__init__()
        if 'b' not in mode:
            raise ValueError(f'non-binary mode {mode!r} not supported')
        self._fs = weakref.ref(fs)
        if start:
            self._map = list(fs.fat.chain(start))
        else:
            self._map = []
        self._index = index
        self._entry = entry
        self._pos = 0
        if 'w' in mode:
            self._mode = '+' if '+' in mode else 'w'
            self.truncate()
        elif 'a' in mode:
            self._mode = '+' if '+' in mode else 'w'
            self.seek(0, os.SEEK_END)
        else:
            self._mode = '+' if '+' in mode else 'r'

    @classmethod
    def from_cluster(cls, fs, start, mode='rb'):
        """
        Construct a :class:`FatFile` from a :class:`FatFileSystem`, *fs*, and
        a *start* cluster. The optional *mode* is equivalent to the built-in
        :func:`open` function.

        Files constructed via this method do not have an associated directory
        entry. As a result, their size is assumed to be the full size of their
        cluster chain. This is typically used for the "file" backing a
        :class:`FatSubDirectory`.

        .. warning::

            This method is intended for internal use by the
            :class:`~nobodd.path.FatPath` class.
        """
        return cls(fs, start, mode)

    @classmethod
    def from_entry(cls, fs, index, entry, mode='rb'):
        """
        Construct a :class:`FatFile` from a :class:`FatFileSystem`, *fs*, a
        :class:`FatDirectory`, *index*, and a
        :class:`~nobodd.fat.DirectoryEntry`, *entry*. The optional *mode* is
        equivalent to the built-in :func:`open` function.

        Files constructed via this method have an associated directory entry
        which will be updated if/when reads or writes occur (updating atime,
        mtime, and size fields).

        .. warning::

            This method is intended for internal use by the
            :class:`~nobodd.path.FatPath` class.
        """
        return cls(fs, get_cluster(entry, fs.fat_type), mode, index, entry)

    def _get_fs(self):
        """
        Check the weak reference to the FatFileSystem. If it's still live,
        return the strong reference result. If it's disappeared, raise an
        :exc:`OSError` exception indicating the file-system has been closed.
        """
        fs = self._fs()
        if fs is None:
            raise OSError(f'FatFileSystem containing {self!r} is closed')
        return fs

    def _get_size(self):
        """
        Returns the current size of the file. If the file has an associated
        directory entry, we simply return the size recorded there. Otherwise,
        the size is full size of all clusters in the file's chain.
        """
        fs = self._get_fs()
        if self._entry is None:
            return fs.clusters.size * len(self._map)
        else:
            return self._entry.size

    def _set_size(self, new_size):
        """
        Update the size of the file in the associated directory entry, if any.
        If the file has no associated directory entry, this is a no-op.
        """
        if self._entry is not None:
            try:
                first_cluster = self._map[0]
            except IndexError:
                # Only set first_cluster to 0 if the map is actually empty;
                # we ignore size here because we allow size to be 0 with a
                # cluster allocated while the file is open so that the file
                # doesn't "move cluster" while it's opened, even if it's
                # truncated. Only on close() do we remove the last cluster
                first_cluster = 0
            self._entry = self._entry._replace(
                size=new_size,
                first_cluster_hi=first_cluster >> 16,
                first_cluster_lo=first_cluster & 0xFFFF)
            self._index.update(self._entry)

    def _set_atime(self, ts=None):
        """
        Update the access timestamp of the file in the associated directory
        entry, if any, to the :class:`~datetime.datetime` *ts*. If the file has
        no associated directory entry, this is a no-op.
        """
        if self._entry is not None:
            if ts is None:
                ts = dt.datetime.now()
            adate, _, _ = encode_timestamp(ts)
            self._entry = self._entry._replace(adate=adate)
            self._index.update(self._entry)

    def _set_mtime(self, ts=None):
        """
        Update the last-modified timestamp of the file in the associated
        directory entry, if any, to the :class:`~datetime.datetime` *ts*. If
        the file has no associated directory entry, this is a no-op.
        """
        if self._entry is not None:
            if ts is None:
                ts = dt.datetime.now()
            mdate, mtime, _ = encode_timestamp(ts)
            self._entry = self._entry._replace(mdate=mdate, mtime=mtime)
            self._index.update(self._entry)

    def close(self):
        if not self.closed:
            if self._entry is not None and self._entry.size == 0 and self._map:
                # See note in _set_size
                assert len(self._map) == 1
                fs = self._get_fs()
                fs.fat.mark_free(self._map[0])
                self._map = []
                self._set_size(0)
            super().close()

    def readable(self):
        return self._mode in 'r+'

    def seekable(self):
        return True

    def writable(self):
        return self._mode in 'w+'

    def readall(self):
        if not self.readable:
            raise io.UnsupportedOperation()
        size = self._get_size()
        buf = bytearray(max(0, size - self._pos))
        mem = memoryview(buf)
        pos = 0
        while self._pos < size:
            pos += self.readinto(mem[pos:])
        return bytes(buf)

    def readinto(self, buf):
        if not self.readable:
            raise io.UnsupportedOperation()
        fs = self._get_fs()
        cs = fs.clusters.size
        size = self._get_size()
        # index is which cluster of the file we wish to read; i.e. index 0
        # represents the first cluster of the file; left and right are the byte
        # offsets within the cluster to return; read is the number of bytes to
        # return
        index = self._pos // cs
        left = self._pos - (index * cs)
        right = min(cs, left + len(buf), size - (index * cs))
        read = max(right - left, 0)
        if read > 0:
            buf[:read] = fs.clusters[self._map[index]][left:right]
            self._pos += read
        if fs.atime and not fs.readonly:
            self._set_atime()
        return read

    def write(self, buf):
        if not self.writable:
            raise io.UnsupportedOperation()
        mem = memoryview(buf)
        fs = self._get_fs()
        size = self._get_size()
        if self._pos > size:
            # Pad the file to the current position. Note that this does *not*
            # count towards written
            self.truncate()
        written = 0
        try:
            while mem:
                # Alternate between filling a cluster with _write1, and
                # allocating a new cluster. This is far from the most efficient
                # method (we're not taking account of whether any clusters are
                # actually contiguous), but it is simple!
                w = self._write1(mem, fs)
                if w:
                    written += w
                    mem = mem[w:]
                else:
                    # TODO In event of ENOSPC, raise or return written so far?
                    for cluster in fs.fat.free():
                        fs.fat.mark_end(cluster)
                        if self._map:
                            fs.fat[self._map[-1]] = cluster
                        self._map.append(cluster)
                        break
        finally:
            if self._pos > size:
                self._set_size(self._pos)
            if not fs.readonly:
                self._set_mtime()
        return written

    def _write1(self, buf, fs=None):
        """
        Write as much of *buf* to the file at the current position as will fit
        in the current cluster, returning the number of bytes written, and
        advancing the position of the file-pointer. If the current position is
        beyond the end of the file, this method writes nothing and return 0.
        """
        if fs is None:
            fs = self._get_fs()
        mem = memoryview(buf)
        cs = fs.clusters.size
        index = self._pos // cs
        left = self._pos - (index * cs)
        right = min(cs, left + len(mem))
        written = max(right - left, 0)
        if written > 0:
            try:
                fs.clusters[self._map[index]][left:right] = mem[:written]
            except IndexError:
                return 0
            self._pos += written
        return written

    def seek(self, pos, whence=io.SEEK_SET):
        if whence == io.SEEK_SET:
            pos = pos
        elif whence == io.SEEK_CUR:
            pos = self._pos + pos
        elif whence == io.SEEK_END:
            pos = self._get_size() + pos
        else:
            raise ValueError(f'invalid whence: {whence}')
        if pos < 0:
            raise IOError('invalid argument')
        self._pos = pos
        return self._pos

    def truncate(self, size=None):
        if not self.writable:
            raise io.UnsupportedOperation()
        fs = self._get_fs()
        cs = fs.clusters.size
        old_size = self._get_size()
        if size is None:
            size = self._pos
        if size == old_size:
            return size
        clusters = max(1, (size + cs - 1) // cs)
        if size > old_size:
            # If we're expanding the size of the file, zero the tail of the
            # current final cluster; this is necessary whether or not we're
            # expanding the actual number of clusters in the file. Note we
            # don't bother calculating exactly how many bytes to zero; we just
            # zero everything from the current size up to the end of the
            # cluster because that's fine in either case
            tail = len(self._map) * cs - old_size
            if tail:
                fs.clusters[self._map[-1]][-tail:] = b'\0' * tail
        if clusters > len(self._map):
            # Pre-calculate the clusters we're going to append. We don't want
            # to add any if we can't add them all. We then mark the clusters
            # in the FAT in reverse order, zeroing new blocks as we go so that
            # the final extension of the file is effectively atomic (from a
            # concurrent reader's perspective)
            to_append = list(islice(fs.fat.free(), clusters - len(self._map)))
            fs.fat.mark_end(to_append[-1])
            zeros = b'\0' * cs
            for next_c, this_c in pairwise(reversed([self._map[-1]] + to_append)):
                fs.clusters[next_c] = zeros
                fs.fat[this_c] = next_c
            self._map.extend(to_append)
        elif clusters < len(self._map):
            # We start by marking the new end cluster, which atomically
            # shortens the FAT chain for the file, then proceed to mark all the
            # removed clusters as free
            to_remove = self._map[len(self._map) - clusters:]
            fs.fat.mark_end(self._map[clusters - 1])
            del self._map[clusters:]
            for cluster in to_remove:
                fs.fat.mark_free(cluster)
        # Finally, correct the directory entry to reflect the new size
        self._set_size(size)
        if not fs.readonly:
            self._set_mtime()
        return size
