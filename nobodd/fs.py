import io
import os
import errno
import struct
import weakref
from collections import abc
from itertools import islice

from .fat import (
    BIOSParameterBlock,
    ExtendedBIOSParameterBlock,
    FAT32BIOSParameterBlock,
    DirectoryEntry,
    LongFilenameEntry,
)
from .path import FatPath
from .tools import pairwise


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
    object *mem* with a *sector_size* defaulting to 512 bytes.

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
    def __init__(self, mem, sector_size=512):
        self._fat_type, bpb, ebpb, ebpb_fat32 = fat_type(mem)
        if bpb.bytes_per_sector != sector_size:
            warnings.warn(
                UserWarning(
                    f'Unexpected sector-size in FAT, {bpb.bytes_per_sector}, '
                    f'differs from {sector_size}'))
        self._label = ebpb.volume_label.decode('ascii', 'replace').rstrip(' ')

        fat_size = (
            ebpb_fat32.sectors_per_fat if ebpb_fat32 is not None else
            bpb.sectors_per_fat) * bpb.bytes_per_sector
        root_size = bpb.max_root_entries * DirectoryEntry._FORMAT.size
        # Root size must be rounded up to a whole number of sectors
        root_size = (
            (root_size + (bpb.bytes_per_sector - 1)) //
            bpb.bytes_per_sector) * bpb.bytes_per_sector
        fat_offset = bpb.reserved_sectors * bpb.bytes_per_sector
        root_offset = fat_offset + (fat_size * bpb.fat_count)
        data_offset = root_offset + root_size
        self._fat = {
            'fat12': Fat12Table,
            'fat16': Fat16Table,
            'fat32': Fat32Table,
        }[self._fat_type](mem[fat_offset:root_offset], fat_size)
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

    def open_dir(self, cluster):
        """
        Opens the sub-directory in the specified *cluster*, returning a
        :class:`FatSubDirectory` instance representing it.

        .. warning::

            This method is intended for internal use by the
            :class:`~nobodd.path.FatPath` class.
        """
        return FatSubDirectory(self, cluster)

    def open_file(self, cluster, size):
        """
        Opens the file at the specified *cluster* with the specified *size* in
        bytes, returning a :class:`FatFile` instance representing it.

        .. warning::

            This method is intended for internal use by the
            :class:`~nobodd.path.FatPath` class.
        """
        return FatFile(self, cluster, size)

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
        if self._fat_type == 'fat32':
            return FatPath._from_index(self, Fat32Root(self, self._root))
        elif self._fat_type == 'fat16':
            return FatPath._from_index(self, Fat16Root(self._root))
        else:
            return FatPath._from_index(self, Fat12Root(self._root))


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
        Generator that scans the FAT from the start for free clusters, yielding
        each as it is found.
        """
        for cluster, value in enumerate(self):
            if value == 0 and self.min_valid <= cluster:
                yield cluster
            if cluster > self.max_valid:
                break


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

    def __init__(self, mem, fat_size):
        super().__init__()
        self._tables = tuple(
            mem[offset:offset + fat_size]
            for offset in range(0, len(mem), fat_size)
        )

    def __len__(self):
        return (super().__len__() * 2) // 3

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

    def __init__(self, mem, fat_size):
        super().__init__()
        self._tables = tuple(
            mem[offset:offset + fat_size].cast('H')
            for offset in range(0, len(mem), fat_size)
        )

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

    # TODO: Override mark_free and mark_end to preserve top nibble

    def __init__(self, mem, fat_size):
        super().__init__()
        self._tables = tuple(
            mem[offset:offset + fat_size].cast('I')
            for offset in range(0, len(mem), fat_size)
        )

    def __getitem__(self, cluster):
        return self._tables[0][cluster] & 0x0FFFFFFF

    def __setitem__(self, cluster, value):
        if not 0x00000000 <= value <= 0x0FFFFFFF:
            raise ValueError(f'{value} is outside range 0x00000000..0x0FFFFFFF')
        for table in self._tables:
            table[cluster] = (
                (table[cluster] & 0xF0000000) |
                (value & 0x0FFFFFFF))


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
        return self._mem[offset:offset + self._cs]

    def __setitem__(self, cluster, value):
        # See above
        offset = (cluster - 2) * self._cs
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

    When iterated, yields :class:`~nobodd.fat.DirectoryEntry` or
    :class:`~nobodd.fat.LongFilenameEntry` instances until the end of the
    directory is encountered.

    .. _FAT directory:
        https://en.wikipedia.org/wiki/Design_of_the_FAT_file_system#Directory_table
    """
    __slots__ = ()

    def _iter_entries(self):
        raise NotImplementedError

    def __iter__(self):
        entries = []
        for entry in self._iter_entries():
            entries.append(entry)
            if isinstance(entry, DirectoryEntry):
                if entry.filename[0] == 0:
                    break
                else:
                    yield entries
                    entries = []

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

    def __init__(self, mem):
        self._mem = mem

    def _get_cluster(self):
        return 0

    def _iter_entries(self):
        for offset in range(0, len(self._mem), DirectoryEntry._FORMAT.size):
            entry = DirectoryEntry.from_buffer(self._mem, offset)
            if entry.attr == 0x0F:
                entry = LongFilenameEntry.from_buffer(self._mem, offset)
            yield entry


