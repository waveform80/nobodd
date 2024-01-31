import io
import mmap
import errno
import datetime as dt

import pytest

from nobodd.disk import DiskImage
from nobodd.fs import FatFileSystem
from nobodd.path import *


def test_path_init(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            assert repr(fs.root) == "FatPath(<fs>, '/')"
            p = fs.root / 'empty'
            assert repr(p) == "FatPath(<fs>, '/empty')"
            assert p.exists()
            assert p.is_file()
            assert not p.is_dir()
            p = fs.root / 'i-dont-exist'
            assert repr(p) == "FatPath(<fs>, '/i-dont-exist')"
            assert not p.exists()
            p = fs.root / 'a.dir/licenses'
            assert p.exists()
            assert not p.is_file()
            assert p.is_dir()
            with pytest.raises(ValueError):
                p = FatPath(fs, 'relative/path')
                p._resolve()
            with pytest.raises(ValueError):
                fs.root / 'emp*'


def test_path_closed_fs(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            p = fs.root / 'empty'
        del fs
        with pytest.raises(OSError):
            p._get_fs()


def test_path_open_readonly(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            p = fs.root / 'lots-of-zeros'
            with p.open('rb', buffering=0) as f:
                assert not isinstance(f, io.BufferedIOBase)
                assert f.tell() == 0
                assert f._mode == 'r'
            with p.open('rb', buffering=512) as f:
                assert isinstance(f, io.BufferedIOBase)
                assert f.tell() == 0
                assert f.raw._mode == 'r'
            with p.open('r') as f:
                assert isinstance(f, io.TextIOWrapper)
                assert f.tell() == 0


def test_path_open_bad(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            p = fs.root / 'lots-of-zeros'
            with pytest.warns(RuntimeWarning):
                # buffering=1 is line buffering; not valid but only a warning
                # in binary mode
                with p.open('rb', buffering=1) as f:
                    assert isinstance(f, io.BufferedIOBase)
            with pytest.raises(ValueError):
                p.open('foo')
            with pytest.raises(ValueError):
                p.open('rb', encoding='utf-8')
            with pytest.raises(ValueError):
                p.open('rb', errors='replace')
            with pytest.raises(ValueError):
                p.open('rb', newline='\n')
            with pytest.raises(ValueError):
                p.open('r', buffering=0)
            with pytest.raises(PermissionError):
                p.open('r+b')


def test_path_open_readwrite(fat12_disk):
    with DiskImage(fat12_disk, access=mmap.ACCESS_COPY) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            p = fs.root / 'lots-of-zeros'
            assert p.exists()
            with p.open('r+b', buffering=0) as f:
                assert not isinstance(f, io.BufferedIOBase)
                assert f.tell() == 0
                assert f._mode == '+'
            with pytest.raises(OSError):
                p.open('xb')
            with pytest.raises(ValueError):
                p.open('wab')
            p = fs.root / 'new-file'
            assert not p.exists()
            with p.open('wb', buffering=0) as f:
                assert f.tell() == 0
                assert f._mode == 'w'
            assert p.exists()


def test_path_open_create(fat12_disk):
    with DiskImage(fat12_disk, access=mmap.ACCESS_COPY) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            p = fs.root / 'new-file'
            with p.open('xb', buffering=0) as f:
                assert f.tell() == 0
                assert f._mode == 'w'
            assert p.exists()


def test_path_unlink(fat12_disk):
    with DiskImage(fat12_disk, access=mmap.ACCESS_COPY) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            # Test unlinking both an empty file and a file with allocated
            # clusters to hit all loop possibilities in unlink
            p = fs.root / 'lots-of-zeros'
            assert p.exists()
            p.unlink()
            p = fs.root / 'empty'
            assert p.exists()
            p.unlink()
            assert not p.exists()
            p.unlink(missing_ok=True)
            assert not p.exists()
            with pytest.raises(FileNotFoundError):
                p.unlink()


def test_path_rename(fat12_disk):
    with DiskImage(fat12_disk, access=mmap.ACCESS_COPY) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            s = fs.root / 'random'
            t = fs.root / 'still-random'
            o = fs.root / 'lots-of-zeros'
            d = fs.root / 'a.dir'
            assert s.exists() and not t.exists() and o.exists()
            buf = s.read_bytes()
            # Rename to new file; touches new entry, removes old entry
            s.rename(t)
            assert not s.exists() and t.exists() and o.exists()
            assert t.read_bytes() == buf
            # Rename over existing file; should remove existing file's clusters
            t.rename(o)
            assert not s.exists() and not t.exists() and o.exists()
            assert o.read_bytes() == buf
            # Cannot rename over a directory
            with pytest.raises(IsADirectoryError):
                o.rename(d)
            # Cannot rename across FS instances (even if targetting the same
            # underlying media)
            with FatFileSystem(img.partitions[1].data) as fs2:
                with pytest.raises(ValueError):
                    (fs2.root / 'empty').rename(fs.root / 'still-empty')
            # Can rename to implicitly constructed FatPath
            (fs.root / 'empty').rename('/still-empty')
            assert (fs.root / 'still-empty').exists()


def test_path_mkdir(fat12_disk):
    with DiskImage(fat12_disk, access=mmap.ACCESS_COPY) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            p = fs.root / 'b.dir'
            assert not p.exists()
            p.mkdir()
            assert p.exists()
            p.mkdir(exist_ok=True)
            assert p.exists()
            with pytest.raises(FileExistsError):
                p.mkdir()
            p = fs.root / 'empty'
            assert p.exists() and p.is_file()
            with pytest.raises(FileExistsError):
                p.mkdir(exist_ok=True)
            p = fs.root / 'foo' / 'bar'
            with pytest.raises(FileNotFoundError):
                p.mkdir()
            p.mkdir(parents=True)
            assert (
                p.parent.exists() and p.parent.is_dir() and
                p.exists() and p.is_dir()
            )


def test_path_rmdir(fat12_disk):
    with DiskImage(fat12_disk, access=mmap.ACCESS_COPY) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            p = fs.root / 'a.dir'
            with pytest.raises(OSError) as err:
                p.rmdir()
            assert err.value.errno == errno.ENOTEMPTY
            p = fs.root / 'empty.dir'
            assert p.exists()
            p.rmdir()
            assert not p.exists()
            with pytest.raises(OSError):
                fs.root.rmdir()


def test_path_resolve(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            p = fs.root / 'empty.dir' / '.' / '..' / 'a.dir' / 'licenses'
            q = p.resolve()
            assert p is not q
            assert str(q) == '/a.dir/licenses'
            q = p.resolve(strict=True)
            assert str(q) == '/a.dir/licenses'
            with pytest.raises(ValueError):
                FatPath(fs, 'foo').resolve()
            with pytest.raises(FileNotFoundError):
                (fs.root / 'foo').resolve(strict=True)


def test_path_match(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            p = fs.root / 'a.dir/licenses/gpl3.txt'
            assert p.match('*.txt')
            assert p.match('licenses/*.txt')
            assert not p.match('*.py')
            assert not p.match('/*.txt')
            assert not p.match('/a.dir/licenses/gpls/*.txt')
            with pytest.raises(ValueError):
                (fs.root / 'foo').match('')


def test_path_glob(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            p = fs.root / 'a.dir' / 'many-many-files'
            assert sum(1 for f in p.glob('?[0-9][02468].txt')) == 500
            assert sum(1 for f in fs.root.glob('*/many-many-files/*.txt')) == 1000
            assert sum(1 for f in fs.root.glob('**/many-*/*.txt')) == 1000
            with pytest.raises(ValueError):
                list(p.glob(''))
            with pytest.raises(ValueError):
                list(p.glob('/'))
            with pytest.raises(ValueError):
                list(p.glob('**.dir/*.txt'))


def test_path_rglob(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            p = fs.root / 'a.dir'
            # gpl3.txt + {000..999}.txt
            assert sum(1 for f in p.rglob('*.txt')) == 1001
            # gpl3.txt + *[13579].txt
            assert sum(1 for f in p.rglob('*[13579].txt')) == 501
            with pytest.raises(ValueError):
                list(p.rglob(''))
            with pytest.raises(ValueError):
                list(p.rglob('/'))
            with pytest.raises(ValueError):
                list(p.rglob('**.dir/*.txt'))


def test_path_stat(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            epoch = dt.datetime(2023, 1, 1).timestamp()
            p = fs.root / 'lots-of-zeros'
            s = p.stat()
            assert s.st_size > 0
            assert s.st_mode == 0o444
            assert s.st_ino != 0
            assert s.st_dev != 0
            assert s.st_nlink == 1
            assert s.st_uid == 0
            assert s.st_gid == 0
            assert s.st_ctime > epoch
            assert s.st_mtime > epoch
            assert s.st_atime > epoch
            p = fs.root / 'a.dir'
            s = p.stat()
            assert s.st_size == 0
            assert s.st_mode == 0o40555
            assert s.st_ino != 0
            assert s.st_nlink == 0
            assert s.st_uid == 0
            assert s.st_gid == 0
            assert s.st_ctime == 0
            assert s.st_mtime == 0
            assert s.st_atime == 0


def test_path_attr(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            epoch = dt.datetime(2023, 1, 1).timestamp()
            p = fs.root / 'a.dir' / 'licenses' / 'gpl3.txt'
            assert p.fs is fs
            assert p.root == '/'
            assert p.anchor == '/'
            assert p.name == 'gpl3.txt'
            assert p.suffix == '.txt'
            assert p.suffixes == ['.txt']
            assert p.stem == 'gpl3'
            assert p.parent.stem == 'licenses'
            assert p.parts == ('/', 'a.dir', 'licenses', 'gpl3.txt')
            assert fs.root.suffix == ''
            assert (fs.root / 'nobodd.tar.gz').suffixes == ['.tar', '.gz']
            assert str(fs.root.parent) == '/'
            assert str(FatPath(fs).parent) == '.'
            assert tuple(str(s) for s in p.parents) == (
                '/a.dir/licenses',
                '/a.dir',
                '/')


def test_path_join(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            p = fs.root / 'a.dir' / 'licenses'
            assert str(p / 'gpl3.txt') == '/a.dir/licenses/gpl3.txt'
            assert str(p / '/empty.dir') == '/empty.dir'


def test_path_queries(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            p = fs.root / 'a.dir' / 'licenses' / 'gpl3.txt'
            assert p.exists()
            assert p.is_file()
            assert not p.is_dir()
            assert p.parent.exists()
            assert p.parent.is_dir()
            assert not p.parent.is_file()
            assert fs.root.is_mount()
            assert not p.parent.is_mount()
            assert p.is_absolute()
            assert p.is_relative_to(p.parent)
            assert not p.is_relative_to(fs.root / 'empty.dir')
            assert str(p.relative_to(p.parent)) == 'gpl3.txt'
            assert not p.relative_to(p.parent).is_absolute()
            with pytest.raises(TypeError):
                p.relative_to()


def test_path_with(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            p = fs.root / 'a.dir' / 'licenses' / 'gpl3.txt'
            assert str(p.with_name('gpl2.txt')) == '/a.dir/licenses/gpl2.txt'
            with pytest.raises(ValueError):
                FatPath(fs).with_name('foo')
            with pytest.raises(ValueError):
                p.with_name('')
            assert str(p.with_stem('mit')) == '/a.dir/licenses/mit.txt'
            assert str(p.with_suffix('.rst')) == '/a.dir/licenses/gpl3.rst'
            assert str(p.with_suffix('')) == '/a.dir/licenses/gpl3'
            assert str(p.parent.with_suffix('.dir')) == '/a.dir/licenses.dir'
            with pytest.raises(ValueError):
                p.with_suffix('/rst')
            with pytest.raises(ValueError):
                p.with_suffix('rst')


def test_path_read(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            assert (fs.root / 'empty').read_bytes() == b''
            assert (fs.root / 'a.dir' / 'licenses' / 'gpl3.txt').read_text().startswith(
                'SPDX-License-Identifier: GPL-3.0-or-later\n')


def test_path_write(fat12_disk):
    with DiskImage(fat12_disk, access=mmap.ACCESS_COPY) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            p = fs.root / 'not-empty'
            assert not p.exists()
            assert p.write_text('foo bar baz') == 11
            assert p.read_text() == 'foo bar baz'

            data = b'\x01\x02\x03\x04' * 4096
            assert p.write_bytes(data) == len(data)
            assert p.read_bytes() == data


def test_path_touch(fat12_disk):
    with DiskImage(fat12_disk, access=mmap.ACCESS_COPY) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            p = fs.root / 'empty'
            old = p.stat()
            p.touch()
            new = p.stat()
            assert new.st_ctime == old.st_ctime
            assert new.st_atime == old.st_atime
            assert new.st_mtime > old.st_mtime
            with pytest.raises(FileExistsError):
                p.touch(exist_ok=False)

            p = fs.root / 'foo'
            assert not p.exists()
            p.touch(exist_ok=False)
            assert p.exists()


def test_path_compares(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            assert [str(p) for p in sorted(fs.root.iterdir())] == [
                '/a.dir',
                '/empty',
                '/empty.dir',
                '/lots-of-zeros',
                '/random',
            ]
            p1 = fs.root / 'a.dir'
            p2 = fs.root / 'empty.dir'
            assert p1 == p1
            assert p2 == p2
            assert p1 != p2
            assert p1 < p2
            assert p1 <= p2
            assert p1 <= p1
            assert p2 > p1
            assert p2 >= p1
            assert p2 >= p2
            assert not ((fs.root / 'a.dir') == '')
            assert (fs.root / 'a.dir') != ''
            with pytest.raises(TypeError):
                (fs.root / 'a.dir') > ''
            with pytest.raises(TypeError):
                (fs.root / 'a.dir') >= ''
            with pytest.raises(TypeError):
                (fs.root / 'a.dir') < ''
            with pytest.raises(TypeError):
                (fs.root / 'a.dir') <= ''
            with FatFileSystem(img.partitions[1].data) as fs2:
                with pytest.raises(TypeError):
                    (fs.root / 'a.dir') == (fs2.root / 'a.dir')
                with pytest.raises(TypeError):
                    (fs.root / 'a.dir') <= (fs2.root / 'a.dir')

