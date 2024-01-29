import io
import mmap
import errno
import struct

import pytest

from nobodd.fat import (
    BIOSParameterBlock,
    ExtendedBIOSParameterBlock,
    lfn_valid,
    lfn_checksum,
)
from nobodd.disk import DiskImage
from nobodd.fs import *


@pytest.fixture(params=(False, True))
def with_fsinfo(request, fat32_disk):
    with DiskImage(fat32_disk, access=mmap.ACCESS_WRITE) as img:
        with img.partitions[1].data as part:
            bpb = BIOSParameterBlock.from_buffer(part)
            f32bpb = FAT32BIOSParameterBlock.from_buffer(
                part, offset=BIOSParameterBlock._FORMAT.size)
            info_offset = (
                f32bpb.info_sector * bpb.bytes_per_sector)
            info = FAT32InfoSector.from_buffer(part, offset=info_offset)
            if not request.param:
                info._replace(sig1=b'EPIC', sig2=b'FAIL').to_buffer(
                    part, offset=info_offset)
    yield request.param


def dir_eof(fat_dir):
    for offset, entries in fat_dir._group_entries():
        pass
    return offset + DirectoryEntry._FORMAT.size


def first_dir(fat_dir):
    for offset, entries in fat_dir._group_entries():
        if entries[-1].attr & 0x10:
            return offset, entries
    assert False, 'failed to find dir'


def find_lfn_file(fat_dir):
    for offset, entries in fat_dir._group_entries():
        if len(entries) > 1 and not entries[-1].attr & 0x10:
            return offset, entries
    assert False, 'failed to find file with LFN'


def find_non_lfn_file(fat_dir):
    for offset, entries in fat_dir._group_entries():
        if len(entries) == 1 and not entries[-1].attr & 0x10:
            return offset, entries
    assert False, 'failed to find file without LFN'


def find_empty_file(fat_dir):
    for offset, entries in fat_dir._group_entries():
        if entries[-1].size == 0 and not entries[-1].attr & 0x10:
            return offset, entries
    assert False, 'failed to find non-empty file'


def find_non_empty_file(fat_dir):
    for offset, entries in fat_dir._group_entries():
        if entries[-1].size > 0:
            return offset, entries
    assert False, 'failed to find non-empty file'


