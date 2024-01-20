import pytest

from nobodd.disk import DiskImage
from nobodd.fat import *


def test_bpb_from_buffer(mbr_disk):
    with DiskImage(mbr_disk) as img:
        bpb = BIOSParameterBlock.from_buffer(img.partitions[1].data)
        assert bpb.oem_name == b'mkfs.fat'
        assert bpb.bytes_per_sector == 512
        assert bpb.sectors_per_cluster == 1
        assert bpb.fat_count == 2
        assert bpb.max_root_entries == 64
        assert bpb.fat16_total_sectors == 8192
        assert bpb.sectors_per_fat == 32
        assert bpb.hidden_sectors == 0


def test_bpb_from_bytes(mbr_disk):
    with DiskImage(mbr_disk) as img:
        bpb1 = BIOSParameterBlock.from_buffer(img.partitions[1].data)
        bpb2 = BIOSParameterBlock.from_bytes(
            bytes(img.partitions[1].data[:BIOSParameterBlock._FORMAT.size]))
        assert bpb1 == bpb2


def test_bpb_to_bytes(mbr_disk):
    with DiskImage(mbr_disk) as img:
        bpb = BIOSParameterBlock.from_buffer(img.partitions[1].data)
        assert img.partitions[1].data[:BIOSParameterBlock._FORMAT.size] == bytes(bpb)


def test_ebpb_from_buffer(mbr_disk):
    with DiskImage(mbr_disk) as img:
        ebpb = ExtendedBIOSParameterBlock.from_buffer(
            img.partitions[1].data, offset=BIOSParameterBlock._FORMAT.size)
        assert ebpb.extended_boot_sig in (0x28, 0x29)
        assert ebpb.volume_label == b'NOBODD---16'
        assert ebpb.file_system == b'FAT16   '


def test_ebpb_from_bytes(mbr_disk):
    with DiskImage(mbr_disk) as img:
        ebpb1 = ExtendedBIOSParameterBlock.from_buffer(
            img.partitions[1].data, offset=BIOSParameterBlock._FORMAT.size)
        ebpb2 = ExtendedBIOSParameterBlock.from_bytes(
            img.partitions[1].data[
                BIOSParameterBlock._FORMAT.size:
                BIOSParameterBlock._FORMAT.size +
                ExtendedBIOSParameterBlock._FORMAT.size])
        assert ebpb1 == ebpb2


def test_ebpb_to_bytes(mbr_disk):
    with DiskImage(mbr_disk) as img:
        ebpb = ExtendedBIOSParameterBlock.from_buffer(
            img.partitions[1].data, offset=BIOSParameterBlock._FORMAT.size)
        assert img.partitions[1].data[
            BIOSParameterBlock._FORMAT.size:
            BIOSParameterBlock._FORMAT.size +
            ExtendedBIOSParameterBlock._FORMAT.size] == bytes(ebpb)


def test_fat32bpb_from_buffer(fat32_disk):
    with DiskImage(fat32_disk) as img:
        f32bpb = FAT32BIOSParameterBlock.from_buffer(
            img.partitions[1].data, offset=BIOSParameterBlock._FORMAT.size)
        assert f32bpb.sectors_per_fat == 126
        assert f32bpb.version == 0
        assert f32bpb.root_dir_cluster != 0
        assert f32bpb.info_sector == 1
        assert f32bpb.backup_sector == 6


def test_fat32bpb_from_bytes(fat32_disk):
    with DiskImage(fat32_disk) as img:
        f32bpb1 = FAT32BIOSParameterBlock.from_buffer(
            img.partitions[1].data, offset=BIOSParameterBlock._FORMAT.size)
        f32bpb2 = FAT32BIOSParameterBlock.from_bytes(
            img.partitions[1].data[
                BIOSParameterBlock._FORMAT.size:
                BIOSParameterBlock._FORMAT.size +
                FAT32BIOSParameterBlock._FORMAT.size])
        assert f32bpb1 == f32bpb2


def test_fat32bpb_to_bytes(fat32_disk):
    with DiskImage(fat32_disk) as img:
        f32bpb = FAT32BIOSParameterBlock.from_buffer(
            img.partitions[1].data, offset=BIOSParameterBlock._FORMAT.size)
        assert img.partitions[1].data[
            BIOSParameterBlock._FORMAT.size:
            BIOSParameterBlock._FORMAT.size +
            FAT32BIOSParameterBlock._FORMAT.size] == bytes(f32bpb)


def test_fat32info_from_buffer(fat32_disk):
    with DiskImage(fat32_disk) as img:
        f32bpb = FAT32BIOSParameterBlock.from_buffer(
            img.partitions[1].data, offset=BIOSParameterBlock._FORMAT.size)
        f32info = FAT32InfoSector.from_buffer(
            img.partitions[1].data, offset=f32bpb.info_sector * 512)
        assert f32info.sig1 == b'RRaA'
        assert f32info.sig2 == b'rrAa'
        assert f32info.sig3 == b'\0\0\x55\xAA'


