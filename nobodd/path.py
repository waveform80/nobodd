import io
import os
import re
import stat
import fnmatch
import datetime as dt
from pathlib import PurePosixPath
from urllib.parse import quote_from_bytes as urlquote_from_bytes
from itertools import zip_longest

from .fat import DirectoryEntry, LongFilenameEntry


class FatPath:
    """
    A :class:`~pathlib.Path`-like object representing a filepath within an
    associated :class:`~nobodd.fs.FatFileSystem`.

    There is rarely a need to construct this class directly. Instead, instances
    should be obtained via the :attr:`~nobodd.fs.FatFileSystem.root` property
    of a :class:`~nobodd.fs.FatFileSystem`. If constructed directly, *fs* is a
    :class:`~nobodd.fs.FatFileSystem` instance, and *pathsegments* is the
    sequence of strings to be joined with a path separator into the path.

    Instances provide almost all the facilities of the :class:`pathlib.Path`
    class they are modeled after, including the crucial :meth:`open` method,
    :meth:`iterdir`, :meth:`glob`, and :meth:`rglob` for enumerating
    directories, :meth:`stat`, :meth:`is_dir`, and :meth:`is_file` for querying
    information about files, division for construction of new paths, and all
    the usual :attr:`name`, :attr:`parent`, :attr:`stem`, and :attr:`suffix`
    attributes.

    As the implementation is read-only, any methods associated with file-system
    modification (``mkdir``, ``chmod``, etc.) are not included.
    """
    __slots__ = ('_fs', '_index', '_entry', '_parts', '_resolved')

    def __init__(self, fs, *pathsegments):
        self._fs = fs
        self._index = None
        self._entry = None
        self._parts = get_parts(*pathsegments)
        self._resolved = False

    def __repr__(self):
        return f'{self.__class__.__name__}({self._fs!r}, {self.__str__()!r})'

    def __str__(self):
        if self._parts == ('',):
            return '/'
        else:
            return '/'.join(self._parts)

    @classmethod
    def _from_index(cls, fs, index, prefix='/'):
        """
        Internal class method for constructing an instance from *fs* (a
        :class:`~nobodd.fs.FatFileSystem` instance), *index* (a
        :class:`~nobodd.fs.FatDirectory` instance), and a *prefix* path.
        """
        self = cls(fs, prefix)
        self._index = index
        self._resolved = True
        return self

    @classmethod
    def _from_entries(cls, fs, entries, prefix='/'):
        """
        Internal class method for constructing an instance from *fs* (a
        :class:`~nobodd.fs.FatFileSystem` instance), *entries* (a sequence of
        associated :class:`~nobodd.fat.LongFilenameEntry` and
        :class:`~nobodd.fat.DirectoryEntry` instances), and a *prefix* path.
        """
        filename, entry = get_filename_entry(entries)
        if not prefix.endswith('/'):
            prefix += '/'
        if entry.attr & 0x10: # directory
            cluster = entry.first_cluster_lo | (
                entry.first_cluster_hi << 16 if fs.fat_type == 'fat32' else 0)
            self = cls._from_index(
                fs, fs.open_dir(cluster), prefix + filename + '/')
        else:
            self = cls(fs, prefix + filename)
        self._entry = entry
        self._resolved = True
        return self

    def _resolve(self):
        """
        Internal method which "resolves" a constructed path to find the
        corresponding structures on disk (if the path exists).
        """
        if self._resolved:
            return
        assert self._index is None
        assert self._entry is None
        try:
            parts = self.parts
            if parts[0] != '/':
                raise ValueError('relative FatPath cannot be resolved')
            parts = parts[1:]
            parent = self._fs.root
            while parts:
                for child in parent.iterdir():
                    if child.name.lower() == parts[0].lower():
                        parent = child
                        parts = parts[1:]
                        break
                else: # path doesn't exist
                    return
            self._index = parent._index
            self._entry = parent._entry
        finally:
            self._resolved = True

    def _must_exist(self):
        """
        Internal method which is called to check that a constructed path
        actually exists in the file-system. Calls :meth:`_resolve` to find the
        corresponding disk structures (if they exist).
        """
        self._resolve()
        if not self.exists():
            raise FileNotFoundError(f'No such file or directory: {self}')

    def open(self, mode='r', buffering=-1, encoding=None, errors=None,
             newline=None):
        """
        Open the file pointed to by the path, like the built-in
        :func:`~io.open` function does. The *mode*, *buffering*, *encoding*,
        *errors* and *newline* options are as for the :func:`~io.open`
        function. If successful, a :class:`~nobodd.fs.FatFile` instance is
        returned.

        .. note::

            This implementation is read-only, so any modes other than "r" and
            "rb" will fail with :exc:`PermissionError`.
        """
        self._must_exist()
        if self.is_dir():
            raise IsADirectoryError(f'Is a directory: {self}')
        if set(mode) & {'+', 'w'}:
            raise PermissionError(f'Permission denied: {self}')
        if set(mode) > {'r', 'b'}:
            raise ValueError(f'invalid mode: {mode}')
        if 'b' in mode:
            if buffering == 1:
                warnings.warn(
                    RuntimeWarning(
                        "line buffering (buffering=1) isn't supported in "
                        "binary mode, the default buffer size will be used"))
                buffering = -1
            if encoding is not None:
                raise ValueError("binary mode doesn't take an encoding argument")
            if errors is not None:
                raise ValueError("binary mode doesn't take an errors argument")
            if newline is not None:
                raise ValueError("binary mode doesn't take a newline argument")
        else:
            if buffering == 0:
                raise ValueError("can't have unbuffered text I/O")
        f = self._fs.open_file(
            get_cluster(self._entry, self._fs.fat_type), self._entry.size)
        if buffering:
            if buffering in (-1, 1):
                buffering = io.DEFAULT_BUFFER_SIZE
            f = io.BufferedReader(f, buffering)
        if 'b' not in mode:
            f = io.TextIOWrapper(
                f, encoding=encoding, errors=errors, newline=newline,
                line_buffering=buffering == 1)
        return f

    def iterdir(self):
        """
        When the path points to a directory, yield path objects of the
        directory contents::

            >>> fs
            <FatFileSystem label='TEST' fat_type='fat16'>
            >>> for child in fs.root.iterdir(): child
            ...
            FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/foo')
            FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/bar.txt')
            FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/setup.cfg')
            FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/baz')
            FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/adir')
            FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/BDIR')

        The children are yielded in arbitrary order (the order they are found
        in the file-system), and the special entries ``'.'`` and ``'..'`` are
        not included.
        """
        self._must_exist()
        if not self.is_dir():
            raise NotADirectoryError(f'Not a directory: {self}')
        for entries in self._index:
            if not entries:
                raise ValueError('empty dir entries')
            if entries[-1].filename.startswith(b'\xe5'): # deleted
                continue # skip deleted entry
            elif (
                isinstance(entries[0], LongFilenameEntry) and
                entries[0].name_1.startswith(b'\xe5\x00')
            ):
                continue # skip deleted entry
            elif entries[-1].attr & 0x8:
                continue # skip volume label
            elif entries[-1].attr & 0x10:
                name = (entries[-1].filename + entries[-1].ext).rstrip(b' ')
                if name in (b'.', b'..'):
                    continue # skip "." and ".." directories
            yield FatPath._from_entries(self._fs, entries, prefix=str(self))

    def match(self, pattern):
        """
        Match this path against the provided glob-style pattern. Returns
        a :class:`bool` indicating if the match is successful.

        If *pattern* is relative, the path may be either relative or absolute,
        and matching is done from the right::

            >>> fs
            <FatFileSystem label='TEST' fat_type='fat16'>
            >>> f = fs / 'nobodd' / 'mbr.py'
            >>> f
            FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/nobodd/mbr.py')
            >>> f.match('*.py')
            True
            >>> f.match('nobodd/*.py')
            True
            >>> f.match('/*.py')
            False

        As FAT file-systems are case-insensitive, all matches are likewise
        case-insensitive.
        """
        pat_parts = get_parts(pattern.lower())
        if not pat_parts:
            raise ValueError('empty pattern')
        parts = self.parts
        if len(pat_parts) > len(parts):
            return False
        for part, pat in zip(reversed(parts), reversed(pat_parts)):
            if not fnmatch.fnmatchcase(part.lower(), pat):
                return False
        return True

    def _search(self, parent, parts):
        """
        Internal generator function for the implementation of :meth:`glob` and
        :meth:`rglob`. Called with *parent*, the containing :class:`FatPath`,
        and *parts*, the sequence of path components (in the form of strings)
        to match against.
        """

        def recursive(parent, parts):
            yield from self._search(parent, parts)
            for path in parent.iterdir():
                if path.is_dir():
                    yield from recursive(path, parts)

        def wildcard(parent, part, parts):
            part_re = re.compile(fnmatch.translate(part), re.IGNORECASE)
            for path in parent.iterdir():
                if part_re.match(path.name):
                    yield from self._search(path, parts)

        def precise(parent, part, parts):
            path = parent / part.lower()
            if path.exists():
                yield from self._search(path, parts)

        if not parts:
            yield parent
        elif parent.is_dir():
            part, *parts = parts
            if not part:
                raise ValueError('empty pattern component')
            elif part == '**':
                yielded = set()
                for path in recursive(parent, parts):
                    if path._path not in yielded:
                        yielded.add(path._path)
                        yield path
            elif '**' in part:
                raise ValueError(
                    'invalid pattern: ** can only be an entire component')
            elif '*' in part or '?' in part or '[' in part:
                yield from wildcard(parent, part, parts)
            else:
                yield from precise(parent, part, parts)

    def glob(self, pattern):
        """
        Glob the given relative *pattern* in the directory represented by this
        path, yielding matching files (of any kind)::

            >>> fs
            <FatFileSystem label='TEST' fat_type='fat16'>
            >>> sorted((fs.root / 'nobodd').glob('*.py'))
            [FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/nobodd/__init__.py'),
             FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/nobodd/disk.py'),
             FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/nobodd/fat.py'),
             FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/nobodd/fs.py'),
             FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/nobodd/gpt.py'),
             FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/nobodd/main.py'),
             FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/nobodd/mbr.py'),
             FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/nobodd/tftp.py'),
             FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/nobodd/tools.py')]

        Patterns are the same as for :func:`~fnmatch.fnmatch`, with the
        addition of "``**``" which means "this directory and all
        subdirectories, recursively". In other words, in enables recurisve
        globbing.

        .. warning::

            Using the "``**``" pattern in large directory trees may consume an
            inordinate amount of time.
        """
        self._must_exist()
        pat_parts = PurePosixPath(pattern.lower()).parts
        if not pat_parts:
            raise ValueError('Unacceptable pattern')
        if pat_parts[0] == '/':
            raise ValueError('Non-relative patterns are not supported')
        yield from self._search(self, pat_parts)

    def rglob(self, pattern):
        """
        This is like calling :meth:`glob` with a prefix of "``**/``" to the
        specified *pattern*.
        """
        self._must_exist()
        pat_parts = PurePosixPath(pattern.lower()).parts
        if not pat_parts:
            raise ValueError('Unacceptable pattern')
        if pat_parts[0] == '/':
            raise ValueError('Non-relative patterns are not supported')
        yield from self._search(self, ('**',) + pat_parts)

    def stat(self, *, follow_symlinks=True):
        """
        Return a :class:`os.stat_result` object containing information about
        this path::

            >>> fs
            <FatFileSystem label='TEST' fat_type='fat16'>
            >>> p = (fs.root / 'nobodd' / 'main.py')
            >>> p.stat().st_size
            388
            >>> p.stat().st_ctime
            1696606672.02

        .. note::

            In a FAT file-system, ``atime`` has day resolution, ``mtime`` has
            2-second resolution, and ``ctime`` has either 2-second or
            millisecond resolution depending on the driver that created it.
            Directories have no timestamp information.

        The *follow_symlinks* parameter is included purely for compatibility
        with :meth:`pathlib.Path.stat`; it is ignored as symlinks are not
        supported.
        """
        self._must_exist()
        if self._index is not None:
            return os.stat_result((
                stat.S_IFDIR | 0o555,  # mode
                self._index.cluster,   # inode
                id(self._fs),          # dev
                0,                     # nlink
                0,                     # uid
                0,                     # gid
                0,                     # size
                0,                     # atime XXX
                0,                     # mtime
                0))                    # ctime
        elif self._entry is not None:
            return os.stat_result((
                0o444,                                               # mode
                get_cluster(self._entry, self._fs.fat_type),         # inode
                id(self._fs),                                        # dev
                1,                                                   # nlink
                0,                                                   # uid
                0,                                                   # gid
                self._entry.size,                                    # size
                get_timestamp(self._entry.adate, 0),                 # atime
                get_timestamp(self._entry.mdate, self._entry.mtime), # mtime
                get_timestamp(                                       # ctime
                    self._entry.cdate, self._entry.ctime,
                    self._entry.ctime_ms * 10)))
        assert False, 'internal error'

    @property
    def fs(self):
        """
        Returns the :class:`FatFileSystem` instance that this instance was
        constructed with.
        """
        return self._fs

    @property
    def root(self):
        """
        Returns a string representing the root. This is always "/".
        """
        return '/'

    @property
    def anchor(self):
        """
        Returns the concatenation of the drive and root. This is always "/".
        """
        return '/'

    @property
    def name(self):
        """
        A string representing the final path component, excluding the root::

            >>> fs
            <FatFileSystem label='TEST' fat_type='fat16'>
            >>> p = (fs.root / 'nobodd' / 'main.py')
            >>> p.name
            'main.py'
        """
        return self._parts[-1]

    @property
    def suffix(self):
        """
        The file extension of the final component, if any:

            >>> fs
            <FatFileSystem label='TEST' fat_type='fat16'>
            >>> p = (fs.root / 'nobodd' / 'main.py')
            >>> p.suffix
            '.py'
        """
        name = self.name
        try:
            return name[name.rindex('.'):]
        except ValueError:
            return ''

    @property
    def suffixes(self):
        """
        A list of the path's file extensions:

            >>> fs
            <FatFileSystem label='TEST' fat_type='fat16'>
            >>> p = (fs.root / 'nobodd.tar.gz')
            >>> p.suffixes
            ['.tar', '.gz']
        """
        name = self.name
        if name.endswith('.'):
            return []
        else:
            return ['.' + s for s in name.lstrip('.').split('.')[1:]]

    @property
    def stem(self):
        """
        The final path component, without its suffix:

            >>> fs
            <FatFileSystem label='TEST' fat_type='fat16'>
            >>> p = (fs.root / 'nobodd' / 'main.py')
            >>> p.stem
            'main'
        """
        name = self.name
        try:
            return name[:name.rindex('.')]
        except ValueError:
            return name

    @property
    def parts(self):
        """
        A tuple giving access to the path's various components:

            >>> fs
            <FatFileSystem label='TEST' fat_type='fat16'>
            >>> p = (fs.root / 'nobodd' / 'main.py')
            >>> p.parts
            ['/', 'nobodd', 'main.py']
        """
        return tuple(
            '/' if index == 0 and part == '' else part
            for index, part in enumerate(self._parts))

    def read_text(self, encoding=None, errors=None):
        """
        Return the decoded contents of the pointed-to file as a string:

            >>> fs
            <FatFileSystem label='TEST' fat_type='fat16'>
            >>> (fs.root / 'foo').read_text()
            'foo\\n'
        """
        with self.open(encoding=encoding, errors=errors) as f:
            return f.read()

    def read_bytes(self):
        """
        Return the binary contents of the pointed-to file as a bytes object:

            >>> fs
            <FatFileSystem label='TEST' fat_type='fat16'>
            >>> (fs.root / 'foo').read_text()
            b'foo\\n'
        """
        with self.open(mode='rb') as f:
            return f.read()

    def exists(self):
        """
        Whether the path points to an existing file or directory:

            >>> fs
            <FatFileSystem label='TEST' fat_type='fat16'>
            >>> (fs.root / 'foo').exists()
            True
            >>> (fs.root / 'fooo').exists()
            False
        """
        self._resolve()
        return self._index is not None or self._entry is not None

    def is_dir(self):
        """
        Return a :class:`bool` indicating whether the path points to a
        directory. :data:`False` is also returned if the path doesn't exist.
        """
        self._resolve()
        return self._index is not None

    def is_file(self):
        """
        Returns a :class:`bool` indicating whether the path points to a regular
        file. :data:`False` is also returned if the path doesn't exist.
        """
        self._resolve()
        return self._index is None and self._entry is not None

    def is_mount(self):
        return self._parts == ('',)

    def is_absolute(self):
        return self._parts[:1] == ('',)

    def is_relative_to(self, *other):
        raise NotImplementedError

    def relative_to(self, *other):
        raise NotImplementedError

    def joinpath(self, *other):
        other = get_parts(*other)
        if other[:1] == ('',):
            return type(self)(self._fs, *other)
        else:
            return type(self)(self._fs, *self._parts, *other)

    def with_name(self, name):
        raise NotImplementedError

    def with_stem(self, stem):
        raise NotImplementedError

    def with_suffix(self, suffix):
        raise NotImplementedError

    __truediv__ = joinpath

    def __eq__(self, other):
        if not isinstance(other, FatPath):
            return NotImplemented
        if self._fs is not other._fs:
            raise TypeError(
                f'comparison is not supported between instances of '
                f'{self.__class__.__name__} with different file-systems')
        return all(
            sp.lower() == op.lower()
            for sp, op in zip_longest(self._parts, other._parts, fillvalue=''))

    def __le__(self, other):
        if not isinstance(other, FatPath):
            return NotImplemented
        if self._fs is not other._fs:
            raise TypeError(
                f'comparison is not supported between instances of '
                f'{self.__class__.__name__} with different file-systems')
        return all(
            sp.lower() <= op.lower()
            for sp, op in zip_longest(self.parts, other.parts, fillvalue=''))

    def __ne__(self, other):
        return not self.__eq__(other)

    def __lt__(self, other):
        return self.__le__(other) and not self.__eq__(other)

    def __gt__(self, other):
        return not self.__le__(other)

    def __ge__(self, other):
        return self.__eq__(other) or self.__gt__(other)

    @property
    def parents(self):
        result = [self.parent]
        self = result[-1]
        while self.parent is not self:
            result.append(self.parent)
            self = result[-1]
        return result

    @property
    def parent(self):
        parent = self._path.parent
        if self._path == parent:
            return self
        else:
            return type(self)(self._fs, parent)


