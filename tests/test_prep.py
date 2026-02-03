# nobodd: a boot configuration tool for the Raspberry Pi
#
# Copyright (c) 2024 Dave Jones <dave.jones@canonical.com>
# Copyright (c) 2024 Canonical Ltd.
#
# SPDX-License-Identifier: GPL-3.0

import os
from shutil import copyfileobj
from unittest import mock

import pytest
from conftest import make_disk

from nobodd.disk import DiskImage
from nobodd.fs import FatFileSystem
from nobodd.mbr import MBRPartition
from nobodd.prep import *


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
        mock.patch('nobodd.prep.get_parser') as get_parser, \
        monkeypatch.context() as m:

        m.delenv('DEBUG', raising=False)
        get_parser.side_effect = RuntimeError('trouble is bad')

        assert main(['foo.img']) == 1
        capture = capsys.readouterr()
        assert 'trouble is bad' in capture.err


def test_error_exit_with_debug(monkeypatch):
    with \
        mock.patch('nobodd.prep.get_parser') as get_parser, \
        monkeypatch.context() as m:

        m.setenv('DEBUG', '1')
        get_parser.side_effect = RuntimeError('trouble is bad')

        with pytest.raises(RuntimeError):
            main(['foo.img'])


def test_error_exit_with_pdb(monkeypatch):
    with \
        mock.patch('nobodd.prep.get_parser') as get_parser, \
        mock.patch('pdb.post_mortem') as post_mortem, \
        monkeypatch.context() as m:

        m.setenv('DEBUG', '2')
        get_parser.side_effect = RuntimeError('trouble is bad')

        main(['foo.img'])
        assert post_mortem.called


def test_regular_operation(fat_disks_w, tmp_path):
    for fat_disk in fat_disks_w.values():
        assert fat_disk.stat().st_size < 50 * 1048576
        assert main([
            '--size', '50MB',
            '--nbd-host', 'myserver',
            '--nbd-name', 'myshare',
            '--serial', 'abcd1234',
            '--tftpd-conf', str(tmp_path / 'tftpd.conf'),
            '--nbd-conf', str(tmp_path / 'nbd.conf'),
            str(fat_disk)
        ]) == 0
        assert fat_disk.stat().st_size == 50 * 1048576
        with \
            DiskImage(fat_disk) as img, \
            FatFileSystem(img.partitions[1].data) as fs:

            assert (fs.root / 'cmdline.txt').read_text() == (
                'ip=dhcp nbdroot=myserver/myshare root=/dev/nbd0p5 '
                'console=serial0,115200 dwc_otg.lpm_enable=0 console=tty1 '
                'rootfstype=ext4 rootwait fixrtc quiet splash')
            assert (tmp_path / 'tftpd.conf').read_text() == f"""\
[board:abcd1234]
image = {fat_disk}
partition = 1
"""
            assert (tmp_path / 'nbd.conf').read_text() == f"""\
[myshare]
exportname = {fat_disk}
"""


def test_cmdline_no_newline(fat16_disk_w):
    with \
        DiskImage(fat16_disk_w, access=mmap.ACCESS_WRITE) as img, \
        FatFileSystem(img.partitions[1].data) as fs:

        # Ensure the transformation works even when cmdline.txt has no newlines
        path = fs.root / 'cmdline.txt'
        path.write_text(path.read_text().rstrip('\n'))

    assert main([
        '--size', '50MB',
        '--boot-partition', '1',
        '--root-partition', '5',
        '--nbd-host', 'myserver',
        '--nbd-name', 'myshare',
        str(fat16_disk_w)
    ]) == 0

    with \
        DiskImage(fat16_disk_w) as img, \
        FatFileSystem(img.partitions[1].data) as fs:

        assert (fs.root / 'cmdline.txt').read_text() == (
            'ip=dhcp nbdroot=myserver/myshare root=/dev/nbd0p5 '
            'console=serial0,115200 dwc_otg.lpm_enable=0 console=tty1 '
            'rootfstype=ext4 rootwait fixrtc quiet splash')


def test_already_big_enough(fat32_disk_w, caplog):
    with fat32_disk_w.open('r+b') as f:
        f.seek(70 * 1048576)
        f.truncate()

    with caplog.at_level(logging.INFO):
        assert main([
            '--verbose',
            '--size', '50MB',
            '--boot-partition', '1',
            '--root-partition', '5',
            '--nbd-host', 'myserver',
            '--nbd-name', 'myshare',
            str(fat32_disk_w)
        ]) == 0
        assert fat32_disk_w.stat().st_size == 70 * 1048576
        msg = (
            f'Skipping resize; {fat32_disk_w} is already '
            f'{50 * 1048576} bytes or larger')
        assert ('prep', logging.INFO, msg) in caplog.record_tuples


def test_detect_later_boot_partition(tmp_path, caplog):
    disk = tmp_path / 'weird.img'
    with disk.open('wb') as output:
        make_disk(output, part_style='mbr', part_map={5: 'ext2', 6: 'fat12'})
    with caplog.at_level(logging.INFO):
        assert main([
            '--verbose',
            '--size', '50MB',
            '--nbd-host', 'myserver',
            '--nbd-name', 'myshare',
            str(disk)
        ]) == 0
        assert ('prep', logging.INFO, 'Boot partition is 6 (fat12)') in caplog.record_tuples


