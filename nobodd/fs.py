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
    sfn_safe,
    lfn_valid,
    lfn_checksum,
)
from .path import FatPath, get_cluster, split_filename_entry
from .tools import (
    pairwise,
    on_first,
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
# the wikipedia page on the Design of the FAT File system [1], and Jonathan
# de Boyne Pollard's notes on determination of FAT widths [2].
#
# [1]: https://en.wikipedia.org/wiki/Design_of_the_FAT_file_system
# [2]: http://homepage.ntlworld.com/jonathan.deboynepollard/FGA/determining-fat-widths.html
#
# (please note [2] is a dead link at the time of writing; use archive.org to
# retrieve)

class FatFileSystem:
    """
    Represents a `FAT`_ file-system, contained at the start of the buffer
    object *mem* with a *sector_size* defaulting to 512 bytes. If *atime* is
    :data:`False`, the default, then accesses to files will *not* update the
    atime field in file meta-data (when the underlying *mem* mapping is
    writable). Finally, *encoding* specifies the character set used for
    decoding and encoding DOS short filenames.

    This class supports the FAT-12, FAT-16, and FAT-32 formats, and will
    automatically determine which to use from the headers found at the start of
    *mem*. The type in use may be queried from :attr:`fat_type`. Of primary use
    is the :attr:`root` attribute which provides a
    :class:`~nobodd.path.FatPath` instance representing the root directory of
    the file-system.

    Instances can (and should) be used as a context manager; exiting the
    context will call the :meth:`close` method implicitly.

    .. _FAT: https://en.wikipedia.org/wiki/Design_of_the_FAT_file_system
    """
    def __init__(self, mem, sector_size=512, atime=False,
                 encoding='iso-8859-1'):
        self._fat_type, bpb, ebpb, ebpb_fat32 = fat_type(mem)
        if bpb.bytes_per_sector != sector_size:
            warnings.warn(
                UserWarning(
                    f'Unexpected sector-size in FAT, {bpb.bytes_per_sector}, '
                    f'differs from {sector_size}'))
        self._atime = atime
        self._encoding = encoding
        self._label = ebpb.volume_label.decode(encoding, 'replace').rstrip(' ')

        fat_size = (
            ebpb_fat32.sectors_per_fat if ebpb_fat32 is not None else
            bpb.sectors_per_fat) * bpb.bytes_per_sector
        root_size = bpb.max_root_entries * DirectoryEntry._FORMAT.size
        # Root size must be rounded up to a whole number of sectors
        root_size = (
            (root_size + (bpb.bytes_per_sector - 1)) //
            bpb.bytes_per_sector) * bpb.bytes_per_sector
        info_offset = (
            ebpb_fat32.info_sector * bpb.bytes_per_sector
            if ebpb_fat32 is not None
            and ebpb_fat32.info_sector not in (0, 0xFFFF)
            else None)
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
            mem[data_offset:], bpb.bytes_per_sector * bpb.sectors_per_cluster)
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
        if fat_size == 0:
            raise ValueError(f'{self._fat_type.upper()} sectors per FAT is 0')
        if root_size % bpb.bytes_per_sector:
            raise ValueError(
                f'Max. root entries, {bpb.max_root_entries} creates a root '
                f'directory region that is not a multiple of sector size, '
                f'{bpb.bytes_per_sector}')
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
        Returns :data:`True` if the underlying :class:`~mmap.mmap` is
        read-only.
        """
        return self._data.readonly

    def open_dir(self, cluster):
        """
        Opens the sub-directory in the specified *cluster*, returning a
        :class:`FatSubDirectory` instance representing it.

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
        instance representing it. Note that the :class:`FatFile` instance
        returned by this method has no directory entry associated with it. This
        is typically used for "files" underlying the sub-directory structure
        which do not have an associated size (other than that dictated by their
        FAT chain of clusters).

        .. warning::

            This method is intended for internal use by the
            :class:`~nobodd.path.FatPath` class.
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
        return fat_type_from_count(bpb, ebpb), bpb, ebpb, None
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
        return fat_type_from_count(bpb, ebpb), bpb, ebpb, ebpb_fat32
    raise ValueError(
        'Could not find file-system type or extended boot signature')


