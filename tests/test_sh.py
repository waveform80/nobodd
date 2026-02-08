import os
import re
from unittest import mock

import pytest
from conftest import make_disk

from nobodd.sh import *


def test_help(capsys):
    with pytest.raises(SystemExit) as err:
        main(['--version'])
    assert err.value.code == 0
    capture = capsys.readouterr()
    assert capture.out.strip() == '0.5'

    with pytest.raises(SystemExit) as err:
        main(['--help'])
    assert err.value.code == 0
    capture = capsys.readouterr()
    assert capture.out.startswith('usage:')


def test_error_exit_no_debug(capsys, monkeypatch):
    with \
        mock.patch('nobodd.sh.get_parser') as get_parser, \
        monkeypatch.context() as m:

        m.delenv('DEBUG', raising=False)
        get_parser.side_effect = RuntimeError('trouble is bad')

        assert main(['help']) == 1
        capture = capsys.readouterr()
        assert 'trouble is bad' in capture.err


def test_error_exit_with_debug(monkeypatch):
    with \
        mock.patch('nobodd.sh.get_parser') as get_parser, \
        monkeypatch.context() as m:

        m.setenv('DEBUG', '1')
        get_parser.side_effect = RuntimeError('trouble is bad')

        with pytest.raises(RuntimeError):
            main(['help'])


def test_error_exit_with_pdb(monkeypatch):
    with \
        mock.patch('nobodd.sh.get_parser') as get_parser, \
        mock.patch('pdb.post_mortem') as post_mortem, \
        monkeypatch.context() as m:

        m.setenv('DEBUG', '2')
        get_parser.side_effect = RuntimeError('trouble is bad')

        main(['foo.img'])
        assert post_mortem.called


def test_std_path():
    stdout = StdPath(for_write=True)
    assert repr(stdout) == 'StdPath(for_write=True)'
    assert stdout.name == 'stdout'
    with pytest.raises(FileNotFoundError):
        stdout.unlink()

    stdin = StdPath(for_write=False)
    assert repr(stdin) == 'StdPath(for_write=False)'
    assert stdin.name == 'stdin'
    with pytest.raises(FileNotFoundError):
        stdin.unlink()


def test_help_commands(capsys):
    with pytest.raises(SystemExit) as err:
        main(['help'])
    assert err.value.code == 0
    capture = capsys.readouterr()
    assert '{help,cat,cp,ls,mkdir,mv,rm,rmdir,touch}' in capture.out


def test_help_cat(capsys):
    with pytest.raises(SystemExit) as err:
        main(['help', 'cat'])
    assert err.value.code == 0
    capture = capsys.readouterr()
    cat_help = capture.out
    with pytest.raises(SystemExit) as err:
        main(['cat', '--help'])
    assert err.value.code == 0
    assert capture.out == cat_help


def test_cat_read(fat12_disk, capsys):
    assert main(['cat', f'{fat12_disk}:1/cmdline.txt']) == 0
    capture = capsys.readouterr()
    assert capture.out == (
        'console=serial0,115200 dwc_otg.lpm_enable=0 console=tty1 '
        'root=LABEL=writable rootfstype=ext4 rootwait fixrtc '
        'quiet splash\n')


def test_cat_write(fat12_disk, tmp_path):
    foo = tmp_path / 'foo'
    bar = tmp_path / 'bar'
    baz = tmp_path / 'baz'
    foo.write_text('foo\n')
    bar.write_text('bar\n')
    assert main([
        'cat', str(foo), str(bar), f'{fat12_disk}:1/cmdline.txt',
        '-o', str(baz)
    ]) == 0
    assert baz.read_text() == (
        'foo\nbar\nconsole=serial0,115200 dwc_otg.lpm_enable=0 console=tty1 '
        'root=LABEL=writable rootfstype=ext4 rootwait fixrtc '
        'quiet splash\n')


def test_ls(fat16_disk, capsys):
    assert main(['ls', f'{fat16_disk}:/']) == 0
    capture = capsys.readouterr()
    assert capture.out == ''.join(s + '\n' for s in [
        'a.dir',
        'cmdline.txt',
        'empty',
        'empty.dir',
        'lots-of-zeros',
        'random',
    ])


