import io
import os
import re
import stat
import fnmatch
import weakref
import datetime as dt
from urllib.parse import quote_from_bytes as urlquote_from_bytes
from itertools import zip_longest

from .fat import DirectoryEntry, LongFilenameEntry, lfn_checksum, lfn_valid
from .tools import encode_timestamp, decode_timestamp


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
    attributes. When the :class:`~nobodd.fs.FatFileSystem` is writable, then
    :meth:`unlink`, :meth:`touch`, :meth:`mkdir`, :meth:`rmdir`, and
    :meth:`rename` may also be used.

    Instances are also comparable for the purposes of sorting, but only within
    the same :class:`~nobodd.fs.FatFileSystem` instance (comparisons across
    file-system instances raise :exc:`TypeError`).
    """
    __slots__ = ('_fs', '_index', '_entry', '_parts', '_resolved')
    sep = '/'

    def __init__(self, fs, *pathsegments):
        self._fs = weakref.ref(fs)
        self._index = None
        self._entry = None
        self._parts = get_parts(*pathsegments)
        for index, part in enumerate(self._parts):
            if index == 0 and not part:
                continue # ignore root marker
            elif not lfn_valid(part):
                raise ValueError(f'invalid name {str(self)!r}')
        self._resolved = False

    def __repr__(self):
        return f'{self.__class__.__name__}(<fs>, {str(self)!r})'

    def __str__(self):
        if self._parts == ('',):
            return self.sep
        else:
            return self.sep.join(self._parts)

    def _get_fs(self):
        """
        Check the weak reference to the FatFileSystem. If it's still live,
        return the strong reference result. If it's disappeared, raise an
        :exc:`OSError` exception indicating the file-system has been closed.
        """
        fs = self._fs()
        if fs is None:
            raise OSError(f'FatFileSystem containing {self!s} is closed')
        return fs

    @classmethod
    def _from_index(cls, fs, index, path=sep):
        """
        Internal class method for constructing an instance from *fs* (a
        :class:`~nobodd.fs.FatFileSystem` instance), *index* (a
        :class:`~nobodd.fs.FatDirectory` instance), and a *path*.

        This is only used in the construction of directory instances.
        """
        self = cls(fs, path)
        self._index = index
        self._resolved = True
        return self

    @classmethod
    def _from_entry(cls, fs, index, entry, path=sep):
        """
        Internal class method for constructing an instance from *fs* (a
        :class:`~nobodd.fs.FatFileSystem` instance), *index* (a
        :class:`~nobodd.fs.FatDirectory instance), *entries* (a sequence of
        associated :class:`~nobodd.fat.LongFilenameEntry` and
        :class:`~nobodd.fat.DirectoryEntry` instances which must exist within
        *index*), and a *path*.
        """
        if entry.attr & 0x10: # directory
            cluster = get_cluster(entry, fs.fat_type)
            self = cls._from_index(fs, fs.open_dir(cluster), path)
        else:
            self = cls(fs, path)
            self._index = index
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
            head, *parts = self.parts
            if head != self.sep:
                raise ValueError('relative FatPath cannot be resolved')
            fs = self._get_fs()
            path = fs.root
            while parts:
                path._must_exist()
                path._must_be_dir()
                head, *parts = parts
                try:
                    path = FatPath._from_entry(
                        fs, path._index, path._index[head],
                        str(path / head))
                except KeyError:
                    # Path doesn't exist
                    return
            self._index = path._index
            self._entry = path._entry
        finally:
            self._resolved = True

    def _refresh(self):
        """
        Internal method which "refreshes" the _entry field to ensure that, if
        the first cluster of the file has changed (because the file was emptied
        and then re-filled) we have the correct value.

        This method should be called before using the cluster of the _entry
        field, unless you are certain the cluster cannot be wrong (e.g. the
        file backing sub-directories can never be emptied due to the "." and
        ".." entries so it never changes).

        The entry will be refreshed by searching for an entry in the _index
        with a matching name, i.e. this is no good if the calling method has
        renamed the entry.
        """
        if self._resolved:
            assert self._index
            assert self._entry
            assert not self._entry.attr & 0x10, 'no need for _refresh on dirs'
            try:
                self._entry = self._index[self.name]
            except KeyError:
                raise FileNotFoundError(
                    f'Directory entry for {self} disappeared')
        else:
            self._resolve()

    def _must_exist(self):
        """
        Internal method which is called to check that a constructed path
        actually exists in the file-system. Calls :meth:`_resolve` implicitly.
        """
        self._resolve()
        if not self.exists():
            raise FileNotFoundError(f'No such file or directory: {self}')

    def _must_not_exist(self):
        """
        Internal method which is called to check that a constructed path
        does not exist in the file-system. Calls :meth:`_resolve` implicitly.
        """
        self._resolve()
        if self.exists():
            raise FileExistsError(f'File exists: {self}')

    def _must_be_dir(self):
        """
        Internal method which is called to check that a constructed path is a
        directory. Calls :meth:`_resolve` implicitly.
        """
        self._resolve()
        if not self.is_dir():
            raise NotADirectoryError(f'Not a directory: {self}')

    def _must_not_be_dir(self):
        """
        Internal method which is called to check that a constructed path is not
        a directory. Calls :meth:`_resolve` implicitly.
        """
        self._resolve()
        if self.is_dir():
            raise IsADirectoryError(f'Is a directory: {self}')

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
        fs = self._get_fs()
        # Check the mode is valid and matches our expectations (can't open a
        # directory, can't read a non-existent file, etc.)
        if set(mode) > set('rwaxb+'):
            raise ValueError(f'invalid file mode {mode!r}')
        if len(set(mode) & set('rwax')) != 1:
            raise ValueError('must have exactly one of read, write, append, '
                             'exclusive creation mode')
        if fs.readonly and set(mode) & set('wax+'):
            raise PermissionError('fs is read-only')
        if 'r' in mode:
            self._must_exist()
        elif 'x' in mode:
            self._must_not_exist()
            mode = mode.replace('x', 'w')
        self._must_not_be_dir()

        # If self._entry is None at this point, we must be creating a file
        # so get the containing index and make an appropriate DirectoryEntry
        if self._entry is None:
            date, time, ms = encode_timestamp(dt.datetime.now())
            parent = self.parent
            parent._must_exist()
            parent._must_be_dir()
            self._index = parent._index
            self._entry = DirectoryEntry(
                # filename and ext of the entry will be ignored and overwritten
                # with SFN generated from the associated name
                filename=b'\0' * 8, ext=b'\0' * 3,
                # Set DOS "Archive" bit and nothing else
                attr=0x20, attr2=0,
                cdate=date, ctime=time, ctime_ms=ms,
                mdate=date, mtime=time,
                adate=date,
                first_cluster_lo=0, first_cluster_hi=0, size=0)
            try:
                parent._index[self.name] = self._entry
            except OSError:
                self._entry = None
                self._index = None
                raise

        # Sanity check the buffering parameter and create the underlying
        # FatFile instance with an appropriate mode
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
            f = fs.open_entry(self._index, self._entry, mode)
        else:
            if buffering == 0:
                raise ValueError("can't have unbuffered text I/O")
            else:
                line_buffering = buffering == 1
            f = fs.open_entry(self._index, self._entry, mode + 'b')

        # Wrap the underlying FatFile instance in whatever's necessary to make
        # it text-mode / buffered
        if buffering:
            if buffering in (-1, 1):
                buffering = fs.clusters.size
            f = {
                (True, False): io.BufferedReader,
                (False, True): io.BufferedWriter,
                (True, True):  io.BufferedRandom,
            }[(f.readable(), f.writable())](f, buffering)
        if 'b' not in mode:
            f = io.TextIOWrapper(
                f, encoding=encoding, errors=errors, newline=newline,
                line_buffering=line_buffering)
        return f

    def unlink(self, missing_ok=False):
        """
        Remove this file. If the path points to a directory, use :meth:`rmdir`
        instead.

        If *missing_ok* is :data:`False` (the default),
        :exc:`FileNotFoundError` is raised if the path does not exist. If
        *missing_ok* is :data:`True`, :exc:`FileNotFoundError` exceptions will
        be ignored (same behaviour as the POSIX ``rm -f`` command).
        """
        fs = self._get_fs()
        try:
            self._must_exist()
        except FileNotFoundError:
            if missing_ok:
                return
            else:
                raise
        self._must_not_be_dir()

        self._refresh()
        del self._index[self.name]
        for cluster in fs.fat.chain(get_cluster(self._entry, fs.fat_type)):
            fs.fat.mark_free(cluster)
        self._index = None
        self._entry = None

    def rename(self, target):
        """
        Rename this file or directory to the given *target*, and return a new
        :class:`FatPath` instance pointing to target. If *target* exists and is
        a file, it will be replaced silently. *target* can be either a string
        or another path object::

            >>> p = fs.root / 'foo'
            >>> p.open('w').write('some text')
            9
            >>> target = fs.root / 'bar'
            >>> p.rename(target)
            FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/bar')
            >>> target.read_text()
            'some text'

        The target path must be absolute. There are no guarantees of atomic
        behaviour (in contrast to :func:`os.rename`).

        .. note::

            :meth:`pathlib.Path.rename` permits relative paths, but interprets
            them relative to the working directory which is a concept
            :class:`FatPath` does not support.
        """
        fs = self._get_fs()
        if not isinstance(target, FatPath):
            target = FatPath(fs, target)
        target_fs = target._get_fs()
        if fs is not target_fs:
            raise ValueError('Cannot rename between FatFileSystem instances')

        if target.exists():
            target._must_not_be_dir()
            target._refresh()
            target_cluster = get_cluster(target._entry, fs.fat_type)
        else:
            target.touch()
            target_cluster = 0
        self._refresh()
        target._index[target.name] = self._entry
        del self._index[self.name]
        if target_cluster:
            for cluster in fs.fat.chain(target_cluster):
                fs.fat.mark_free(cluster)
        self._index = None
        self._entry = None
        return target

    def mkdir(self, mode=0o777, parents=False, exist_ok=False):
        """
        Create a new directory at this given path. The *mode* parameter exists
        only for compatibility with :class:`pathlib.Path` and is otherwise
        ignored. If the path already exists, :exc:`FileExistsError` is raised.

        If *parents* is true, any missing parents of this path are created as
        needed.

        If *parents* is false (the default), a missing parent raises
        :exc:`FileNotFoundError`.

        If *exist_ok* is false (the default), :exc:`FileExistsError` is raised
        if the target directory already exists.

        If *exist_ok* is true, :exc:`FileExistsError` exceptions will be
        ignored (same behavior as the POSIX ``mkdir -p`` command), but only if
        the last path component is not an existing non-directory file.
        """
        fs = self._get_fs()
        try:
            self._must_not_exist()
        except FileExistsError:
            if exist_ok and self.is_dir():
                return
            else:
                raise
        parent = self.parent
        try:
            parent._must_exist()
        except FileNotFoundError:
            if parents:
                parent.mkdir(mode, parents, exist_ok)
            else:
                raise
        parent._must_be_dir()

        date, time, ms = encode_timestamp(dt.datetime.now())
        cluster = next(fs.fat.free())
        fs.fat.mark_end(cluster)

        self._entry = DirectoryEntry(
            # filename and ext of the entry will be ignored and overwritten
            # with SFN generated from the associated name
            filename=b'\0' * 8, ext=b'\0' * 3,
            # Set DOS "Directory" bit and nothing else
            attr=0x10, attr2=0,
            cdate=date, ctime=time, ctime_ms=ms,
            mdate=date, mtime=time,
            adate=date,
            first_cluster_lo=cluster & 0xFFFF,
            first_cluster_hi=cluster >> 16 if fs.fat_type == 'fat32' else 0,
            size=0)
        try:
            parent._index[self.name] = self._entry
        except OSError:
            self._entry = None
            raise
        else:
            self._index = fs.open_dir(cluster)

        # Write the minimum entries that all sub-dirs must have: the "." and
        # ".." entries, and a terminal EOF entry
        self._index['.'] = self._entry
        if parent._entry is None:
            # Parent is the root
            self._index['..'] = self._entry._replace(
                first_cluster_hi=0, first_cluster_lo=0)
        else:
            self._index['..'] = parent._entry

    def rmdir(self):
        """
        Remove this directory. The directory must be empty.
        """
        fs = self._get_fs()
        self._must_exist()
        self._must_be_dir()
        if self._entry is not None:
            cluster = get_cluster(self._entry, fs.fat_type)
        else:
            cluster = 0
        if cluster == 0:
            raise OSError(errno.EACCES, 'Cannot remove the root directory')
        for item in self.iterdir():
            raise OSError(errno.ENOTEMPTY, os.strerror(errno.ENOTEMPTY))

        parent = self.resolve(strict=False).parent
        # NOTE: We already know parent must exist and be a dir
        parent._resolve()
        del parent._index[self.name]
        for cluster in fs.fat.chain(cluster):
            fs.fat.mark_free(cluster)
        self._index = None
        self._entry = None

    def resolve(self, strict=False):
        """
        Make the path absolute, resolving any symlinks. A new :class:`FatPath`
        object is returned.

        ``".."`` components are also eliminated (this is the only method to do
        so). If the path doesn't exist and *strict* is :data:`True`,
        :exc:`FileNotFoundError` is raised. If *strict* is :data:`False`, the
        path is resolved as far as possible and any remainder is appended
        without checking whether it exists.

        Note that as there is no concept of the "current" directory within
        :class:`~nobodd.fs.FatFileSystem`, relative paths cannot be resolved
        by this function, only absolute.
        """
        fs = self._get_fs()
        if not self.is_absolute():
            raise ValueError(f'Cannot resolve relative path {self!r}')
        parts = [p for p in self._parts if p != '.']
        while '..' in parts:
            i = parts.index('..')
            if i == 1:
                del parts[1]
            else:
                del parts[i - 1:i]
        result = FatPath(fs, *parts)
        if strict:
            result._must_exist()
        return result

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
        fs = self._get_fs()
        self._must_exist()
        self._must_be_dir()
        for name, entry in self._index.items():
            if name not in ('.', '..'):
                yield FatPath._from_entry(
                    fs, self._index, entry, str(self / name))

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
                    if path._parts not in yielded:
                        yielded.add(path._parts)
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
        subdirectories, recursively". In other words, it enables recurisve
        globbing.

        .. warning::

            Using the "``**``" pattern in large directory trees may consume an
            inordinate amount of time.
        """
        self._must_exist()
        pat_parts = tuple(p.lower() for p in self.parts)
        if not pat_parts:
            raise ValueError('Unacceptable pattern')
        if pat_parts[0] == self.sep:
            raise ValueError('Non-relative patterns are not supported')
        yield from self._search(self, pat_parts)

    def rglob(self, pattern):
        """
        This is like calling :meth:`glob` with a prefix of "``**/``" to the
        specified *pattern*.
        """
        self._must_exist()
        pat_parts = tuple(p.lower() for p in self.parts)
        if not pat_parts:
            raise ValueError('Unacceptable pattern')
        if pat_parts[0] == self.sep:
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
        fs = self._get_fs()
        self._must_exist()
        if self._entry is not None and not (self._entry.attr & 0x10):
            self._refresh()
            return os.stat_result((
                0o444,                                      # mode
                get_cluster(self._entry, fs.fat_type),      # inode
                id(fs),                                     # dev
                1,                                          # nlink
                0,                                          # uid
                0,                                          # gid
                self._entry.size,                           # size
                decode_timestamp(                           # atime
                    self._entry.adate, 0).timestamp(),
                decode_timestamp(                           # mtime
                    self._entry.mdate, self._entry.mtime).timestamp(),
                decode_timestamp(                           # ctime
                    self._entry.cdate, self._entry.ctime,
                    self._entry.ctime_ms * 10).timestamp()))
        else: # self._index is not None is guaranteed by _must_exist
            # NOTE: No need to _refresh as the cluster of a sub-directory can
            # never change
            return os.stat_result((
                stat.S_IFDIR | 0o555,  # mode
                self._index.cluster,   # inode
                id(fs),                # dev
                0,                     # nlink
                0,                     # uid
                0,                     # gid
                0,                     # size
                0,                     # atime
                0,                     # mtime
                0))                    # ctime

    @property
    def fs(self):
        """
        Returns the :class:`~nobodd.fs.FatFileSystem` instance that this
        instance was constructed with.
        """
        return self._get_fs()

    @property
    def root(self):
        """
        Returns a string representing the root. This is always "/".
        """
        return self.sep

    @property
    def anchor(self):
        """
        Returns the concatenation of the drive and root. This is always "/".
        """
        return self.sep

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
    def shortname(self):
        """
        A string representing the shortened version of the final path
        component, excluding the root::

            >>> fs
            <FatFileSystem label='TEST' fat_type='fat16'>
            >>> p = (fs.root / 'nobodd' / 'main.py')
            >>> p.name
            'MAIN.PY'

        Short names are always upper-case and limited to a length of 8.3 (8
        characters for the filename, 3 for the extension).
        """
        return self._sfn

    @property
    def suffix(self):
        """
        The file extension of the final component, if any::

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
        A list of the path's file extensions::

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
        The final path component, without its suffix::

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
        A tuple giving access to the path's various components::

            >>> fs
            <FatFileSystem label='TEST' fat_type='fat16'>
            >>> p = (fs.root / 'nobodd' / 'main.py')
            >>> p.parts
            ['/', 'nobodd', 'main.py']
        """
        return tuple(
            self.sep if index == 0 and part == '' else part
            for index, part in enumerate(self._parts))

    @property
    def parent(self):
        """
        The logical parent of the path::

            >>> fs
            <FatFileSystem label='TEST' fat_type='fat16'>
            >>> p = (fs.root / 'nobodd' / 'main.py')
            >>> p.parent
            FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/nobodd')

        You cannot go past an anchor::

            >>> p = (fs.root / 'nobodd' / 'main.py')
            >>> p.parent.parent.parent
            FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/')
        """
        fs = self._get_fs()
        if len(self._parts) > 1:
            return type(self)(fs, *self._parts[:-1])
        elif self._parts == ('',) or self._parts == ('.',):
            return self
        else:
            return type(self)(fs, '.')

    @property
    def parents(self):
        """
        An immutable sequence providing access to the logical ancestors of the
        path::

            >>> fs
            <FatFileSystem label='TEST' fat_type='fat16'>
            >>> p = (fs.root / 'nobodd' / 'main.py')
            >>> p.parents
            (FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/nobodd'),
             FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/'))
        """
        result = [self.parent]
        self = result[-1]
        while self.parent is not self:
            result.append(self.parent)
            self = result[-1]
        return tuple(result)

    def read_text(self, encoding=None, errors=None):
        """
        Return the decoded contents of the pointed-to file as a string::

            >>> fs
            <FatFileSystem label='TEST' fat_type='fat16'>
            >>> (fs.root / 'foo').read_text()
            'foo\\n'
        """
        with self.open(encoding=encoding, errors=errors) as f:
            return f.read()

    def write_text(self, data, encoding=None, errors=None, newline=None):
        """
        Open the file pointed to in text mode, write *data* to it, and close
        the file::

            >>> p = fs.root / 'my_text_file'
            >>> p.write_text('Text file contents')
            18
            >>> p.read_text()
            'Text file contents'

        An existing file of the same name is overwritten. The optional
        parameters have the same meaning as in :meth:`open`.
        """
        with self.open(mode='w', encoding=encoding, errors=errors,
                       newline=newline) as f:
            return r.write(data)

    def read_bytes(self):
        """
        Return the binary contents of the pointed-to file as a bytes object::

            >>> fs
            <FatFileSystem label='TEST' fat_type='fat16'>
            >>> (fs.root / 'foo').read_text()
            b'foo\\n'
        """
        with self.open(mode='rb') as f:
            return f.read()

    def write_bytes(self, data):
        """
        Open the file pointed to in bytes mode, write *data* to it, and close
        the file::

            >>> p = fs.root / 'my_binary_file'
            >>> p.write_bytes(b'Binary file contents')
            20
            >>> p.read_bytes()
            b'Binary file contents'

        An existing file of the same name is overwritten.
        """
        with self.open(mode='wb') as f:
            return f.write(data)

    def touch(self, mode=0o666, exist_ok=True):
        """
        Create a file at this given path. The *mode* parameter is only present
        for compatibility with :class:`pathlib.Path` and is otherwise ignored.
        If the file already exists, the function succeeds if *exist_ok* is
        :data:`True` (and its modification time is updated to the current
        time), otherwise :exc:`FileExistsError` is raised.
        """
        if exist_ok:
            with self.open('ab', buffering=0) as f:
                f._set_mtime()
        else:
            with self.open('xb', buffering=0) as f:
                pass

    def exists(self):
        """
        Whether the path points to an existing file or directory::

            >>> fs
            <FatFileSystem label='TEST' fat_type='fat16'>
            >>> (fs.root / 'foo').exists()
            True
            >>> (fs.root / 'fooo').exists()
            False
        """
        self._resolve()
        return self._index is not None and (
            self._entry is not None or self._parts == ('',))

    def is_dir(self):
        """
        Return a :class:`bool` indicating whether the path points to a
        directory. :data:`False` is also returned if the path doesn't exist.
        """
        self._resolve()
        return self._index is not None and (
            self._entry is None or bool(self._entry.attr & 0x10))

    def is_file(self):
        """
        Returns a :class:`bool` indicating whether the path points to a regular
        file. :data:`False` is also returned if the path doesn't exist.
        """
        self._resolve()
        return self._entry is not None and not (self._entry.attr & 0x10)

    def is_mount(self):
        """
        Returns a :class:`bool` indicating whether the path is a *mount point*.
        In this implementation, this is only :data:`True` for the root path.
        """
        return self._parts == ('',)

    def is_absolute(self):
        """
        Return whether the path is absolute or not. A path is considered
        absolute if it has a "/" prefix.
        """
        return self._parts[:1] == ('',)

    def is_relative_to(self, *other):
        """
        Return whether or not this path is relative to the *other* path.
        """
        try:
            self.relative_to(*other)
        except ValueError:
            return False
        else:
            return True

    def relative_to(self, *other):
        """
        Compute a version of this path relative to the path represented by
        *other*. If it's impossible, :exc:`ValueError` is raised.
        """
        if not other:
            raise TypeError('need at least one argument')
        fs = self._get_fs()
        to = type(self)(fs, *other)
        n = len(to._parts)
        if self._parts[:n] != to._parts:
            raise ValueError(
                f'{self!r} is not in the subpath of {to!r} OR one path is '
                f'relative and the other is absolute')
        return type(self)(fs, *self._parts[n:])

    def joinpath(self, *other):
        """
        Calling this method is equivalent to combining the path with each of
        the *other* arguments in turn::

            >>> fs
            <FatFileSystem label='TEST' fat_type='fat16'>
            >>> fs.root
            FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/')
            >>> fs.root.joinpath('nobodd')
            FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/nobodd')
            >>> fs.root.joinpath('nobodd', 'main.py')
            FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/nobodd/main.py')
        """
        fs = self._get_fs()
        other = get_parts(*other)
        if other[:1] == ('',):
            return type(self)(fs, *other)
        else:
            return type(self)(fs, *self._parts, *other)

    def with_name(self, name):
        """
        Return a new path with the :attr:`name` changed. If the original path
        doesn't have a name, :exc:`ValueError` is raised.
        """
        fs = self._get_fs()
        if not self.name:
            raise ValueError(f'{self!r} has an empty name')
        if not name:
            raise ValueError(f'invalid name {name!r}')
        return type(self)(fs, *self._parts[:-1], name)

    def with_stem(self, stem):
        """
        Return a new path with the :attr:`stem` changed. If the original path
        doesn't have a name, :exc:`ValueError` is raised.
        """
        return self.with_name(stem + self.suffix)

    def with_suffix(self, suffix):
        """
        Return a new path with the :attr:`suffix` changed. If the original path
        doesn't have a suffix, the new *suffix* is appended instead. If the
        *suffix* is an empty string, the original suffix is removed.
        """
        if self.sep in suffix:
            raise ValueError(f'Invalid suffix {suffix!r}')
        if suffix and not suffix.startswith('.') or suffix == '.':
            raise ValueError(f'Invalid suffix {suffix!r}')
        name = self.name
        old_suffix = self.suffix
        if not old_suffix:
            name = name + suffix
        else:
            name = name[:-len(old_suffix)] + suffix
        return self.with_name(name)

    __truediv__ = joinpath

    def __eq__(self, other):
        if not isinstance(other, FatPath):
            return NotImplemented
        self_fs = self._get_fs()
        other_fs = other._get_fs()
        if self_fs is not other_fs:
            raise TypeError(
                f'comparison is not supported between instances of '
                f'{self.__class__.__name__} with different file-systems')
        return len(sp) == len(op) and all(
            sp.lower() == op.lower()
            for sp, op in zip_longest(self._parts, other._parts, fillvalue=''))

    def __le__(self, other):
        if not isinstance(other, FatPath):
            return NotImplemented
        self_fs = self._get_fs()
        other_fs = other._get_fs()
        if self_fs is not other_fs:
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


def get_cluster(entry, fat_type):
    """
    Given *entry*, a :class:`~nobodd.fat.DirectoryEntry`, and the *fat_type*
    indicating the size of FAT clusters, return the first cluster of the file
    associated with the directory entry.
    """
    return entry.first_cluster_lo | (
        entry.first_cluster_hi << 16 if fat_type == 'fat32' else 0)


def get_parts(*pathsegments):
    """
    Given *pathsegments*, split them on the "/" path separator, and return a
    :class:`tuple` containing each path segment.

    If the path segments refer to an absolute path (beginning with "/") the
    first element of the returned :class:`tuple` will be an empty string.
    """
    return tuple(
        part
        for i1, segment in enumerate(pathsegments)
        for i2, part in enumerate(str(segment).split('/'))
        if i1 == i2 == 0 or part)