def fat_type_from_count(bpb, ebpb):
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
    fat_sectors = (
        bpb.fat_count *
        (ebpb_fat32.sectors_per_fat or bpb.fat16_sectors_per_fat))
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
        :class:`tuple`.
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
        if info_mem is not None:
            warnings.warn(Warning(
                'info-sector should not be present in fat-12'))
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
                value |= struct.unpack_from('<H', self._mem, offset)[0] & 0x000F
            else:
                offset = cluster + (cluster >> 1)
                value |= struct.unpack_from('<H', self._mem, offset)[0] & 0xF000
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
        if info_mem is not None:
            warnings.warn(Warning(
                'info-sector should not be present in fat-16'))
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
                    info.sig3 == (0x00, 0x00, 0x55, 0xAA)):
                self._info = info
                self._info_mem = info_mem

    def close(self):
        super().close()
        if self._info is not None:
            self._info.release()
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

    def mark_end(self, cluster):
        if not self[cluster]:
            self._alloc(cluster)
        super().mark_end(cluster)

    def mark_free(self, cluster):
        if self[cluster]:
            self._dealloc(cluster)
        super().mark_free(cluster)

    def free(self):
        if self._info is not None:
            last_alloc = self._info.last_alloc
            if min_valid <= last_alloc < len(self):
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
    read and (if the underlying :class:`~mmap.mmap` is writable) re-written.
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
        Returns :data:`True` if the underlying :class:`~mmap.mmap` is
        read-only.
        """
        return self._mem.readonly

    def __len__(self):
        return len(self._mem) // self._cs

    def __getitem__(self, cluster):
        # The first data cluster is numbered 2, hence the offset below.
        # Clusters 0 and 1 are special and don't exist in the data portion of
        # the file-system
        offset = (cluster - 2) * self._cs
        if offset < 0:
            raise IndexError(cluster)
        return self._mem[offset:offset + self._cs]

    def __setitem__(self, cluster, value):
        # See above
        offset = (cluster - 2) * self._cs
        if offset < 0:
            raise IndexError(cluster)
        self._mem[offset:offset + self._cs] = value

    def __delitem__(self, cluster):
        raise TypeError('FS length is immutable')

    def insert(self, cluster, value):
        """
        Raises :exc:`TypeError`; the FS length is immutable.
        """
        raise TypeError('FS length is immutable')


class FatDirectory(abc.Iterable):
    """
    An abstract :class:`~collections.abc.Iterable` representing a `FAT
    directory`_.

    When iterated, yields sequences ending with a single
    :class:`~nobodd.fat.DirectoryEntry` and preceded by zero or more
    :class:`~nobodd.fat.LongFilenameEntry` instances. Stops when the end of
    directory marker (an entry with NUL as the first filename byte) is
    encountered.

    .. _FAT directory:
        https://en.wikipedia.org/wiki/Design_of_the_FAT_file_system#Directory_table
    """
    MAX_SFN_SUFFIX = 0xFFFF
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
        appropriate. All instances must be yielded, in the order they appear on
        disk, regardless of whether they represent deleted entries or
        otherwise.
        """
        raise NotImplementedError

    @abstractmethod
    def _update_entry(self, offset, entry):
        """
        Abstract method which is expected to re-write *entry* (a
        :class:`~nobodd.fat.DirectoryEntry` or
        :class:`~nobodd.fat.LongFilenameEntry` instance) at the specified
        *offset* in the directory.
        """
        raise NotImplementedError

    def __iter__(self):
        for sequence in self._group_entries():
            yield [entry for offset, entry in sequence]

    def _group_entries(self):
        """
        Generator which yields sequences of tuples of offsets and either
        :class:`~nobodd.fat.LongFilenameEntry` or
        :class:`~nobodd.fat.DirectoryEntry` instances.

        Each sequence yielded represents a single (extant, non-deleted) file or
        directory entry with its long-filename entries at the start, and the
        directory entry as the final element. In other words, for a file with
        three long-filename entries, the following sequence might be yielded::

            [(0, <LongFilenameEntry>),
             (32, <LongFilenameEntry>),
             (64, <LongFilenameEntry>),
             (96, <DirectoryEntry>)]
        """
        entries = []
        for offset, entry in self._iter_entries():
            if isinstance(entry, LongFilenameEntry):
                if entry.sequence == 0xE5: # deleted entry
                    continue
            entries.append((offset, entry))
            if isinstance(entry, DirectoryEntry):
                if entry.filename[0] == 0: # end of valid entries
                    break
                elif entry.filename[0] != 0xE5: # deleted entry
                    yield entries
                entries = []

    def _clean_entries(self):
        """
        Find and remove all deleted entries from the directory.

        The method scans the directory for all directory entries and long
        filename entries which start with 0xE5, indicating a deleted entry,
        and overwrites them with later (not deleted) entries. Trailing entries
        are then zeroed out. The return value is the new offset of the EOF
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

    def _find_entry(self, entry):
        """
        Returns the sequence of offsets and entries (as generated by
        :meth:`_group_entries`) in the directory which matches *entry*.

        If *entry* has a non-zero cluster, the directory will be searched for
        an entry with a matching cluster. If none is found, or if *entry* has
        a cluster of zero, the directory will be searched and an entry with a
        matching SFN (short file-name).

        If no such sequence can be found in the directory, this raises
        :exc:`FileNotFoundError`.
        """
        find_sfn = entry.filename, entry.ext
        find_cluster = get_cluster(entry, self.fat_type)
        for sequence in self._group_entries():
            offset, entry = sequence[-1]
            sfn = entry.filename, entry.ext
            cluster = get_cluster(entry, self.fat_type)
            if (
                (find_cluster and cluster == find_cluster) or
                (0 in (cluster, find_cluster) and sfn == find_sfn)
            ):
                return sequence
        raise FileNotFoundError(
            f'No directory entry corresponding to cluster {cluster} found')

    def _make_filename_entries(self, filename, attr=0x20, ctime=None,
                               cluster=0):
        """
        Construct the :class:`~nobodd.fat.LongFilenameEntry` instances (if
        any), and :class:`~nobodd.fat.DirectoryEntry` required to represent the
        specified *filename* (with optional *attr*, *ctime*, and an initial
        *cluster*).

        This function merely constructs the instances, ensuring the (many,
        convoluted!) rules are followed, including that the short filename, if
        one is generated, is unique in this directory, and the long filename is
        encoded and check-summed appropriately.
        """
        if ctime is None:
            ctime = dt.datetime.now()
        cdate, ctime, ctime_ms = encode_timestamp(ctime)

        lfn, sfn, ext, attr2 = self._get_lfn_sfn_ext(filename)
        if lfn:
            cksum = lfn_checksum(sfn, ext)
            entries = [
                LongFilenameEntry(
                    sequence=(0x40 if terminal else 0) | part,
                    name_1=lfn[offset:offset + 10],
                    attr=0xF,
                    checksum=cksum,
                    name_2=lfn[offset + 10:offset + 22],
                    first_cluster=0,
                    name_3=lfn[offset + 22:offset + 26]
                )
                for terminal, (part, offset)
                in on_first(reversed(list(enumerate(range(len(lfn), 26), start=1))))
            ]
        else:
            entries = []

        entries.append(
            DirectoryEntry(
                filename=sfn,
                ext=ext,
                attr=attr,
                attr2=attr2,
                cdate=cdate,
                ctime=ctime,
                ctime_ms=ctime_ms,
                adate=cdate,
                mdate=cdate,
                mtime=ctime,
                first_cluster_hi=cluster >> 16,
                first_cluster_lo=cluster & 0xFFFF,
                size=0
            )
        )
        return entries

    def _get_lfn_sfn_ext(self, filename):
        """
        Given a *filename*, generate an appropriately encoded long filename
        (encoded in little-endian UCS-2), a short filename, an extension, and
        the case attributes. The result is a 4-tuple: ``lfn, sfn, ext, attr``.

        ``lfn``, ``sfn``, and ``ext`` will be :class:`bytes` strings, and
        ``attr`` will be an :class:`int`. If *filename* is capable of being
        represented as a short filename only (potentially with non-zero case
        attributes), ``lfn`` in the result will be blank.
        """
        # This function expects only valid long filenames to be passed.
        # Anything invalid should raise an exception
        if filename.strip(' ') != filename:
            raise ValueError(
                f'Filename {filename!r} starts or ends with space')
        if filename.endswith('.'):
            raise ValueError(
                f'Filename {filename!r} ends with dots')
        if not lfn_valid(filename):
            raise ValueError(
                f'Filename {filename!r} contains invalid characters, '
                'e.g. \\/:*?"<>|')
        # sfn == short filename, lfn == long filename, ext == extension
        sfn = sfn_safe(
            filename.lstrip('.').upper().encode(self._encoding, 'replace'))
        if b'.' in sfn:
            sfn, ext = sfn.rsplit(b'.', 1)
        else:
            sfn, ext = sfn, b''

        if len(sfn) <= 8 and len(ext) <= 3:
            # NOTE: Huh, a place where match..case might actually be
            # useful! Why isn't this a dict? It was originally, but in
            # purely symbolic cases (e.g. "." and "..") the transformed SFN
            # can be equivalent in all cases and we want to prefer the case
            # where attr is 0.
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
            attr = 0
            sfn_only = False

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
            re.compile(f'{re.escape(prefix[:i])}~([0-9]{{{i}}}).{re.escape(ext)}',
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

    def create(self, filename, attr=0x20, ctime=None, cluster=0):
        """
        Create a :class:`~nobodd.fat.DirectoryEntry` instance, and all
        preceding :class:`~nobodd.fat.LongFilenameEntry` instances within the
        directory, returning the new :class:`~nobodd.fat.DirectoryEntry`
        instance (the :class:`~nobodd.fat.LongFilenameEntry` instances are
        written but not returned).

        The "long" filename will be set to *filename*. The "short" filename in
        the final directory entry will be derived from *filename*, and will be
        unique within the directory.

        The *attr* parameter (which defaults to 0x20 or the DOS "Archive" bit)
        will be used for the attributes on the directory entry. The *ctime*
        parameter which defaults to :data:`None` meaning "now" is an optional
        :class:`~datetime.datetime` which will be used to set the ctime, mtime,
        and atime entries of the directory entry.

        If *cluster* is specified, it will be set as the first cluster of the
        new entry. This defaults to 0 indicating that no storage is associated
        with the entry.

        The return value is the sequence of new directory entries created.
        """
        entries = self._make_filename_entries(filename, attr, ctime, cluster)
        self.append(*entries, DirectoryEntry.eof())
        return entries

    def append(self, *entries):
        """
        Append *entries*, one or more :class:`~nobodd.fat.DirectoryEntry` or
        :class:`~nobodd.fat.LongFilenameEntry` instances, to the end of the
        directory.

        If the directory structure runs out of space (which is more likely
        under FAT-12 and FAT-16 where the root directory is fixed in size),
        then all deleted entries will be expunged, and the method will attempt
        to append the new entries once more.
        """
        eof_offset = 0
        for eof_offset, entry in self._iter_entries():
            if isinstance(entry, DirectoryEntry) and entry.filename[0] == 0:
                break
        # NOTE: We write the entries in reverse order to make it more likely
        # that anything scanning the directory simultaneously sees the append
        # as "atomic" (because the last item written overwrites the old EOF
        # marker entry)
        for cleaned in (False, True):
            offsets = range(
                eof_offset,
                eof_offset + len(entries) * DirectoryEntry._FORMAT.size,
                DirectoryEntry._FORMAT.size)
            try:
                for offset, entry in reversed(list(zip(offsets, entries))):
                    self._update_entry(offset, entry)
            except OSError as e:
                if e.errno == errno.ENOSPC:
                    eof_offset = self._clean_entries()
                else:
                    raise
            else:
                break

    def remove(self, entry):
        """
        Find *entry* (a :class:`~nobodd.fat.DirectoryEntry` instance) within
        the directory, by matching on the starting cluster, and mark it (and
        all preceding :class:`~nobodd.fat.LongFilenameEntry` instances) as
        deleted.

        .. note::

            This does *not* remove the entries from the directory, just changes
            the first character of the filename entry to 0xE5.
        """
        # NOTE: We update the DirectoryEntry first then work backwards, marking
        # the long filename entries. This ensures anything simultaneously
        # scanning the directory shouldn't find a "live" directory entry
        # preceded by "dead" long filenames
        for offset, old_entry in reversed(self._find_entry(entry)):
            if isinstance(old_entry, DirectoryEntry):
                self._update_entry(offset, old_entry._replace(
                    filename=b'\xe5' + old_entry.filename[1:]))
            else: # LongFilenameEntry
                self._update_entry(offset, old_entry._replace(sequence=0xE5))

    def update(self, entry):
        """
        Find *entry* (a :class:`~nobodd.fat.DirectoryEntry` instance) within
        the directory, by matching on the starting cluster, and update it with
        the current contents of *entry*.

        If *entry* cannot be found in the directory, :exc:`FileNotFoundError`
        is raised.
        """
        for offset, old_entry in reversed(self._find_entry(entry)):
            self._update_entry(offset, entry)
            break

    cluster = property(lambda self: self._get_cluster())


class FatRoot(FatDirectory):
    """
    An abstract derivative of :class:`FatDirectory` representing the
    (fixed-size) root directory of a FAT-12 or FAT-16 file-system. Must be
    constructed with *mem*, which is a buffer object covering the root
    directory clusters. The :class:`Fat12Root` and :class:`Fat16Root` classes
    are (trivial) concrete derivatives of this.
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
    :class:`FatFileSystem` instance) and *start*, the first cluster of the
    sub-directory.
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

    You should never need to construct this instance directly. Instead it is
    returned by the :meth:`~nobodd.path.FatPath.open` method of
    :class:`~nobodd.path.FatPath` instances. For example::

        from nobodd.disk import DiskImage
        from nobodd.fs import FatFileSystem

        with DiskImage('test.img') as img:
            with FatFileSystem(img.partitions[1].data) as fs:
                path = fs.root / 'bar.txt'
                with path.open('r', encoding='utf-8') as f:
                    print(f.read())

    Instances can (and should) be used as context managers to implicitly close
    references upon exiting the context. Instances are readable and seekable,
    and optionally writable, using all the methods derived from the base
    :class:`io.RawIOBase` class.
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
        which will be updated if/when a write to the file changes its size
        (extension or truncation).

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
            raise OSError(f'FatFileSystem containing {self._name} is closed')
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
