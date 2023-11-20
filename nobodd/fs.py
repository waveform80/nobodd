import io
import struct
from collections import abc

from .fat import (
    BIOSParameterBlock,
    ExtendedBIOSParameterBlock,
    FAT32BIOSParameterBlock,
    DirectoryEntry,
    LongFilenameEntry,
)
from .path import FatPath


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
        self._cs = bpb.bytes_per_sector * bpb.sectors_per_cluster

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
        self._fat = mem[fat_offset:fat_offset + fat_size]
        self._data = mem[data_offset:]
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
            self._fat.release()
            self._data.release()
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


class Fat16Root(FatDirectory):
    """
    A derivative of :class:`FatDirectory` representing the (fixed-size) root
    directory of a FAT-16 file-system. Must be constructed with *mem*, which is
    a buffer object covering the root directory clusters.
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
    A derivative of :class:`FatDirectory` representing a sub-directory in a FAT
    file-system (of any type). Must be constructed with *fs* (a
    :class:`FatFileSystem` instance) and *start*, the first cluster of the
    sub-directory.
    """
    __slots__ = ('_cs', '_file')

    def __init__(self, fs, start):
        self._cs = fs._cs
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


# The root directory in FAT32 is simply a regular sub-directory with the
# starting cluster recorded in the BPB
Fat32Root = FatSubDirectory

# The root directory in FAT12 is structured the same as FAT16
Fat12Root = Fat16Root


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

    Instancese can (and should) be used as context managers to implicitly close
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
        self._map = list(self._get_clusters())
        # size should only be "None" in the case of directory entries; in this
        # case, scan the FAT to determine # of clusters (and thus max. size)
        if size is None:
            size = len(self._map) * self._fs._cs
        self._size = size
        self._pos = 0

    def _get_clusters(self):
        cluster = self._start
        if self._fs._fat_type == 'fat12':
            fat = self._fs._fat
            while 0x002 <= cluster <= 0xFEF:
                yield cluster
                if cluster % 2:
                    offset = cluster + (cluster >> 1) + 1
                    cluster = struct.unpack_from('<H', fat, offset) >> 4
                else:
                    offset = cluster + (cluster >> 1)
                    cluster = struct.unpack_from('<H', fat, offset) & 0x0FFF
        elif self._fs._fat_type == 'fat16':
            fat = self._fs._fat.cast('H')
            while 0x0002 <= cluster <= 0xFFEF:
                yield cluster
                cluster = fat[cluster]
        elif self._fs._fat_type == 'fat32':
            fat = self._fs._fat.cast('I')
            while 0x0000002 <= cluster <= 0xFFFFFEF:
                yield cluster
                cluster = fat[cluster] & 0x0FFFFFFF
        else:
            assert False, 'unrecognized FAT type'

    def readable(self):
        return True

    def seekable(self):
        return True

    def readall(self):
        buf = bytearray(self._size - self._pos)
        mem = memoryview(buf)
        pos = 0
        while self._pos < self._size:
            pos += self.readinto(mem[pos:])
        return bytes(buf)

    def readinto(self, buf):
        cs = self._fs._cs # cluster size
        # index is which cluster of the file we wish to read; i.e. index 0
        # represents the first cluster of the file; left and right are the byte
        # offsets within the cluster to return; read is the number of bytes to
        # return
        index = self._pos // cs
        left = self._pos - (index * cs)
        right = min(cs, left + len(buf), self._size - (index * cs))
        read = max(right - left, 0)
        if read > 0:
            # cluster is then the actual cluster number to read from the data
            # portion (offset by 2 because the first data cluster is #2)
            cluster = self._map[index] - 2
            buf[:read] = self._fs._data[
                cluster * cs:(cluster + 1) * cs][left:right]
            self._pos += read
        return read

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
