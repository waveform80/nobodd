import gzip
from shutil import copyfileobj

import pytest


def make_disk(output, part_style='mbr', part_num=1, fat_type='fat16'):
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


@pytest.fixture()
def gpt_disk(request, tmp_path):
    with (tmp_path / 'gpt.img').open('w+b') as output:
        make_disk(output, 'gpt')
        yield output


@pytest.fixture()
def mbr_disk(request, tmp_path):
    with (tmp_path / 'mbr.img').open('w+b') as output:
        make_disk(output, 'mbr')
        yield output