def get_filename_entry(entries, dos_encoding='iso-8859-1'):
    # The extration of the long filename could be simpler, but let's do all
    # the checks we can (the structure includes a *lot* of redundancy for
    # checking things!)
    if not entries:
        raise ValueError('blank dir_entries')
    entry = entries[-1]
    if not isinstance(entry, DirectoryEntry):
        raise ValueError(
            f'last entry of entries must be a DirectoryEntry, not {entry!r}')

    if isinstance(entries[0], LongFilenameEntry):
        checksum = entries[0].checksum
        sequence = entries[0].sequence
        if not sequence & 0b1000000:
            raise ValueError('first LongFilenameEntry is not marked as terminal')
        sequence = sequence & 0b11111
        filename = entries[0].name_1 + entries[0].name_2 + entries[0].name_3
        for part in entries[1:-1]:
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
            filename = part.name_1 + part.name_2 + part.name_3 + filename
        if sequence > 1:
            raise ValueError(f'missing {sequence} LongFilenameEntry items')

        sum_ = 0
        for char in entry.filename + entry.ext:
            sum_ = (((sum_ & 1) << 7) + (sum_ >> 1) + char) & 0xFF
        if sum_ != checksum:
            raise ValueError(
                f'checksum mismatch in long filename: {sum_} != {checksum}')
        filename = filename.decode('utf-16le').rstrip('\uffff')
        # There may be one trailing NUL char, but there may not if the filename
        # fits perfectly in a LFN structure
        if filename[-1:] == '\x00':
            filename = filename[:-1]
        # But there shouldn't be more than one!
        if filename[-1:] == '\x00':
            raise ValueError(f'excess NUL chars in long filename: {filename!r}')
        if not filename:
            raise ValueError('empty long filename')
    else:
        filename = entry.filename.rstrip(b' ').decode(dos_encoding)
        if entry.ext != b'   ':
            filename += '.' + entry.ext.rstrip(b' ').decode(dos_encoding)
    return filename, entry


def get_timestamp(date, time, ms=0):
    return dt.datetime(
        year=1980 + ((date & 0xFE00) >> 9),
        month=(date & 0x1E0) >> 5,
        day=(date & 0x1F),
        hour=(time & 0xF800) >> 11,
        minute=(time & 0x7E0) >> 5,
        second=(time & 0x1F) * 2 + (ms // 1000),
        microsecond=(ms % 100) * 1000
    ).timestamp()


def get_cluster(entry, fat_type):
    return entry.first_cluster_lo | (
        entry.first_cluster_hi << 16 if fat_type == 'fat32' else 0)


def get_parts(*pathsegments):
    return tuple(
        part
        for i1, segment in enumerate(pathsegments)
        for i2, part in enumerate(segment.split('/'))
        if i1 == i2 == 0 or part)
