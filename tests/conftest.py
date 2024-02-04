import gzip
from shutil import copyfileobj

import pytest


def make_disk(output, *, part_style='mbr', part_num=1, fat_type='fat16'):
    disk, parts = {
        'gpt': ('tests/gpt_disk.img.gz', {1: 2048, 2: 18432, 5: 20480, 6: 28672}),
        'mbr': ('tests/mbr_disk.img.gz', {1: 2048, 2: 18432, 5: 22528, 6: 32768}),
    }[part_style]
    fs = {
        'fat12': 'tests/fat12.img.gz',
        'fat16': 'tests/fat16.img.gz',
        'fat32': 'tests/fat32.img.gz',
    }[fat_type]
    output.seek(0)
    with gzip.open(disk) as src:
        copyfileobj(src, output)
    output.seek(parts[part_num] * 512)
    with gzip.open(fs) as src:
        copyfileobj(src, output)
    output.seek(0)


@pytest.fixture(scope='session')
def gpt_disk(request, tmp_path_factory):
    tmp = tmp_path_factory.mktemp('gpt_disk')
    path = tmp / 'gpt.img'
    with path.open('wb') as output:
        make_disk(output, part_style='gpt')
    path.chmod(0o444)
    with path.open('rb') as output:
        yield output


@pytest.fixture()
def gpt_disk_w(request, tmp_path, gpt_disk):
    with (tmp_path / 'gpt-mutable.img').open('w+b') as output:
        gpt_disk.seek(0)
        copyfileobj(gpt_disk, output)
        output.seek(0)
        yield output


@pytest.fixture(scope='session')
def mbr_disk(request, tmp_path_factory):
    tmp = tmp_path_factory.mktemp('mbr_disk')
    path = tmp / 'mbr.img'
    with path.open('wb') as output:
        make_disk(output, part_style='mbr')
    path.chmod(0o444)
    with path.open('rb') as output:
        yield output


@pytest.fixture()
def mbr_disk_w(request, tmp_path, mbr_disk):
    with (tmp_path / 'mbr-mutable.img').open('w+b') as output:
        mbr_disk.seek(0)
        copyfileobj(mbr_disk, output)
        output.seek(0)
        yield output


@pytest.fixture(scope='session')
def fat12_disk(request, tmp_path_factory):
    tmp = tmp_path_factory.mktemp('fat12_disk')
    path = tmp / 'fat12.img'
    with path.open('wb') as output:
        make_disk(output, part_style='mbr', fat_type='fat12')
    path.chmod(0o444)
    return path


@pytest.fixture(scope='session')
def fat12_disk_r(request, fat12_disk):
    with fat12_disk.open('rb') as output:
        yield output


@pytest.fixture()
def fat12_disk_w(request, tmp_path, fat12_disk_r):
    with (tmp_path / 'fat12-mutable.img').open('w+b') as output:
        fat12_disk_r.seek(0)
        copyfileobj(fat12_disk_r, output)
        output.seek(0)
        yield output


@pytest.fixture(scope='session')
def fat16_disk(request, tmp_path_factory):
    tmp = tmp_path_factory.mktemp('fat16_disk')
    path = tmp / 'fat16.img'
    with path.open('wb') as output:
        make_disk(output, part_style='mbr', fat_type='fat16')
    path.chmod(0o444)
    return path


@pytest.fixture(scope='session')
def fat16_disk_r(request, fat16_disk):
    with fat16_disk.open('rb') as output:
        yield output


@pytest.fixture()
def fat16_disk_w(request, tmp_path, fat16_disk_r):
    with (tmp_path / 'fat16-mutable.img').open('w+b') as output:
        fat16_disk_r.seek(0)
        copyfileobj(fat16_disk_r, output)
        output.seek(0)
        yield output


@pytest.fixture(scope='session')
def fat32_disk(request, tmp_path_factory):
    tmp = tmp_path_factory.mktemp('fat32_disk')
    path = tmp / 'fat32.img'
    with path.open('wb') as output:
        make_disk(output, part_style='gpt', fat_type='fat32')
    path.chmod(0o444)
    return path


@pytest.fixture(scope='session')
def fat32_disk_r(request, fat32_disk):
    with fat32_disk.open('rb') as output:
        yield output


@pytest.fixture()
def fat32_disk_w(request, tmp_path, fat32_disk_r):
    with (tmp_path / 'fat32-mutable.img').open('w+b') as output:
        fat32_disk_r.seek(0)
        copyfileobj(fat32_disk_r, output)
        output.seek(0)
        yield output


@pytest.fixture()
def fat_disks_r(request, fat12_disk_r, fat16_disk_r, fat32_disk_r):
    yield {
        'fat12': fat12_disk_r,
        'fat16': fat16_disk_r,
        'fat32': fat32_disk_r,
    }