def test_ls_long(fat16_disk, capsys):
    assert main(['ls', '-lS', f'{fat16_disk}:/']) == 0
    expected = re.compile(''.join(s + '\n' for s in [
        r'-r--r--r--  1 root root    32768 .* lots-of-zeros',
        r'-r--r--r--  1 root root     1024 .* random',
        r'-r--r--r--  1 root root      122 .* cmdline.txt',
        r'dr-xr-xr-x  2 root root        0 .* a\.dir',
        r'-r--r--r--  1 root root        0 .* empty',
        r'dr-xr-xr-x  2 root root        0 .* empty\.dir',
    ]))
    capture = capsys.readouterr()
    assert expected.match(capture.out)


def test_ls_files_and_dirs(fat16_disk, capsys):
    assert main([
        'ls', f'{fat16_disk}:/a.dir',
              f'{fat16_disk}:/a.dir/many-many-files/000.txt',
              f'{fat16_disk}:/a.dir/many-many-files/099.txt']) == 0
    expected = re.compile(''.join(s + '\n' for s in [
        r'.*/a\.dir/many-many-files/000\.txt',
        r'.*/a\.dir/many-many-files/099\.txt',
        r'',
        r'.*/a.dir:',
        r'licenses',
        r'many-many-files',
    ]))
    capture = capsys.readouterr()
    assert expected.match(capture.out)


def test_ls_all(fat16_disk, capsys):
    assert main(['ls', '-a', f'{fat16_disk}:/a.dir']) == 0
    expected = re.compile(''.join(s + '\n' for s in [
        r'.',
        r'..',
        r'licenses',
        r'many-many-files',
    ]))
    capture = capsys.readouterr()
    assert expected.match(capture.out)


def test_ls_all_root(fat16_disk, capsys):
    assert main(['ls', '-a', f'{fat16_disk}:/']) == 0
    expected = re.compile(''.join(s + '\n' for s in [
        r'.',
        r'..',
        'a.dir',
        'cmdline.txt',
        'empty',
        'empty.dir',
        'lots-of-zeros',
        'random',
    ]))
    capture = capsys.readouterr()
    assert expected.match(capture.out)


def test_rm(fat16_disk_w, capsys):
    assert main(['rm', f'{fat16_disk_w}:/empty', f'{fat16_disk_w}:/cmdline.txt']) == 0
    assert main(['ls', f'{fat16_disk_w}:/']) == 0
    expected = re.compile(''.join(s + '\n' for s in [
        'a.dir',
        #'cmdline.txt',
        #'empty',
        'empty.dir',
        'lots-of-zeros',
        'random',
    ]))
    capture = capsys.readouterr()
    assert expected.match(capture.out)
    assert main(['rm', f'{fat16_disk_w}:/does-not-exist']) != 0
    assert main(['rm', '-f', f'{fat16_disk_w}:/does-not-exist']) == 0


def test_rm_rf(fat16_disk_w, capsys):
    assert main(['rm', '-rf', f'{fat16_disk_w}:/a.dir']) == 0
    assert main(['ls', f'{fat16_disk_w}:/']) == 0
    expected = re.compile(''.join(s + '\n' for s in [
        #'a.dir',
        'cmdline.txt',
        'empty',
        'empty.dir',
        'lots-of-zeros',
        'random',
    ]))
    capture = capsys.readouterr()
    assert expected.match(capture.out)


def test_rmdir(fat16_disk_w, capsys):
    assert main(['rmdir', f'{fat16_disk_w}:/empty.dir']) == 0
    assert main(['ls', f'{fat16_disk_w}:/']) == 0
    expected = re.compile(''.join(s + '\n' for s in [
        'a.dir',
        'cmdline.txt',
        'empty',
        #'empty.dir',
        'lots-of-zeros',
        'random',
    ]))
    capture = capsys.readouterr()
    assert expected.match(capture.out)


