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
from nobodd.prep import *


def test_help(capsys):
    with pytest.raises(SystemExit) as err:
        main(['--version'])
    assert err.value.code == 0
    capture = capsys.readouterr()
    assert capture.out.strip() == '0.1'

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


def test_regular_operation(fat_disks_w):
    for fat_disk in fat_disks_w.values():
        assert fat_disk.stat().st_size < 50 * 1048576
        assert main([
            '--size', '50MB',
            '--nbd-host', 'myserver',
            '--nbd-name', 'myshare',
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
            '--size', '50MB',
            '--nbd-host', 'myserver',
            '--nbd-name', 'myshare',
            str(disk)
        ]) == 0
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
