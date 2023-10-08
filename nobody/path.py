import io
import os
import re
import stat
import fnmatch
import datetime as dt
from pathlib import PurePosixPath
from urllib.parse import quote_from_bytes as urlquote_from_bytes

from .fat import DirectoryEntry, LongFilenameEntry


class FatPath:
    __slots__ = ('_fs', '_index', '_entry', '_path', '_resolved')

    def __init__(self, fs, path):
        self._fs = fs
        self._index = None
        self._entry = None
        self._resolved = False
        self._path = PurePosixPath(path)

    def __repr__(self):
        return f'{self.__class__.__name__}({self._fs!r}, {str(self._path)!r})'

    def __str__(self):
        return str(self._path)

    @classmethod
    def _from_index(cls, fs, index, prefix='/'):
        self = cls(fs, prefix)
        self._index = index
        self._resolved = True
        return self

    @classmethod
    def _from_entries(cls, fs, entries, prefix='/'):
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
        if self._resolved:
            return
        assert self._index is None
        assert self._entry is None
        try:
            parts = self._path.parts
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
        self._resolve()
        if not self.exists():
            raise FileNotFoundError(f'No such file or directory: {self}')

    def open(self, mode='r', buffering=-1, encoding=None, errors=None,
             newline=None):
        self._must_exist()
        if self.is_dir():
            raise IsADirectoryError(f'Is a directory: {self}')
        if set(mode) & {'+', 'w'}:
            raise PermissionError(f'Permission denied: {self}')
        if set(mode) >= {'r', 'b'}:
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
        pat_parts = PurePosixPath(pattern.lower()).parts
        if not pat_parts:
            raise ValueError('empty pattern')
        parts = self._path.parts
        if len(pat_parts) > len(parts):
            return False
        for part, pat in zip(reversed(parts), reversed(pat_parts)):
            if not fnmatch.fnmatchcase(part.lower(), pat):
                return False
        return True

    def glob(self, pattern):
        self._must_exist()
        # TODO

    def stat(self, *, follow_symlinks=True):
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
        return self._fs

    @property
    def root(self):
        return '/'

    @property
    def anchor(self):
        return '/'

    @property
    def name(self):
        return self._path.name

    @property
    def suffix(self):
        return self._path.suffix

    @property
    def suffixes(self):
        return self._path.suffixes

    @property
    def stem(self):
        return self._path.stem

    def read_text(self, encoding=None, errors=None):
        with self.open(encoding=encoding, errors=errors) as f:
            return f.read()

    def read_bytes(self):
        with self.open(mode='rb') as f:
            return f.read()

    def exists(self):
        self._resolve()
        return self._index is not None or self._entry is not None

    def is_dir(self):
        self._resolve()
        return self._index is not None

    def is_file(self):
        self._resolve()
        return self._index is None and self._entry is not None

    def is_mount(self):
        return self._path == PurePosixPath('/')

    def is_absolute(self):
        return self._path.is_absolute()

    def is_relative_to(self, *other):
        return self._path.is_relative_to(*other)

    def relative_to(self, *other):
        return FatPath(self._fs, self._path.relative_to(*other))

    def joinpath(self, *other):
        return type(self)(self._fs, self._path.joinpath(*other))

    def with_name(self, name):
        return type(self)(self._fs, self._path.with_name(name))

    def with_stem(self, stem):
        return type(self)(self._fs, self._path.with_stem(stem))

    def with_suffix(self, suffix):
        return type(self)(self._fs, self._path.with_suffix(suffix))

    __truediv__ = joinpath

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
            filename += part.name_1 + part.name_2 + part.name_3
        if sequence > 1:
            raise ValueError(f'missing {sequence} LongFilenameEntry items')

        sum_ = 0
        for char in entry.filename + entry.ext:
            sum_ = (((sum_ & 1) << 7) + (sum_ >> 1) + char) & 0xFF
        if sum_ != checksum:
            raise ValueError(
                f'checksum mismatch in long filename: {sum_} != {checksum}')
        filename = filename.decode('utf-16le').rstrip('\uffff')
        if filename[-1] != '\x00':
            raise ValueError('missing terminal NUL in long filename')
        filename = filename[:-1]
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