class FatSubDirectory(FatDirectory):
    """
    A concrete derivative of :class:`FatDirectory` representing a sub-directory
    in a FAT file-system (of any type). Must be constructed with *fs* (a
    :class:`FatFileSystem` instance) and *start*, the first cluster of the
    sub-directory.
    """
    __slots__ = ('_cs', '_file')

    def __init__(self, fs, start):
        self._cs = fs.clusters.size
        self._file = FatFile(fs, start)

    def _get_cluster(self):
        return self._file._start

    def _iter_entries(self):
        buf = bytearray(self._cs)
        self._file.seek(0)
        while self._file.readinto(buf):
            for offset in range(0, len(buf), DirectoryEntry._FORMAT.size):
                entry = DirectoryEntry.from_buffer(buf, offset)
                if entry.attr == 0x0F:
                    entry = LongFilenameEntry.from_buffer(buf, offset)
                yield entry


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
    but not writable (this is a read-only implementation), using all the
    methods derived from the base :class:`io.RawIOBase` class.

    If constructed manually, *fs* is the associated :class:`FatFileSystem`
    instance, *start* is the first cluster of the file, and *size* is
    (optionally) the size in bytes of the file. If unspecified, the file is
    assumed to fill all its clusters.
    """
    __slots__ = ('_fs', '_start', '_map', '_size', '_pos')

    def __init__(self, fs, start, size=None):
        self._fs = fs
        self._start = start
        self._map = list(fs._fat.chain(start))
        # size should only be "None" in the case of directory entries; in this
        # case, scan the FAT to determine # of clusters (and thus max. size)
        if size is None:
            size = len(self._map) * self._fs._cs
        self._size = size
        self._pos = 0

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
        fs = self._get_fs()
        if self._entry is None:
            return fs.clusters.size * len(self._map)
        else:
            return self._entry.size

    def _set_size(self, new_size):
        # TODO
        pass

    def readable(self):
        return True

    def seekable(self):
        return True

    def writable(self):
        return not self._get_fs().fat.readonly

    def readall(self):
        size = self._get_size()
        buf = bytearray(max(0, size - self._pos))
        mem = memoryview(buf)
        pos = 0
        while self._pos < size:
            pos += self.readinto(mem[pos:])
        return bytes(buf)

    def readinto(self, buf):
        fs = self._get_fs()
        cs = fs.clusters.size
        # index is which cluster of the file we wish to read; i.e. index 0
        # represents the first cluster of the file; left and right are the byte
        # offsets within the cluster to return; read is the number of bytes to
        # return
        index = self._pos // cs
        left = self._pos - (index * cs)
        right = min(cs, left + len(buf), self._size - (index * cs))
        read = max(right - left, 0)
        if read > 0:
            buf[:read] = fs.clusters[self._map[index]][left:right]
            self._pos += read
        return read

    def write(self, buf):
        mem = memoryview(buf)
        fs = self._get_fs()
        if self._pos > self._size:
            # Pad the file to the current position. Note that this does *not*
            # count towards written
            self.truncate()
        written = 0
        while mem:
            # Alternate between filling a cluster with _write1, and allocating
            # a new cluster. This is far from the most efficient method (we're
            # not taking account of whether any clusters are actually
            # contiguous), but it is simple!
            w = self._write1(mem, fs)
            if w:
                written += w
                mem = mem[w:]
            else:
                for cluster in fs.fat.free():
                    fs.fat.mark_end(cluster)
                    fs.fat[self._map[-1]] = cluster
                    self._map.append(cluster)
                    break
                else:
                    # Unlike truncate, we don't pre-allocate the space we're
                    # going to write to. It is possible to wind up running out
                    # of space part-way through the write
                    # XXX raise or return written?
                    raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
        if self._pos > self._size:
            self._set_size(self._pos)
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
        cs = fs.clusters.size
        index = self._pos // cs
        left = self._pos - (index * cs)
        right = min(cs, left + len(mem))
        written = max(right - left, 0)
        if written > 0:
            try:
                fs.clusters[self._map[index]][left:right] = buf[:written]
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
            pos = self._size + pos
        else:
            raise ValueError(f'invalid whence: {whence}')
        if pos < 0:
            raise IOError('invalid argument')
        self._pos = pos
        return self._pos

    def truncate(self, size=None):
        fs = self._get_fs()
        cs = fs.clusters.size
        if size is None:
            size = self._pos
        if size == self._size:
            return size
        clusters = max(1, (size + cs - 1) // cs)
        if size > self._size:
            # If we're expanding the size of the file, zero the tail of the
            # current final cluster; this is necessary whether or not we're
            # expanding the actual number of clusters in the file. Note we
            # don't bother calculating exactly how many bytes to zero; we just
            # zero everything from the current size up to the end of the
            # cluster because that's fine in either case
            tail = len(self._map) * cs - self._size
            if tail:
                fs.clusters[self._map[-1]][-tail:] = b'\0' * tail
        if clusters > len(self._map):
            # Pre-calculate the clusters we're going to append. We don't want
            # to add any if we can't add them all. We then mark the clusters
            # in the FAT in reverse order, zeroing new blocks as we go so that
            # the final extension of the file is effectively atomic (from a
            # concurrent reader's perspective)
            to_append = list(islice(fs.fat.free(), clusters - len(self._map)))
            if len(to_append) + len(self._map) < clusters:
                raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
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
        return self._size
