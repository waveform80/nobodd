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


def test_regular_operation(fat_disks_r, tmp_path):
    for fat_type, fat_disk in fat_disks_r.items():
        test_path = tmp_path / 'test.img'
        with test_path.open('w+b') as test_file:
            fat_disk.seek(0)
            copyfileobj(fat_disk, test_file)
        assert main([
            '--size', '100MB',
            '--boot-partition', '1',
            '--nbd-host', 'myserver',
            '--nbd-name', 'myshare',
            str(test_path)
        ]) == 0
        assert test_path.stat().st_size == 100 * 1048576
        with (
            test_path.open('r+b') as test_file,
            DiskImage(test_file) as img,
            FatFileSystem(img.partitions[1].data) as fs,
        ):
            assert (fs.root / 'cmdline.txt').read_text() == (
                'ip=dhcp nbdroot=myserver/myshare root=/dev/nbd0p5 '
                'console=serial0,115200 dwc_otg.lpm_enable=0 console=tty1 '
                'rootfstype=ext4 rootwait fixrtc quiet splash')