def test_fs_init(fat12_disk, fat16_disk, fat32_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            assert fs.fat_type == 'fat12'
            assert fs.label == 'NOBODD---12'
            assert fs.sfn_encoding == 'iso-8859-1'
            assert not fs.atime
    with DiskImage(fat16_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            assert fs.fat_type == 'fat16'
            assert fs.label == 'NOBODD---16'
            assert fs.sfn_encoding == 'iso-8859-1'
            assert not fs.atime
    with DiskImage(fat32_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            assert fs.fat_type == 'fat32'
            assert fs.label == 'NOBODD---32'
            assert fs.sfn_encoding == 'iso-8859-1'
            assert not fs.atime


def test_fs_init_bad(fat16_disk):
    # The bad/dirty flags are present on FAT16/32 only, hence using the larger
    # disk image here
    with DiskImage(fat16_disk, access=mmap.ACCESS_WRITE) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            fs.fat[1] = 0x7FFF
        with pytest.warns(DirtyFileSystem):
            with FatFileSystem(img.partitions[1].data) as fs:
                fs.fat[1] = 0xBFFF
        with pytest.warns(DamagedFileSystem):
            with FatFileSystem(img.partitions[1].data) as fs:
                pass


def test_ambiguous_headers_fat12(fat12_disk):
    with DiskImage(fat12_disk, access=mmap.ACCESS_COPY) as img:
        with img.partitions[1].data as part:
            ebpb = ExtendedBIOSParameterBlock.from_buffer(
                part, offset=BIOSParameterBlock._FORMAT.size)
            # It's FAT Jim, but not as we know it ...
            ebpb._replace(file_system=b'FAT     ').to_buffer(
                part, offset=BIOSParameterBlock._FORMAT.size)
        with FatFileSystem(img.partitions[1].data) as fs:
            assert fs.fat_type == 'fat12'


def test_ambiguous_headers_fat32(fat32_disk):
    with DiskImage(fat32_disk, access=mmap.ACCESS_COPY) as img:
        with img.partitions[1].data as part:
            bpb = BIOSParameterBlock.from_buffer(part)
            f32bpb = FAT32BIOSParameterBlock.from_buffer(
                part, offset=BIOSParameterBlock._FORMAT.size)
            ebpb = ExtendedBIOSParameterBlock.from_buffer(
                part, offset=BIOSParameterBlock._FORMAT.size +
                FAT32BIOSParameterBlock._FORMAT.size)
            # Pretend we've got a normal number of sectors for FAT32 (the test
            # image is deliberately undersized for efficiency), and that the
            # file-system label is ambiguous
            bpb._replace(
                fat16_total_sectors=0,
                fat32_total_sectors=128000).to_buffer(part)
            ebpb._replace(file_system=b'FAT     ').to_buffer(
                part, offset=BIOSParameterBlock._FORMAT.size +
                FAT32BIOSParameterBlock._FORMAT.size)
        with FatFileSystem(img.partitions[1].data) as fs:
            assert fs.fat_type == 'fat32'


def test_ambiguous_headers_huge_fat32(fat32_disk):
    with DiskImage(fat32_disk, access=mmap.ACCESS_COPY) as img:
        with img.partitions[1].data as part:
            bpb = BIOSParameterBlock.from_buffer(part)
            f32bpb = FAT32BIOSParameterBlock.from_buffer(
                part, offset=BIOSParameterBlock._FORMAT.size)
            ebpb = ExtendedBIOSParameterBlock.from_buffer(
                part, offset=BIOSParameterBlock._FORMAT.size +
                FAT32BIOSParameterBlock._FORMAT.size)
            # Pretend we've got a normal number of sectors for FAT32 (the test
            # image is deliberately undersized for efficiency), and that the
            # file-system label is ambiguous
            bpb._replace(
                fat16_total_sectors=0,
                fat32_total_sectors=0).to_buffer(part)
            ebpb._replace(file_system=struct.pack('<Q', 8000000000)).to_buffer(
                part, offset=BIOSParameterBlock._FORMAT.size +
                FAT32BIOSParameterBlock._FORMAT.size)
        with FatFileSystem(img.partitions[1].data) as fs:
            assert fs.fat_type == 'fat32'


def test_bad_headers(fat16_disk, fat32_disk):
    # Claims to be FAT32, but lacks the FAT32-specific BPB
    with DiskImage(fat16_disk, access=mmap.ACCESS_COPY) as img:
        with img.partitions[1].data as part:
            ebpb = ExtendedBIOSParameterBlock.from_buffer(
                part, offset=BIOSParameterBlock._FORMAT.size)
            ebpb._replace(file_system = b'FAT32   ').to_buffer(
                part, offset=BIOSParameterBlock._FORMAT.size)
        with pytest.raises(ValueError):
            FatFileSystem(img.partitions[1].data)

    # Claims to be FAT16 but has 0 root entries (like FAT32)
    with DiskImage(fat16_disk, access=mmap.ACCESS_COPY) as img:
        with img.partitions[1].data as part:
            bpb = BIOSParameterBlock.from_buffer(part)
            bpb._replace(max_root_entries=0).to_buffer(part)
        with pytest.raises(ValueError):
            FatFileSystem(img.partitions[1].data)

    # Claims to be FAT32, but has non-zero root entries (like FAT12/16)
    with DiskImage(fat32_disk, access=mmap.ACCESS_COPY) as img:
        with img.partitions[1].data as part:
            bpb = BIOSParameterBlock.from_buffer(part)
            bpb._replace(max_root_entries=64).to_buffer(part)
        with pytest.raises(ValueError):
            FatFileSystem(img.partitions[1].data)

    # Has zero sectors per FAT
    with DiskImage(fat16_disk, access=mmap.ACCESS_COPY) as img:
        with img.partitions[1].data as part:
            bpb = BIOSParameterBlock.from_buffer(part)
            bpb._replace(sectors_per_fat=0).to_buffer(part)
        with pytest.raises(ValueError):
            FatFileSystem(img.partitions[1].data)

    # Root directory doesn't fill a sector
    with DiskImage(fat16_disk, access=mmap.ACCESS_COPY) as img:
        with img.partitions[1].data as part:
            bpb = BIOSParameterBlock.from_buffer(part)
            bpb._replace(max_root_entries=bpb.max_root_entries - 1).to_buffer(part)
        with pytest.raises(ValueError):
            FatFileSystem(img.partitions[1].data)

    # No fs-label, and extended boot sigs are corrupt
    with DiskImage(fat16_disk, access=mmap.ACCESS_COPY) as img:
        with img.partitions[1].data as part:
            ebpb = ExtendedBIOSParameterBlock.from_buffer(
                part, offset=BIOSParameterBlock._FORMAT.size)
            ebpb._replace(
                file_system = b'EPICFAIL',
                extended_boot_sig=0).to_buffer(
                    part, offset=BIOSParameterBlock._FORMAT.size)
        with pytest.raises(ValueError):
            FatFileSystem(img.partitions[1].data)


def test_fs_repr(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            assert repr(fs) == "<FatFileSystem label='NOBODD---12' fat_type='fat12'>"


def test_fs_close_idempotent(fat12_disk):
    with DiskImage(fat12_disk) as img:
        fs = FatFileSystem(img.partitions[1].data)
        fs.close()
        fs.close()
        assert fs._fat is None
        assert fs._data is None
        assert fs._root is None


def test_fs_readonly(fat12_disk):
    with DiskImage(fat12_disk, access=mmap.ACCESS_READ) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            assert fs.readonly
    with DiskImage(fat12_disk, access=mmap.ACCESS_COPY) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            assert not fs.readonly


def test_fs_opendir(fat12_disk, fat16_disk, fat32_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            assert isinstance(fs.open_dir(0), FatDirectory)
    with DiskImage(fat16_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            assert isinstance(fs.open_dir(0), FatDirectory)
    with DiskImage(fat32_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            assert isinstance(fs.open_dir(0), FatDirectory)
    with DiskImage(fat32_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            # Cheating by using the root-dir cluster as a sub-directory
            assert isinstance(fs.open_dir(fs._root), FatSubDirectory)


def test_fs_open_file(fat32_disk):
    with DiskImage(fat32_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            # In FAT32, the root-dir is a sub-directory; opening the root
            # cluster as a file gets us the "file" underlying the root dir
            with fs.open_file(fs._root) as f:
                assert isinstance(f, FatFile)


def test_fs_open_entry(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            index = fs.open_dir(0)
            for entry in index.values():
                if entry.attr == 0x20:  # archive bit only
                    with fs.open_entry(index, entry) as f:
                        assert isinstance(f, FatFile)
                    break
            else:
                assert False, 'No file entries found in root'


def test_fs_root(fat12_disk, fat16_disk, fat32_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            assert isinstance(fs.root, FatPath)
    with DiskImage(fat16_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            assert isinstance(fs.root, FatPath)
    with DiskImage(fat32_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            assert isinstance(fs.root, FatPath)


def test_fattable_close_idempotent(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            with fs._fat as tab:
                assert len(tab._tables) == 2
            assert not fs._fat._tables
            fs._fat.close()
            assert not fs._fat._tables


def test_fattable_free(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            for cluster in fs._fat.free():
                assert cluster > 1
                break
            with pytest.raises(OSError) as err:
                for cluster in fs._fat.free():
                    pass
            assert err.value.errno == errno.ENOSPC


def test_fattable_free_fat32(fat32_disk, with_fsinfo):
    with DiskImage(fat32_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            for cluster in fs._fat.free():
                assert cluster > 1
                break
            with pytest.raises(OSError) as err:
                for cluster in fs._fat.free():
                    pass
            assert err.value.errno == errno.ENOSPC


def test_fattable_free_fat32_bad_last_alloc(fat32_disk):
    # When FSINFO's last_alloc is invalid, test we just fall back to scanning
    # sequentially
    with DiskImage(fat32_disk, access=mmap.ACCESS_COPY) as img:
        with img.partitions[1].data as part:
            bpb = BIOSParameterBlock.from_buffer(part)
            f32bpb = FAT32BIOSParameterBlock.from_buffer(
                part, offset=BIOSParameterBlock._FORMAT.size)
            info_offset = (
                f32bpb.info_sector * bpb.bytes_per_sector)
            info = FAT32InfoSector.from_buffer(part, offset=info_offset)
            info._replace(last_alloc=0).to_buffer(part, offset=info_offset)
        with FatFileSystem(img.partitions[1].data) as fs:
            for cluster in fs._fat.free():
                assert cluster > 1
                break
            with pytest.raises(OSError) as err:
                for cluster in fs._fat.free():
                    pass
            assert err.value.errno == errno.ENOSPC

    # When FSINFO's last_alloc+1 is allocated, test we skip it (this isn't
    # really "bad", more inconvenient)
    with DiskImage(fat32_disk, access=mmap.ACCESS_WRITE) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            info = fs._fat._info
            fs._fat._info = None
            fs.fat.mark_end(info.last_alloc + 1)
        with FatFileSystem(img.partitions[1].data) as fs:
            for cluster in fs._fat.free():
                assert cluster > info.last_alloc + 1
                break


def test_fattable_free_too_large():
    # FAT table can exceed max_valid clusters for the purposes of filling a
    # sector; this ensures we do not yield clusters out of range
    fat_table = bytearray(6144)
    fat_table[:6114] = b'\xFF' * 6114
    with Fat12Table(memoryview(fat_table), len(fat_table)) as tbl:
        with pytest.raises(OSError) as err:
            for cluster in tbl.free():
                assert tbl.min_valid <= cluster <= tbl.max_valid
        assert err.value.errno == errno.ENOSPC


def test_fat12table_sequence(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with img.partitions[1].data as part:
            bpb = BIOSParameterBlock.from_buffer(part)
        with FatFileSystem(img.partitions[1].data) as fs:
            assert fs._fat.readonly == fs.readonly
            assert len(fs._fat) == (
                bpb.sectors_per_fat * bpb.bytes_per_sector // 1.5)
            assert fs._fat[0] > fs._fat.max_valid
            assert fs._fat[1] > fs._fat.max_valid
            first = fs._fat[0]
            second = fs._fat[1]
            assert all(c == first for c in fs._fat.get_all(0))
            assert all(c == second for c in fs._fat.get_all(1))
            with pytest.raises(TypeError):
                del fs._fat[0]
            with pytest.raises(TypeError):
                fs._fat.insert(0, 0)
            with pytest.raises(IndexError):
                fs._fat[4000000000]
            with pytest.raises(IndexError):
                fs._fat.get_all(4000000000)


def test_fat12table_mutate(fat12_disk):
    with DiskImage(fat12_disk, access=mmap.ACCESS_COPY) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            # Given FAT-12 crosses three-bytes for every two values, it's
            # important to check adjacent values aren't affected by mutation
            save2 = fs._fat[2]
            save3 = fs._fat[3]
            fs._fat[2] = 3
            assert fs._fat[2] == 3
            assert fs._fat[3] == save3
            fs._fat.mark_end(3)
            assert fs._fat[2] == 3
            assert fs._fat[3] == fs._fat.end_mark
            fs._fat.mark_free(2)
            assert fs._fat[2] == 0
            assert fs._fat[3] == fs._fat.end_mark
            assert fs._fat.get_all(2) == (0, 0)
            assert fs._fat.get_all(3) == (fs._fat.end_mark, fs._fat.end_mark)
            with pytest.raises(ValueError):
                fs._fat[0] = 0xFFFF
            with pytest.raises(IndexError):
                fs._fat[4000000000] = 2


def test_fat16table_sequence(fat16_disk):
    with DiskImage(fat16_disk) as img:
        with img.partitions[1].data as part:
            bpb = BIOSParameterBlock.from_buffer(part)
        with FatFileSystem(img.partitions[1].data) as fs:
            assert fs._fat.readonly == fs.readonly
            assert len(fs._fat) == (
                bpb.sectors_per_fat * bpb.bytes_per_sector // 2)
            assert fs._fat[0] > fs._fat.max_valid
            assert fs._fat[1] > fs._fat.max_valid
            first = fs._fat[0]
            second = fs._fat[1]
            assert all(c == first for c in fs._fat.get_all(0))
            assert all(c == second for c in fs._fat.get_all(1))
            with pytest.raises(TypeError):
                del fs._fat[0]
            with pytest.raises(TypeError):
                fs._fat.insert(0, 0)
            with pytest.raises(IndexError):
                fs._fat[4000000000]
            with pytest.raises(IndexError):
                fs._fat.get_all(4000000000)


def test_fat16table_mutate(fat16_disk):
    with DiskImage(fat16_disk, access=mmap.ACCESS_COPY) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            fs._fat[2] = 3
            assert fs._fat[2] == 3
            fs._fat.mark_end(3)
            assert fs._fat[3] == fs._fat.end_mark
            fs._fat.mark_free(2)
            assert fs._fat[2] == 0
            assert fs._fat.get_all(2) == (0, 0)
            assert fs._fat.get_all(3) == (fs._fat.end_mark, fs._fat.end_mark)
            with pytest.raises(ValueError):
                fs._fat[0] = 0xFFFFFF
            with pytest.raises(IndexError):
                fs._fat[4000000000] = 2


def test_fat32table_sequence(fat32_disk, with_fsinfo):
    with DiskImage(fat32_disk) as img:
        with img.partitions[1].data as part:
            bpb = BIOSParameterBlock.from_buffer(part)
            f32bpb = FAT32BIOSParameterBlock.from_buffer(
                part, offset=BIOSParameterBlock._FORMAT.size)
        with FatFileSystem(img.partitions[1].data) as fs:
            assert fs._fat.readonly == fs.readonly
            assert len(fs._fat) == (
                f32bpb.sectors_per_fat * bpb.bytes_per_sector // 4)
            assert fs._fat[0] > fs._fat.max_valid
            assert fs._fat[1] > fs._fat.max_valid
            first = fs._fat[0]
            second = fs._fat[1]
            assert all(c == first for c in fs._fat.get_all(0))
            assert all(c == second for c in fs._fat.get_all(1))
            with pytest.raises(TypeError):
                del fs._fat[0]
            with pytest.raises(TypeError):
                fs._fat.insert(0, 0)
            with pytest.raises(IndexError):
                fs._fat[4000000000]
            with pytest.raises(IndexError):
                fs._fat.get_all(4000000000)


def test_fat32table_mutate(fat32_disk, with_fsinfo):
    with DiskImage(fat32_disk, access=mmap.ACCESS_COPY) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            fs._fat[2] = 3
            assert fs._fat[2] == 3
            fs._fat.mark_end(3)
            assert fs._fat[3] == fs._fat.end_mark
            if with_fsinfo:
                save_free = fs._fat._info.free_clusters
            fs._fat.mark_free(2)
            assert fs._fat[2] == 0
            if with_fsinfo:
                assert fs._fat._info.free_clusters == save_free + 1
            assert fs._fat.get_all(2) == (0, 0)
            assert fs._fat.get_all(3) == (fs._fat.end_mark, fs._fat.end_mark)
            # Have to be sure we both de-allocate and re-allocate a cluster to
            # test FAT32's info sector manipulation
            fs._fat[2] = 3
            assert fs._fat[2] == 3
            if with_fsinfo:
                assert fs._fat._info.free_clusters == save_free
                assert fs._fat._info.last_alloc == 2
            with pytest.raises(ValueError):
                fs._fat[0] = 0xFFFFFFFF
            with pytest.raises(IndexError):
                fs._fat[4000000000] = 2


def test_fat32table_alloc_bad(fat32_disk):
    # Ignore FSINFO block's free_clusters when allocating and it says there
    # are 0 free clusters left
    with DiskImage(fat32_disk, access=mmap.ACCESS_COPY) as img:
        with img.partitions[1].data as part:
            bpb = BIOSParameterBlock.from_buffer(part)
            f32bpb = FAT32BIOSParameterBlock.from_buffer(
                part, offset=BIOSParameterBlock._FORMAT.size)
            info_offset = (
                f32bpb.info_sector * bpb.bytes_per_sector)
            info = FAT32InfoSector.from_buffer(part, offset=info_offset)
            info._replace(free_clusters=0).to_buffer(part, offset=info_offset)
        with FatFileSystem(img.partitions[1].data) as fs:
            assert fs._fat._info.free_clusters == 0
            fs.fat.mark_end(next(fs.fat.free()))
            assert fs._fat._info.free_clusters == 0
    # ... and likewise when deallocating; ignore bad info that says
    # everything's free
    with DiskImage(fat32_disk, access=mmap.ACCESS_COPY) as img:
        with img.partitions[1].data as part, FatFileSystem(part) as fs:
            bpb = BIOSParameterBlock.from_buffer(part)
            f32bpb = FAT32BIOSParameterBlock.from_buffer(
                part, offset=BIOSParameterBlock._FORMAT.size)
            info_offset = (
                f32bpb.info_sector * bpb.bytes_per_sector)
            info = FAT32InfoSector.from_buffer(part, offset=info_offset)
            info._replace(free_clusters=len(fs.fat)).to_buffer(
                part, offset=info_offset)
        with FatFileSystem(img.partitions[1].data) as fs:
            assert fs._fat._info.free_clusters == len(fs.fat)
            for cluster, value in enumerate(fs.fat):
                if cluster >= 2 and value:
                    fs.fat.mark_free(cluster)
                    break
            assert fs._fat._info.free_clusters == len(fs.fat)


def test_fatclusters_close_idempotent(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with img.partitions[1].data as part:
            bpb = BIOSParameterBlock.from_buffer(part)
        with FatFileSystem(img.partitions[1].data) as fs:
            with fs._data as data:
                assert data._cs == bpb.sectors_per_cluster * bpb.bytes_per_sector
            assert not fs._data._mem
            fs._data.close()
            assert not fs._data._mem


def test_fatclusters_sequence(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with img.partitions[1].data as part:
            bpb = BIOSParameterBlock.from_buffer(part)
        with FatFileSystem(img.partitions[1].data) as fs:
            data_clusters = (
                bpb.fat16_total_sectors
                - bpb.reserved_sectors
                # fat_sectors
                - (bpb.fat_count * bpb.sectors_per_fat)
                # root_sectors
                - (bpb.max_root_entries * DirectoryEntry._FORMAT.size // bpb.bytes_per_sector)
            ) // bpb.sectors_per_cluster
            assert len(fs._data) == data_clusters
            assert len(fs._data[2]) == fs._data._cs
            assert len(fs._data[data_clusters - 1]) == fs._data._cs
            with pytest.raises(IndexError):
                fs._data[0]
            with pytest.raises(IndexError):
                fs._data[1]
            with pytest.raises(IndexError):
                fs._data[data_clusters + 2]


def test_fatclusters_mutate(fat12_disk):
    with DiskImage(fat12_disk, access=mmap.ACCESS_COPY) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            zeros = b'\0' * fs._data._cs
            ones = b'\xff' * fs._data._cs
            fs._data[2] = zeros
            assert fs._data[2] == zeros
            fs._data[2] = ones
            assert fs._data[2] == ones
            with pytest.raises(IndexError):
                fs._data[0] = zeros
            with pytest.raises(IndexError):
                fs._data[1] = zeros
            with pytest.raises(IndexError):
                fs._data[len(fs._data) + 2] = zeros
            with pytest.raises(TypeError):
                del fs._data[2]
            with pytest.raises(TypeError):
                fs._data.insert(2, zeros)


def test_fatdirectory_mapping(fat_disks):
    for fat_disk in fat_disks.values():
        with DiskImage(fat_disk) as img:
            with FatFileSystem(img.partitions[1].data) as fs:
                root = fs.open_dir(0)
                # Length, contains, iter, and all mapping views
                assert len(root) > 0
                assert 'empty' in root
                assert 'EMPTY' in root
                assert 'lots-of-zeros' in root
                assert 'LOTS-O~1' in root
                assert root['empty'] == root['EMPTY']
                assert root['lots-of-zeros'] == root['LOTS-O~1']
                assert 'lots-of-ones' not in root
                with pytest.raises(KeyError):
                    root['lots-of-ones']
                for name1, entry1, (name2, entry2) in zip(
                    root, root.values(), root.items()
                ):
                    assert lfn_valid(name1)
                    assert name1 == name2
                    assert isinstance(entry1, DirectoryEntry)
                    assert entry1 == entry2


def test_fatdirectory_mutate_out_of_range(fat12_disk):
    with DiskImage(fat12_disk, access=mmap.ACCESS_COPY) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            root = fs.open_dir(0)
            empty = root['empty']
            with pytest.raises(OSError):
                root._update_entry(128000, empty)


def test_fatdirectory_mutate(fat_disks):
    for fat_disk in fat_disks.values():
        with DiskImage(fat_disk, access=mmap.ACCESS_COPY) as img:
            with FatFileSystem(img.partitions[1].data) as fs:
                root = fs.open_dir(0)

                # Append, overwrite, and delete of simple SFN entries
                l = len(root)
                empty = root['empty']
                touched = empty._replace(adate=empty.adate + 1)
                root['empty'] = touched
                assert root['empty'] == touched
                root['empty2'] = touched
                assert 'empty2' in root
                assert root['empty'] == root['empty2']._replace(filename=b'EMPTY   ')
                assert len(root) == l + 1
                del root['empty']
                assert 'empty' not in root
                assert len(root) == l

                # Cover deletion of LFN entries too
                assert 'lots-of-zeros' in root
                del root['lots-of-zeros']
                assert 'lots-of-zeros' not in root
                assert len(root) == l - 1
                with pytest.raises(KeyError):
                    del root['i-dont-exist']


def test_fatdirectory_split_entries(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            root = fs.open_dir(0)
            offset, entries = find_lfn_file(root)
            # Filename with mod 13 chars (no \0 terminator)
            lfn, sfn, _ = root._split_entries(entries)
            assert (lfn, sfn) == ('lots-of-zeros', 'LOTS-O~1')
            # Filenames with ! mod 13 chars
            lfn, sfn, _ = root._split_entries([
                LongFilenameEntry(
                    sequence=0x41,
                    name_1=b'a\0b\0c\0d\0e\0',
                    attr=0xF,
                    checksum=0xCA,
                    name_2=b'f\0g\0h\0i\0j\0k\0',
                    first_cluster=0,
                    name_3=b'l\0\0\0'),
                entries[-1]._replace(
                    filename=b'ABCDEF~1',
                    ext=b'   ')
            ])
            assert (lfn, sfn) == ('abcdefghijkl', 'ABCDEF~1')


def test_fatdirectory_prefix_entries(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            root = fs.open_dir(0)
            offset, entries = find_non_lfn_file(root)
            lfn, sfn, entry = root._split_entries(entries)
            assert (lfn, sfn) == ('empty', 'EMPTY')

            # Ensure we don't generate LFNs when unnecessary
            assert root._prefix_entries('empty', entry) == entries

            # Short filenames with extension and variety of cases
            cksum = lfn_checksum(b'EMPTY   ', b'DAT')
            assert root._prefix_entries('EMPTY.DAT', entry) == [
                entry._replace(filename=b'EMPTY   ', ext=b'DAT', attr2=0)
            ]
            assert root._prefix_entries('empty.dat', entry) == [
                entry._replace(filename=b'EMPTY   ', ext=b'DAT', attr2=0b11000)
            ]
            assert root._prefix_entries('EMPTY.dat', entry) == [
                entry._replace(filename=b'EMPTY   ', ext=b'DAT', attr2=0b10000)
            ]
            assert root._prefix_entries('empty.DAT', entry) == [
                entry._replace(filename=b'EMPTY   ', ext=b'DAT', attr2=0b1000)
            ]

            # Short filename with mixed case, demanding LFN
            cksum = lfn_checksum(b'EMPTY~1 ', b'DAT')
            assert root._prefix_entries('Empty.Dat', entry) == [
                LongFilenameEntry(
                    sequence=0x41,
                    name_1=b'E\0m\0p\0t\0y\0',
                    attr=0xF,
                    checksum=cksum,
                    name_2=b'.\0D\0a\0t\0\0\0\xFF\xFF',
                    first_cluster=0,
                    name_3=b'\xFF' * 4,
                ),
                entry._replace(filename=b'EMPTY~1 ', ext=b'DAT', attr2=0)
            ]

            # "Special" . and .. entries
            assert root._prefix_entries('.', entry) == [
                entry._replace(filename=b'.       ', ext=b'   ', attr2=0)
            ]
            assert root._prefix_entries('..', entry) == [
                entry._replace(filename=b'..      ', ext=b'   ', attr2=0)
            ]

            # Filename with mod 13 chars (no \0 terminator)
            cksum = lfn_checksum(b'ABCDEF~1', b'   ')
            assert root._prefix_entries('abcdefghijklmnopqrstuvwxyz', entry) == [
                LongFilenameEntry(
                    sequence=0x42,
                    name_1=b'n\0o\0p\0q\0r\0',
                    attr=0xF,
                    checksum=cksum,
                    name_2=b's\0t\0u\0v\0w\0x\0',
                    first_cluster=0,
                    name_3=b'y\0z\0',
                ),
                LongFilenameEntry(
                    sequence=0x01,
                    name_1=b'a\0b\0c\0d\0e\0',
                    attr=0xF,
                    checksum=cksum,
                    name_2=b'f\0g\0h\0i\0j\0k\0',
                    first_cluster=0,
                    name_3=b'l\0m\0',
                ),
                entry._replace(
                    filename=b'ABCDEF~1',
                    ext=b'   ',
                    attr2=0,
                ),
            ]

            # Filename with !mod 13 chars (adds \0 terminator and padding)
            cksum = lfn_checksum(b'ABCDEF~1', b'   ')
            assert root._prefix_entries('abcdefghijklmnopqrstuvw', entry) == [
                LongFilenameEntry(
                    sequence=0x42,
                    name_1=b'n\0o\0p\0q\0r\0',
                    attr=0xF,
                    checksum=cksum,
                    name_2=b's\0t\0u\0v\0w\0\0\0',
                    first_cluster=0,
                    name_3=b'\xff' * 4,
                ),
                LongFilenameEntry(
                    sequence=0x01,
                    name_1=b'a\0b\0c\0d\0e\0',
                    attr=0xF,
                    checksum=cksum,
                    name_2=b'f\0g\0h\0i\0j\0k\0',
                    first_cluster=0,
                    name_3=b'l\0m\0',
                ),
                entry._replace(
                    filename=b'ABCDEF~1',
                    ext=b'   ',
                    attr2=0,
                ),
            ]

            # Excessive length
            with pytest.raises(ValueError):
                root._prefix_entries('foo' * 255, entry)


def test_fatdirectory_bad_lfn(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            root = fs.open_dir(0)
            offset, entries = find_lfn_file(root)

            # Blank LFN
            with pytest.warns(BadLongFilename):
                lfn, sfn, _ = root._split_entries([
                    entries[0]._replace(
                        name_1=b'\xFF' * 10,
                        name_2=b'\xFF' * 12,
                        name_3=b'\xFF' * 4),
                    entries[-1]])
            assert (lfn, sfn) == ('LOTS-O~1', 'LOTS-O~1')

            # Bad first_cluster
            with pytest.warns(BadLongFilename):
                lfn, sfn, _ = root._split_entries([
                    entries[0]._replace(first_cluster=1),
                    entries[-1]])
            assert (lfn, sfn) == ('LOTS-O~1', 'LOTS-O~1')

            # Bad checksum
            with pytest.warns(OrphanedLongFilename):
                lfn, sfn, _ = root._split_entries([
                    entries[0]._replace(checksum=0xFF),
                    entries[-1]])
            assert (lfn, sfn) == ('LOTS-O~1', 'LOTS-O~1')

            # Repeated terminal entry
            with pytest.warns(OrphanedLongFilename):
                lfn, sfn, _ = root._split_entries([
                    entries[0]._replace(sequence=0x43),
                    entries[0]._replace(sequence=0x02),
                    entries[0],
                    entries[-1]])
            assert (lfn, sfn) == ('lots-of-zeros', 'LOTS-O~1')

            # Bad sequence number
            with pytest.warns(BadLongFilename):
                lfn, sfn, _ = root._split_entries([
                    entries[0]._replace(sequence=0x40),
                    entries[-1]])
            assert (lfn, sfn) == ('LOTS-O~1', 'LOTS-O~1')

            # More bad sequence numbers
            with pytest.warns(OrphanedLongFilename):
                lfn, sfn, _ = root._split_entries([
                    entries[0]._replace(sequence=0x42),
                    entries[0]._replace(sequence=0x03),
                    entries[-1]])
            assert (lfn, sfn) == ('LOTS-O~1', 'LOTS-O~1')

            # More entries after last
            with pytest.warns(OrphanedLongFilename):
                lfn, sfn, _ = root._split_entries([
                    entries[0],
                    entries[0],
                    entries[0],
                    entries[-1]])
            assert (lfn, sfn) == ('lots-of-zeros', 'LOTS-O~1')

            # Missing entries
            with pytest.warns(OrphanedLongFilename):
                lfn, sfn, _ = root._split_entries([
                    entries[0]._replace(sequence=0x43),
                    entries[0]._replace(sequence=0x02),
                    entries[-1]])
            assert (lfn, sfn) == ('LOTS-O~1', 'LOTS-O~1')


def test_fatdirectory_ignores_deleted(fat12_disk):
    with DiskImage(fat12_disk, access=mmap.ACCESS_COPY) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            root = fs.open_dir(0)
            del_offset, entries = find_lfn_file(root)

            # Mark lots-of-zeros as deleted
            entries[0] = entries[0]._replace(sequence=0xE5)
            entries[1] = entries[1]._replace(
                filename=b'\xE5' + entries[1].filename[1:])
            root._update_entry(
                del_offset - DirectoryEntry._FORMAT.size, entries[0])
            root._update_entry(
                del_offset, entries[1])

            # Ensure _group_entries never yields the offsets we deleted
            for offset, entries in root._group_entries():
                assert offset != del_offset


def test_fatdirectory_clean(fat12_disk):
    with DiskImage(fat12_disk, access=mmap.ACCESS_COPY) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            root = fs.open_dir(0)
            eof_offset = dir_eof(root)
            del_offset, entries = find_lfn_file(root)

            # Mark lots-of-zeros as deleted
            entries[0] = entries[0]._replace(sequence=0xE5)
            entries[1] = entries[1]._replace(
                filename=b'\xE5' + entries[1].filename[1:])
            root._update_entry(
                del_offset - DirectoryEntry._FORMAT.size, entries[0])
            root._update_entry(
                del_offset, entries[1])

            # Offsets may change after clean, but not entries
            before_entries = [e for offset, e in root._group_entries()]
            root._clean_entries()
            after_entries = [e for offset, e in root._group_entries()]
            assert before_entries == after_entries
            assert dir_eof(root) == (
                eof_offset - (DirectoryEntry._FORMAT.size * 2))


def test_fatdirectory_get_unique_sfn(fat12_disk):
    with DiskImage(fat12_disk, access=mmap.ACCESS_COPY) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            root = fs.open_dir(0)
            offset, entries = find_lfn_file(root)
            lfn, sfn, entry = root._split_entries(entries)
            assert (lfn, sfn) == ('lots-of-zeros', 'LOTS-O~1')

            # Colliding SFN
            cksum = lfn_checksum(b'LOTS-O~2', b'   ')
            entries_2 = root._prefix_entries('lots-of-ones', entry)
            assert entries_2 == [
                LongFilenameEntry(
                    sequence=0x41,
                    name_1=b'l\0o\0t\0s\0-\0',
                    attr=0xF,
                    checksum=cksum,
                    name_2=b'o\0f\0-\0o\0n\0e\0',
                    first_cluster=0,
                    name_3=b's\0\0\0',
                ),
                entry._replace(
                    filename=b'LOTS-O~2',
                    ext=b'   ',
                    attr2=0,
                ),
            ]
            offset = dir_eof(root)
            for e in entries_2:
                root._update_entry(offset, e)
                offset += DirectoryEntry._FORMAT.size

            # Colliding LFN and SFN
            cksum = lfn_checksum(b'LOTS-O~4', b'   ')
            entries_3 = [
                LongFilenameEntry(
                    sequence=0x41,
                    name_1=b'L\0O\0T\0S\0-\0',
                    attr=0xF,
                    checksum=cksum,
                    name_2=b'O\0~\x003\0\0\0' + b'\xFF' * 4,
                    first_cluster=0,
                    name_3=b'\xFF' * 4,
                ),
                entry._replace(
                    filename=b'LOTS-O~4',
                    ext=b'   ',
                    attr2=0,
                ),
            ]
            offset = dir_eof(root)
            for e in entries_3:
                root._update_entry(offset, e)
                offset += DirectoryEntry._FORMAT.size

            cksum = lfn_checksum(b'LOTS-O~5', b'   ')
            entries_5 = root._prefix_entries('lots-of-nowt', entry)
            assert entries_5 == [
                LongFilenameEntry(
                    sequence=0x41,
                    name_1=b'l\0o\0t\0s\0-\0',
                    attr=0xF,
                    checksum=cksum,
                    name_2=b'o\0f\0-\0n\0o\0w\0',
                    first_cluster=0,
                    name_3=b't\0\0\0',
                ),
                entry._replace(
                    filename=b'LOTS-O~5',
                    ext=b'   ',
                    attr2=0,
                ),
            ]


def test_fatdirectory_cluster(fat_disks):
    for fat_type, fat_disk in fat_disks.items():
        with DiskImage(fat_disk) as img:
            with FatFileSystem(img.partitions[1].data) as fs:
                root = fs.open_dir(0)
                if fat_type == 'fat32':
                    assert root.cluster != 0
                else:
                    assert root.cluster == 0


def test_fatfile_readonly(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            root = fs.open_dir(0)
            offset, entries = find_non_empty_file(root)
            *entries, entry = entries

            f = fs.open_entry(root, entry)
            assert f.tell() == 0
            assert f.seek(0, io.SEEK_END) > 0
            assert f.seek(0, io.SEEK_END) == entry.size
            with pytest.raises(ValueError):
                f.seek(0, whence=100)
            with pytest.raises(OSError):
                f.seek(-1)
            assert f.readable()
            assert f.seekable()
            assert not f.writable()
            with pytest.raises(OSError):
                f.write(b'foo')
            with pytest.raises(OSError):
                f.truncate()
            f.seek(0)
            buf = f.read()
            assert isinstance(buf, bytes)
            assert len(buf) == entry.size
            buf = bytearray(10)
            assert f.readinto(buf) == 0
            assert f.tell() == entry.size
            f.close()
            with pytest.raises(ValueError):
                f.seek(0)
            with pytest.raises(ValueError):
                fs.open_entry(root, entry, mode='r')


def test_fatfile_fs_gone(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            root = fs.open_dir(0)
            offset, entries = find_non_empty_file(root)
            *entries, entry = entries
            f = fs.open_entry(root, entry)
    # Necessary to make sure fs is well and truly gone; will probably fail
    # on non-CPython, due to slower GC
    del fs
    with pytest.raises(ValueError):
        f.read(1024)


def test_fatfile_dir_no_key(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            root = fs.open_dir(0)
            offset, entries = first_dir(root)
            *entries, entry = entries
            f = fs.open_dir(get_cluster(entry, fs.fat_type))
            with pytest.raises(ValueError):
                f._file._get_key()


def test_fatfile_writable(fat12_disk):
    with DiskImage(fat12_disk, access=mmap.ACCESS_COPY) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            root = fs.open_dir(0)
            offset, entries = find_non_empty_file(root)
            *entries, entry = entries

            with fs.open_entry(root, entry, mode='a+b') as f:
                assert f.tell() == entry.size
                assert f.readable()
                assert f.seekable()
                assert f.writable()
            with fs.open_entry(root, entry, mode='wb') as f:
                assert f.tell() == 0
                assert not f.readable()
                assert f.seekable()
                assert f.writable()
                with pytest.raises(OSError):
                    f.read(10)
                with pytest.raises(OSError):
                    f.readall()
                # FatFile maintains one cluster even when file is empty, to
                # avoid re-allocation of clusters
                assert len(f._map) == 1
                # Write something multiple clusters long to test allocation of
                # new clusters
                assert f.write(b'\xFF' * fs.clusters.size * 2)
                assert len(f._map) == 2


def test_fatfile_write_empty(fat12_disk):
    with DiskImage(fat12_disk, access=mmap.ACCESS_COPY) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            root = fs.open_dir(0)
            offset, entries = find_empty_file(root)
            *entries, entry = entries
            with fs.open_entry(root, entry, mode='wb') as f:
                assert f.tell() == 0
                # Ensure map really is empty so we're allocating from scratch
                assert len(f._map) == 0
                # Write something multiple clusters long to test allocation of
                # new clusters
                assert f.write(b'\xFF' * fs.clusters.size * 2)
                assert len(f._map) == 2
                # This shouldn't be possible given how _write1 is normally
                # called, but for the sake of coverage...
                assert f._write1(b'') == 0


def test_fatfile_atime(fat12_disk):
    with DiskImage(fat12_disk, access=mmap.ACCESS_COPY) as img:
        with FatFileSystem(img.partitions[1].data, atime=True) as fs:
            root = fs.open_dir(0)
            offset, entries = find_non_empty_file(root)
            *entries, entry = entries

            with fs.open_entry(root, entry) as f:
                f.read()
                assert f._entry.adate > entry.adate


def test_fatfile_mtime(fat12_disk):
    with DiskImage(fat12_disk, access=mmap.ACCESS_COPY) as img:
        with FatFileSystem(img.partitions[1].data, atime=True) as fs:
            root = fs.open_dir(0)
            offset, entries = find_non_empty_file(root)
            *entries, entry = entries

            with fs.open_entry(root, entry, mode='r+b') as f:
                f.write(b'\x00' * 10)
                assert f._entry.mdate > entry.mdate


def test_fatfile_truncate(fat12_disk):
    # Check general truncate functionality (truncate to 0, and implicit
    # truncation to current position)
    with DiskImage(fat12_disk, access=mmap.ACCESS_COPY) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            root = fs.open_dir(0)
            offset, entries = find_non_empty_file(root)
            *entries, entry = entries

            with fs.open_entry(root, entry, mode='r+b') as f:
                # Ensure truncate actually removes bytes from the file's record
                assert f.tell() == 0
                assert f._entry.size > 0
                assert f.truncate() == 0
                assert f._entry.size == 0
                # Seek beyond new EOF and ensure next write "truncates" up to
                # the new position
                assert f.seek(512) == 512
                assert f.write(b'foo') == 3
                assert f.tell() == 515
                assert f._entry.size == 515

    # Check truncate with explicit sizes
    with DiskImage(fat12_disk, access=mmap.ACCESS_COPY) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            root = fs.open_dir(0)
            offset, entries = find_non_empty_file(root)
            *entries, entry = entries

            with fs.open_entry(root, entry, mode='r+b') as f:
                assert f.tell() == 0
                assert f._entry.size > 2
                assert f.truncate(size=2) == 2
                assert f._entry.size == 2

    # Check truncate with multiple extra clusters
    with DiskImage(fat12_disk, access=mmap.ACCESS_COPY) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            root = fs.open_dir(0)
            offset, entries = find_non_empty_file(root)
            *entries, entry = entries

            with fs.open_entry(root, entry, mode='wb') as f:
                assert f.seek(fs.clusters.size * 4) == fs.clusters.size * 4
                assert f.write(b'foo') == 3
                assert f.tell() == fs.clusters.size * 4 + 3