def test_mkdir(fat16_disk_w, capsys):
    assert main(['mkdir', f'{fat16_disk_w}:/foo']) == 0
    assert main(['mkdir', f'{fat16_disk_w}:/foo/bar']) == 0
    assert main(['ls', f'{fat16_disk_w}:/']) == 0
    expected = re.compile(''.join(s + '\n' for s in [
        'a.dir',
        'cmdline.txt',
        'empty',
        'empty.dir',
        'foo',
        'lots-of-zeros',
        'random',
    ]))
    capture = capsys.readouterr()
    assert expected.match(capture.out)
    assert main(['ls', f'{fat16_disk_w}:/foo']) == 0
    expected = re.compile(''.join(s + '\n' for s in [
        'bar',
    ]))
    capture = capsys.readouterr()
    assert expected.match(capture.out)


def test_mkdir_p(fat16_disk_w, capsys):
    assert main(['mkdir', '-p', f'{fat16_disk_w}:/foo/bar']) == 0
    assert main(['ls', f'{fat16_disk_w}:/']) == 0
    expected = re.compile(''.join(s + '\n' for s in [
        'a.dir',
        'cmdline.txt',
        'empty',
        'empty.dir',
        'foo',
        'lots-of-zeros',
        'random',
    ]))
    capture = capsys.readouterr()
    assert expected.match(capture.out)
    assert main(['ls', f'{fat16_disk_w}:/foo']) == 0
    expected = re.compile(''.join(s + '\n' for s in [
        'bar',
    ]))
    capture = capsys.readouterr()
    assert expected.match(capture.out)


def test_touch(fat16_disk_w, capsys):
    assert main(['touch', f'{fat16_disk_w}:/foo']) == 0
    assert main(['touch', f'{fat16_disk_w}:/a.dir/foo']) == 0
    assert main(['ls', f'{fat16_disk_w}:/']) == 0
    expected = re.compile(''.join(s + '\n' for s in [
        'a.dir',
        'cmdline.txt',
        'empty',
        'empty.dir',
        'foo',
        'lots-of-zeros',
        'random',
    ]))
    capture = capsys.readouterr()
    assert expected.match(capture.out)
    assert main(['ls', f'{fat16_disk_w}:/a.dir']) == 0
    expected = re.compile(''.join(s + '\n' for s in [
        'foo',
        'licenses',
        'many-many-files',
    ]))
    capture = capsys.readouterr()
    assert expected.match(capture.out)


def test_cp(fat16_disk_w, tmp_path):
    assert main(['cp', f'{fat16_disk_w}:/cmdline.txt', str(tmp_path)]) == 0
    assert (tmp_path / 'cmdline.txt').read_text() == (
        'console=serial0,115200 dwc_otg.lpm_enable=0 console=tty1 '
        'root=LABEL=writable rootfstype=ext4 rootwait fixrtc quiet splash\n')
    assert main(['cp', f'{fat16_disk_w}:/empty.dir', str(tmp_path)]) == 0
    assert (tmp_path / 'empty.dir').is_dir()
    assert main(['cp', f'{fat16_disk_w}:/a.dir', str(tmp_path)]) == 1
    assert not (tmp_path / 'a.dir').exists()
    assert main([
        'cp', f'{fat16_disk_w}:/random', f'{fat16_disk_w}:/cmdline.txt',
        f'{fat16_disk_w}:/empty']) == 1


def test_cp_over(fat16_disk_w, capsys):
    assert main([
        'cp', f'{fat16_disk_w}:/cmdline.txt', f'{fat16_disk_w}:/random']) == 0
    assert main(['cat', f'{fat16_disk_w}:/random']) == 0
    capture = capsys.readouterr()
    assert capture.out == (
        'console=serial0,115200 dwc_otg.lpm_enable=0 console=tty1 '
        'root=LABEL=writable rootfstype=ext4 rootwait fixrtc quiet splash\n')


def test_cp_r(fat16_disk_w, tmp_path, capsys):
    assert main(['cp', '-r', f'{fat16_disk_w}:/a.dir', str(tmp_path)]) == 0
    assert (tmp_path / 'a.dir').exists()
    assert {
        str(p.relative_to(tmp_path)) for p in (tmp_path / 'a.dir').rglob('*')
    } == {
        'a.dir/licenses',
        'a.dir/licenses/gpl3.txt',
        'a.dir/many-many-files',
    } | {
        f'a.dir/many-many-files/{n:03d}.txt' for n in range(100)
    }