def test_fat32info_from_bytes(fat32_disk):
    with DiskImage(fat32_disk) as img:
        f32bpb = FAT32BIOSParameterBlock.from_buffer(
            img.partitions[1].data, offset=BIOSParameterBlock._FORMAT.size)
        f32info1 = FAT32InfoSector.from_buffer(
            img.partitions[1].data, offset=f32bpb.info_sector * 512)
        f32info2 = FAT32InfoSector.from_bytes(
            img.partitions[1].data[
                f32bpb.info_sector * 512:
                f32bpb.info_sector * 512 + FAT32InfoSector._FORMAT.size])
        assert f32info1 == f32info2


def test_fat32info_to_bytes(fat32_disk):
    with DiskImage(fat32_disk) as img:
        f32bpb = FAT32BIOSParameterBlock.from_buffer(
            img.partitions[1].data, offset=BIOSParameterBlock._FORMAT.size)
        f32info = FAT32InfoSector.from_buffer(
            img.partitions[1].data, offset=f32bpb.info_sector * 512)
        assert img.partitions[1].data[
            f32bpb.info_sector * 512:
            f32bpb.info_sector * 512 + FAT32InfoSector._FORMAT.size] == bytes(f32info)


def test_fat32info_to_buffer(fat32_disk):
    with DiskImage(fat32_disk) as img:
        f32bpb = FAT32BIOSParameterBlock.from_buffer(
            img.partitions[1].data, offset=BIOSParameterBlock._FORMAT.size)
        f32info = FAT32InfoSector.from_buffer(
            img.partitions[1].data, offset=f32bpb.info_sector * 512)
        buf1 = bytes(img.partitions[1].data[
            f32bpb.info_sector * 512:
            f32bpb.info_sector * 512 + FAT32InfoSector._FORMAT.size])
        buf2 = bytearray(len(buf1))
        f32info.to_buffer(buf2)
        assert buf1 == buf2


def test_direntry_from_buffer(gpt_disk):
    with DiskImage(gpt_disk) as img:
        bpb = BIOSParameterBlock.from_buffer(img.partitions[1].data)
        offset = (
            bpb.reserved_sectors + (bpb.sectors_per_fat * bpb.fat_count)
        ) * bpb.bytes_per_sector
        # First root entry is the volume ID
        volid = DirectoryEntry.from_buffer(img.partitions[1].data, offset)
        assert volid.filename + volid.ext == b'NOBODD---16'
        assert volid.attr == 8
        assert volid.attr2 == 0
        assert volid.first_cluster_lo == 0
        assert volid.first_cluster_hi == 0
        assert volid.size == 0


def test_direntry_from_bytes(gpt_disk):
    with DiskImage(gpt_disk) as img:
        bpb = BIOSParameterBlock.from_buffer(img.partitions[1].data)
        offset = (
            bpb.reserved_sectors + (bpb.sectors_per_fat * bpb.fat_count)
        ) * bpb.bytes_per_sector
        dirent1 = DirectoryEntry.from_buffer(img.partitions[1].data, offset)
        dirent2 = DirectoryEntry.from_bytes(
            img.partitions[1].data[offset:offset + DirectoryEntry._FORMAT.size])
        assert dirent1 == dirent2


def test_direntry_to_bytes(gpt_disk):
    with DiskImage(gpt_disk) as img:
        bpb = BIOSParameterBlock.from_buffer(img.partitions[1].data)
        offset = (
            bpb.reserved_sectors + (bpb.sectors_per_fat * bpb.fat_count)
        ) * bpb.bytes_per_sector
        dirent = DirectoryEntry.from_buffer(img.partitions[1].data, offset)
        assert img.partitions[1].data[
            offset:offset + DirectoryEntry._FORMAT.size] == bytes(dirent)


def test_direntry_to_buffer(gpt_disk):
    with DiskImage(gpt_disk) as img:
        bpb = BIOSParameterBlock.from_buffer(img.partitions[1].data)
        offset = (
            bpb.reserved_sectors + (bpb.sectors_per_fat * bpb.fat_count)
        ) * bpb.bytes_per_sector
        dirent = DirectoryEntry.from_buffer(img.partitions[1].data, offset)
        buf1 = bytes(img.partitions[1].data[
            offset:offset + DirectoryEntry._FORMAT.size])
        buf2 = bytearray(len(buf1))
        dirent.to_buffer(buf2)
        assert buf1 == buf2


def test_direntry_eof():
    # These are the only things that really matter in an EOF dir entry
    assert DirectoryEntry.eof().filename[0] == 0
    assert DirectoryEntry.eof().attr == 0


def test_direntry_iter(gpt_disk):
    with DiskImage(gpt_disk) as img:
        bpb = BIOSParameterBlock.from_buffer(img.partitions[1].data)
        offset = (
            bpb.reserved_sectors + (bpb.sectors_per_fat * bpb.fat_count)
        ) * bpb.bytes_per_sector
        entries = list(DirectoryEntry.iter_over(img.partitions[1].data[
            offset:offset + bpb.max_root_entries *
            DirectoryEntry._FORMAT.size
        ]))
        assert len(entries) == bpb.max_root_entries
        print(repr(entries))
        assert entries[0].filename + entries[0].ext == b'NOBODD---16'
        assert entries[0].attr == 8
