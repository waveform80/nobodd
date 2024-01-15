import mmap
from uuid import UUID
from pathlib import Path

import pytest

from nobodd.disk import *


def test_disk_init_file(gpt_disk):
    with DiskImage(gpt_disk) as disk:
        assert repr(disk) == (
            f"<DiskImage file={gpt_disk!r} style='gpt' "
            f"signature=UUID('733b49a8-6918-4e44-8d3d-47ed9b481335')>")


def test_disk_init_path(gpt_disk):
    with DiskImage(Path(gpt_disk.name)) as disk:
        assert repr(disk) == (
            f"<DiskImage file=<_io.BufferedReader name={gpt_disk.name!r}> "
            f"style='gpt' signature=UUID('733b49a8-6918-4e44-8d3d-47ed9b481335')>")


def test_disk_close_idempotency(gpt_disk):
    disk = DiskImage(gpt_disk)
    try:
        assert disk._map is not None
        disk.close()
        assert disk._map is None
    finally:
        disk.close()
        assert disk._map is None


def test_bad_disks_gpt(gpt_disk):
    m = mmap.mmap(gpt_disk.fileno(), 0, access=mmap.ACCESS_WRITE)
    h = GPTHeader.from_buffer(m, offset=512)
    # Corrupted signature
    m[512:512 + h._FORMAT.size] = bytes(h._replace(signature=b'EPICFART'))
    with DiskImage(gpt_disk) as disk:
        with pytest.raises(ValueError):
            disk.partitions
    # Unrecognized revision
    m[512:512 + h._FORMAT.size] = bytes(h._replace(revision=0x20000))
    with DiskImage(gpt_disk) as disk:
        with pytest.raises(ValueError):
            disk.partitions
    # Unrecognized header size
    m[512:512 + h._FORMAT.size] = bytes(h._replace(header_size=20))
    with DiskImage(gpt_disk) as disk:
        with pytest.raises(ValueError):
            disk.partitions
    # Bad CRC32
    m[512:512 + h._FORMAT.size] = bytes(h._replace(header_crc32=1))
    with DiskImage(gpt_disk) as disk:
        with pytest.raises(ValueError):
            disk.partitions


def test_bad_disks_mbr(mbr_disk):
    m = mmap.mmap(mbr_disk.fileno(), 0, access=mmap.ACCESS_WRITE)
    h = MBRHeader.from_buffer(m)
    # Corrupted boot signature
    m[:h._FORMAT.size] = bytes(h._replace(boot_sig=0xDEAD))
    with DiskImage(mbr_disk) as disk:
        with pytest.raises(ValueError):
            disk.partitions
    # Zero field isn't
    m[:h._FORMAT.size] = bytes(h._replace(zero=1))
    with DiskImage(mbr_disk) as disk:
        with pytest.raises(ValueError):
            disk.partitions
    p = MBRPartition.from_bytes(h.partition_3)
    offset = p.first_lba * 512
    h2 = MBRHeader.from_buffer(m, offset=offset)
    # Corrupted boot signature in EBR
    m[:h._FORMAT.size] = bytes(h)
    m[offset:offset + h2._FORMAT.size] = bytes(h2._replace(boot_sig=0xDEAD))
    with DiskImage(mbr_disk) as disk:
        with pytest.raises(ValueError):
            disk.partitions
    p2 = MBRPartition.from_bytes(h2.partition_2)
    # Partition type of second partition of EBR isn't terminal or another EBR
    m[offset:offset + h2._FORMAT.size] = bytes(
        h2._replace(partition_2=bytes(p2._replace(part_type=1))))
    with DiskImage(mbr_disk) as disk:
        with pytest.raises(ValueError):
            disk.partitions
    # Two EBRs in primary
    m[offset:offset + h2._FORMAT.size] = bytes(h2)
    m[:h._FORMAT.size] = bytes(h._replace(partition_4=h.partition_3))
    with DiskImage(mbr_disk) as disk:
        with pytest.warns(UserWarning):
            disk.partitions


def test_disk_gpt_attr(gpt_disk):
    with DiskImage(gpt_disk) as disk:
        assert disk.style == 'gpt'
        assert disk.signature == UUID('733b49a8-6918-4e44-8d3d-47ed9b481335')
        assert len(disk.partitions) == 4


def test_disk_mbr_attr(mbr_disk):
    with DiskImage(mbr_disk) as disk:
        assert disk.style == 'mbr'
        assert disk.signature == 0x3b1190bc
        assert len(disk.partitions) == 4


def test_disk_gpt_partition_attr(gpt_disk):
    with DiskImage(gpt_disk) as disk:
        with disk.partitions[1] as part:
            assert repr(part) == (
                f"<DiskPartition size={8 * 1024 * 1024} label='big-part' "
                f"type=UUID('ebd0a0a2-b9e5-4433-87c0-68b6b72699c7')>")
            assert part.type == UUID('EBD0A0A2-B9E5-4433-87C0-68B6B72699C7')
            assert part.label == 'big-part'
            assert len(part.data) == 8 * 1024 * 1024


def test_disk_mbr_partition_attr(mbr_disk):
    with DiskImage(mbr_disk) as disk:
        with disk.partitions[2] as part:
            assert repr(part) == (
                f"<DiskPartition size=205312 label='Partition 2' type=12>")
            assert part.type == 12
            assert part.label == 'Partition 2'
            assert len(part.data) == 205312


def test_disk_partitions_repr(gpt_disk):
    with DiskImage(gpt_disk) as disk:
        assert repr(disk.partitions) == (
            'DiskPartitionsGPT({\n'
            "1: <DiskPartition size=8388608 label='big-part' type=UUID('ebd0a0a2-b9e5-4433-87c0-68b6b72699c7')>,\n"
            "2: <DiskPartition size=204800 label='little-part1' type=UUID('ebd0a0a2-b9e5-4433-87c0-68b6b72699c7')>,\n"
            "5: <DiskPartition size=4194304 label='medium-part' type=UUID('ebd0a0a2-b9e5-4433-87c0-68b6b72699c7')>,\n"
            "6: <DiskPartition size=204800 label='little-part2' type=UUID('ebd0a0a2-b9e5-4433-87c0-68b6b72699c7')>,\n"
            '})')


def test_disk_partitions_get_gpt(gpt_disk):
    with DiskImage(gpt_disk) as disk:
        with pytest.raises(KeyError):
            disk.partitions[0]
        with pytest.raises(KeyError):
            disk.partitions[10]
        assert disk.partitions.keys() == {1, 2, 5, 6}


def test_disk_partitions_get_mbr(mbr_disk):
    with DiskImage(mbr_disk) as disk:
        with pytest.raises(KeyError):
            disk.partitions[0]
        with pytest.raises(KeyError):
            disk.partitions[10]
        assert disk.partitions.keys() == {1, 2, 5, 6}
