import pytest

from nobodd.disk import DiskImage
from nobodd.fat import *


def root_offset(part):
    # Only for FAT-12/16 where this is in a fixed location
    bpb = BIOSParameterBlock.from_buffer(part)
    return (
        bpb.reserved_sectors + (bpb.sectors_per_fat * bpb.fat_count)
    ) * bpb.bytes_per_sector


def root_dir(part):
    bpb = BIOSParameterBlock.from_buffer(part)
    offset = root_offset(part)
    return part[offset:offset + bpb.max_root_entries * DirectoryEntry._FORMAT.size]


def first_lfn_offset(part):
    offset = root_offset(part)
    with root_dir(part) as mem:
        for entry in DirectoryEntry.iter_over(mem):
            if entry.attr == 0xF:
                return offset
            offset += DirectoryEntry._FORMAT.size


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


def test_bpb_to_buffer(mbr_disk):
    with DiskImage(mbr_disk) as img:
        bpb = BIOSParameterBlock.from_buffer(img.partitions[1].data)
        buf1 = bytes(bpb)
        buf2 = bytearray(len(buf1))
        bpb.to_buffer(buf2)
        assert buf1 == buf2


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


def test_ebpb_to_buffer(mbr_disk):
    with DiskImage(mbr_disk) as img:
        ebpb = ExtendedBIOSParameterBlock.from_buffer(
            img.partitions[1].data, offset=BIOSParameterBlock._FORMAT.size)
        buf1 = bytes(ebpb)
        buf2 = bytearray(len(buf1))
        ebpb.to_buffer(buf2)
        assert buf1 == buf2


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


def test_fat32bpb_to_buffer(fat32_disk):
    with DiskImage(fat32_disk) as img:
        f32bpb = FAT32BIOSParameterBlock.from_buffer(
            img.partitions[1].data, offset=BIOSParameterBlock._FORMAT.size)
        buf1 = bytes(f32bpb)
        buf2 = bytearray(len(buf1))
        f32bpb.to_buffer(buf2)
        assert buf1 == buf2


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
        offset = root_offset(img.partitions[1].data)
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
        offset = root_offset(img.partitions[1].data)
        dirent1 = DirectoryEntry.from_buffer(img.partitions[1].data, offset)
        dirent2 = DirectoryEntry.from_bytes(
            img.partitions[1].data[offset:offset + DirectoryEntry._FORMAT.size])
        assert dirent1 == dirent2


def test_direntry_to_bytes(gpt_disk):
    with DiskImage(gpt_disk) as img:
        offset = root_offset(img.partitions[1].data)
        dirent = DirectoryEntry.from_buffer(img.partitions[1].data, offset)
        assert img.partitions[1].data[
            offset:offset + DirectoryEntry._FORMAT.size] == bytes(dirent)


def test_direntry_to_buffer(gpt_disk):
    with DiskImage(gpt_disk) as img:
        offset = root_offset(img.partitions[1].data)
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
        with root_dir(img.partitions[1].data) as dir_mem:
            entries = list(DirectoryEntry.iter_over(dir_mem))
        assert len(entries) == bpb.max_root_entries
        assert entries[0].filename + entries[0].ext == b'NOBODD---16'
        assert entries[0].attr == 8


def test_lfnentry_from_buffer(gpt_disk):
    with DiskImage(gpt_disk) as img:
        lfn = LongFilenameEntry.from_buffer(
            img.partitions[1].data,
            offset=first_lfn_offset(img.partitions[1].data))
        assert lfn.sequence == 0x41 # terminal, part 1
        assert (lfn.name_1 + lfn.name_2 + lfn.name_3).decode('utf-16le') == 'lots-of-zeros'


def test_lfnentry_from_bytes(gpt_disk):
    with DiskImage(gpt_disk) as img:
        offset = first_lfn_offset(img.partitions[1].data)
        lfn = LongFilenameEntry.from_bytes(
            img.partitions[1].data[offset:offset + LongFilenameEntry._FORMAT.size])
        assert lfn.sequence == 0x41 # terminal, part 1
        assert (lfn.name_1 + lfn.name_2 + lfn.name_3).decode('utf-16le') == 'lots-of-zeros'


def test_lfnentry_to_bytes(gpt_disk):
    with DiskImage(gpt_disk) as img:
        offset = first_lfn_offset(img.partitions[1].data)
        lfn = LongFilenameEntry.from_buffer(img.partitions[1].data, offset=offset)
        assert img.partitions[1].data[
            offset:offset + LongFilenameEntry._FORMAT.size] == bytes(lfn)


def test_lfnentry_to_buffer(gpt_disk):
    with DiskImage(gpt_disk) as img:
        lfn = LongFilenameEntry.from_buffer(
            img.partitions[1].data,
            offset=first_lfn_offset(img.partitions[1].data))
        buf1 = bytes(lfn)
        buf2 = bytearray(len(buf1))
        lfn.to_buffer(buf2)
        assert buf1 == buf2


def test_lfnentry_iter(gpt_disk):
    with DiskImage(gpt_disk) as img:
        bpb = BIOSParameterBlock.from_buffer(img.partitions[1].data)
        with root_dir(img.partitions[1].data) as dir_mem:
            entries = list(LongFilenameEntry.iter_over(dir_mem))
        assert len(entries) == bpb.max_root_entries
        assert any(entry.attr == 0xF for entry in entries)


def test_lfn_checksum():
    assert lfn_checksum(b'        ', b'   ') == 247
    assert lfn_checksum(b'FOO     ', b'BAR') == 83


def test_lfn_valid():
    assert lfn_valid('foo.bar baz')
    assert lfn_valid('123 föo')
    assert not lfn_valid('')
    assert not lfn_valid('foo*')


def test_sfn_valid():
    assert sfn_valid(b'FOOBAR')
    assert sfn_valid(b'FOO 123')
    assert not sfn_valid(b'')
    assert not sfn_valid(b'  FOO BAR  ')


def test_sfn_safe():
    assert sfn_safe(b'FOO BAR') == b'FOOBAR'
    assert sfn_safe(b'FOO [BAR]', b'_') == b'FOO_BAR_'
    assert sfn_safe(b'FOO [BAR]', b'?') == b'FOO?BAR?'
