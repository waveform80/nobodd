from shutil import copyfileobj

import pytest

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


def test_regular_operation(fat_disks_w, tmp_path):
    for fat_disk in fat_disks_w.values():
        assert fat_disk.stat().st_size < 100 * 1048576
        assert main([
            '--size', '100MB',
            '--boot-partition', '1',
            '--nbd-host', 'myserver',
            '--nbd-name', 'myshare',
            str(fat_disk)
        ]) == 0
        assert fat_disk.stat().st_size == 100 * 1048576
        with (
            DiskImage(fat_disk) as img,
            FatFileSystem(img.partitions[1].data) as fs,
        ):
            assert (fs.root / 'cmdline.txt').read_text() == (
                'ip=dhcp nbdroot=myserver/myshare root=/dev/nbd0p5 '
                'console=serial0,115200 dwc_otg.lpm_enable=0 console=tty1 '
                'rootfstype=ext4 rootwait fixrtc quiet splash')


def test_already_big_enough(fat16_disk_w, tmp_path, caplog):
    with caplog.at_level(logging.INFO):
        with fat16_disk_w.open('r+b') as f:
            f.seek(120 * 1048576)
            f.truncate()

        assert main([
            '--size', '100MB',
            '--boot-partition', '1',
            '--nbd-host', 'myserver',
            '--nbd-name', 'myshare',
            str(fat16_disk_w)
        ]) == 0
        assert fat16_disk_w.stat().st_size == 120 * 1048576
        msg = (
            f'Skipping resize; {fat16_disk_w} is already '
            f'{100 * 1048576} bytes or larger')
        assert ('prep', logging.INFO, msg) in caplog.record_tuples
