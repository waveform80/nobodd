import gzip
from shutil import copyfileobj

import pytest


def make_disk(output, *, part_style='mbr', part_map={1: 'fat16', 5: 'ext2'}):
    disk, parts = {
        # Both layouts define the following partitions in a 32MB disk:
        # 1 -- 8MB
        # 2 -- 200KB
        # 5 -- 4MB
        # 6 -- 200KB
        'gpt': ('tests/gpt_disk.img.gz', {1: 2048, 2: 18432, 5: 20480, 6: 28672}),
        'mbr': ('tests/mbr_disk.img.gz', {1: 2048, 2: 18432, 5: 22528, 6: 32768}),
    }[part_style]
    fs = {
        # The fat12 image fits in any of the partitions (160KB unpacked). The
        # fat16 and ext2 images will only fit in partitions 1 and 5 (4MB
        # unpacked). The fat32 image will only fit in partition 1 (and, yes,
        # it's undersized according to the "spec", but that just goes to show
        # how ridiculous the spec is in certain places)
        'fat12': 'tests/fat12.img.gz',
        'fat16': 'tests/fat16.img.gz',
        'fat32': 'tests/fat32.img.gz',
        'ext2':  'tests/ext2.img.gz',
    }
    output.seek(0)
    with gzip.open(disk) as src:
        copyfileobj(src, output)
    for part_num, fat_type in part_map.items():
        output.seek(parts[part_num] * 512)
        with gzip.open(fs[fat_type]) as src:
            copyfileobj(src, output)
    output.seek(0)


@pytest.fixture(scope='session')
def gpt_disk(request, tmp_path_factory):
    tmp = tmp_path_factory.mktemp('gpt_disk')
    path = tmp / 'gpt.img'
    with path.open('wb') as output:
        make_disk(output, part_style='gpt')
    path.chmod(0o444)
    return path


@pytest.fixture()
def gpt_disk_w(request, tmp_path, gpt_disk):
    path = tmp_path / 'gpt-mutable.img'
    with gpt_disk.open('rb') as source, path.open('w+b') as output:
        copyfileobj(source, output)
    return path


@pytest.fixture(scope='session')
def mbr_disk(request, tmp_path_factory):
    tmp = tmp_path_factory.mktemp('mbr_disk')
    path = tmp / 'mbr.img'
    with path.open('wb') as output:
        make_disk(output, part_style='mbr')
    path.chmod(0o444)
    return path


@pytest.fixture()
def mbr_disk_w(request, tmp_path, mbr_disk):
    path = tmp_path / 'mbr-mutable.img'
    with mbr_disk.open('rb') as source, path.open('w+b') as output:
        copyfileobj(source, output)
    return path


@pytest.fixture(scope='session')
def fat12_disk(request, tmp_path_factory):
    tmp = tmp_path_factory.mktemp('fat12_disk')
    path = tmp / 'fat12.img'
    with path.open('wb') as output:
        make_disk(output, part_style='mbr', part_map={1: 'fat12'})
    path.chmod(0o444)
    return path


@pytest.fixture()
def fat12_disk_w(request, tmp_path, fat12_disk):
    path = tmp_path / 'fat12-mutable.img'
    with fat12_disk.open('rb') as source, path.open('w+b') as output:
        copyfileobj(source, output)
    return path


@pytest.fixture(scope='session')
def fat16_disk(request, tmp_path_factory):
    tmp = tmp_path_factory.mktemp('fat16_disk')
    path = tmp / 'fat16.img'
    with path.open('wb') as output:
        make_disk(output, part_style='mbr', part_map={1: 'fat16'})
    path.chmod(0o444)
    return path


@pytest.fixture()
def fat16_disk_w(request, tmp_path, fat16_disk):
    path = tmp_path / 'fat16-mutable.img'
    with fat16_disk.open('rb') as source, path.open('w+b') as output:
        copyfileobj(source, output)
    return path


@pytest.fixture(scope='session')
def fat32_disk(request, tmp_path_factory):
    tmp = tmp_path_factory.mktemp('fat32_disk')
    path = tmp / 'fat32.img'
    with path.open('wb') as output:
        make_disk(output, part_style='gpt', part_map={1: 'fat32'})
    path.chmod(0o444)
    return path


@pytest.fixture()
def fat32_disk_w(request, tmp_path, fat32_disk):
    path = tmp_path / 'fat32-mutable.img'
    with fat32_disk.open('rb') as source, path.open('w+b') as output:
        copyfileobj(source, output)
    return path


@pytest.fixture(scope='session')
def fat_disks(request, fat12_disk, fat16_disk, fat32_disk):
    yield {
        'fat12': fat12_disk,
        'fat16': fat16_disk,
        'fat32': fat32_disk,
    }


@pytest.fixture()
def fat_disks_w(request, fat12_disk_w, fat16_disk_w, fat32_disk_w):
    yield {
        'fat12': fat12_disk_w,
        'fat16': fat16_disk_w,
        'fat32': fat32_disk_w,
    }