def test_detect_multi_root(tmp_path, caplog):
    disk = tmp_path / 'weird.img'
    with disk.open('w+b') as output:
        make_disk(output, part_style='mbr', part_map={
            1: 'ext2', 5: 'ext2', 6: 'fat12'})
        # Re-write partition 1's type to Linux (0x83)
        output.seek(446)
        part = MBRPartition.from_bytes(output.read(16))
        part = part._replace(part_type=0x83)
        output.seek(446)
        output.write(MBRPartition._FORMAT.pack(*part))
    with caplog.at_level(logging.INFO):
        assert main([
            '--verbose',
            '--size', '50MB',
            '--nbd-host', 'myserver',
            '--nbd-name', 'myshare',
            str(disk)
        ]) == 0
        assert ('prep', logging.INFO, 'Root partition is 1') in caplog.record_tuples
        assert ('prep', logging.INFO, 'Boot partition is 6 (fat12)') in caplog.record_tuples


def test_detect_boot_fail(tmp_path, capsys):
    disk = tmp_path / 'empty.img'
    with disk.open('wb') as output:
        make_disk(output, part_style='mbr', part_map={})
    assert main([
        '--size', '50MB',
        '--nbd-host', 'myserver',
        '--nbd-name', 'myshare',
        str(disk)
    ]) == 1
    capture = capsys.readouterr()
    assert 'Unable to detect boot partition' in capture.err


def test_detect_root_fail(tmp_path, capsys):
    disk = tmp_path / 'allfat.img'
    with disk.open('wb') as output:
        make_disk(output, part_style='gpt', part_map={
            1: 'fat12', 2: 'fat32', 5: 'fat16', 6: 'fat12'})
    assert main([
        '--size', '50MB',
        '--nbd-host', 'myserver',
        '--nbd-name', 'myshare',
        str(disk)
    ]) == 1
    capture = capsys.readouterr()
    assert 'Unable to detect root partition' in capture.err


def test_default_host_share(fat16_disk_w):
    with mock.patch('nobodd.prep.socket.getfqdn') as getfqdn:
        getfqdn.return_value = 'louis.prima.org'
        assert main([
            '--size', '50MB',
            '--boot-partition', '1',
            '--root-partition', '5',
            str(fat16_disk_w)
        ]) == 0

    with \
        DiskImage(fat16_disk_w) as img, \
        FatFileSystem(img.partitions[1].data) as fs:

        assert (fs.root / 'cmdline.txt').read_text() == (
            'ip=dhcp nbdroot=louis.prima.org/fat16-mutable root=/dev/nbd0p5 '
            'console=serial0,115200 dwc_otg.lpm_enable=0 console=tty1 '
            'rootfstype=ext4 rootwait fixrtc quiet splash')


def test_remove_files(fat16_disk_w, caplog):
    with caplog.at_level(logging.INFO):
        assert main([
            '--verbose',
            '--size', '50MB',
            '--remove', 'a.dir',
            '--remove', 'random',
            '--remove', 'i-dont-exist',
            str(fat16_disk_w)
        ]) == 0

    with \
        DiskImage(fat16_disk_w) as img, \
        FatFileSystem(img.partitions[1].data) as fs:

        assert not (fs.root / 'a.dir').exists()
        assert not (fs.root / 'random').exists()
        assert (
            'prep', logging.WARNING,
            'No such file/dir /i-dont-exist in partition 1'
        ) in caplog.record_tuples


def test_bad_copy_files(fat16_disk_w, caplog, tmp_path):
    assert main([
        '--verbose',
        '--size', '50MB',
        '--copy', 'i-dont-exist',
        '--copy', 'seed',
        str(fat16_disk_w)
    ]) == 1


def test_copy_files(fat16_disk_w, caplog, tmp_path):
    config_txt = """\
[all]
arm_64bit=1
kernel=vmlinuz
initramfs initrd.img followkernel
cmdline=cmdline.txt
"""
    user_data = """\
chpasswd:
    expire: true
    list:
    - elmer:WascallyWabbit

# For maximum secuwity!
ssh_pwauth: true
"""
    network_config = """\
version: 2
wifis:
    wlan0:
        dhcp4: true
        optional: true
        access-points:
            elmerswifi:
                password: "VewyVewySecwet"
"""

    (tmp_path / 'seed').mkdir()
    (tmp_path / 'config.txt').write_text(config_txt)
    (tmp_path / 'seed' / 'meta-data').touch()
    (tmp_path / 'seed' / 'user-data').write_text(user_data)
    (tmp_path / 'seed' / 'network-config').write_text(network_config)
    (tmp_path / 'seed' / 'foo').mkdir()
    (tmp_path / 'seed' / 'foo' / 'a foo').touch()
    (tmp_path / 'seed' / 'foo' / 'a wild foo').touch()
    with caplog.at_level(logging.INFO):
        assert main([
            '--verbose',
            '--size', '50MB',
            '--copy', str(tmp_path / 'config.txt'),
            '--copy', str(tmp_path / 'seed'),
            str(fat16_disk_w)
        ]) == 0

    with \
        DiskImage(fat16_disk_w) as img, \
        FatFileSystem(img.partitions[1].data) as fs:

        assert (fs.root / 'config.txt').read_text() == config_txt
        assert (fs.root / 'seed').is_dir()
        assert (fs.root / 'seed' / 'meta-data').stat().st_size == 0
        assert (fs.root / 'seed' / 'user-data').read_text() == user_data
        assert (fs.root / 'seed' / 'network-config').read_text() == network_config
        assert (fs.root / 'seed' / 'foo').is_dir()
        assert (fs.root / 'seed' / 'foo' / 'a foo').is_file()
        assert (fs.root / 'seed' / 'foo' / 'a wild foo').is_file()
