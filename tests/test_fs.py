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


def first_dir(fat_dir):
    for offset, entries in fat_dir._group_entries():
        if entries[-1].attr & 0x10:
            return offset, entries
    assert False, 'failed to find dir'


def first_lfn_file(fat_dir):
    for offset, entries in fat_dir._group_entries():
        if len(entries) > 1 and not entries[-1].attr & 0x10:
            return offset, entries
    assert False, 'failed to find file with LFN'


def first_non_lfn_file(fat_dir):
    for offset, entries in fat_dir._group_entries():
        if len(entries) == 1 and not entries[-1].attr & 0x10:
            return offset, entries
    assert False, 'failed to find file without LFN'


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


def test_fat12table_sequence(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with img.partitions[1].data as part:
            bpb = BIOSParameterBlock.from_buffer(part)
        with FatFileSystem(img.partitions[1].data) as fs:
            assert fs._fat.readonly == fs.readonly
            assert len(fs._fat) == (
                bpb.sectors_per_fat * bpb.bytes_per_sector // 1.5)
            assert fs._fat[0] > fs._fat.max_valid
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


def test_fatdirectory_iter(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            root = fs.open_dir(0)
            for name1, entry1, (name2, entry2) in zip(
                root, root.values(), root.items()
            ):
                assert lfn_valid(name1)
                assert name1 == name2
                assert isinstance(entry1, DirectoryEntry)
                assert entry1 == entry2


def test_fatdirectory_split_entries(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            root = fs.open_dir(0)
            offset, entries = first_lfn_file(root)
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
            offset, entries = first_non_lfn_file(root)
            # Regular, non-LFN file
            lfn, sfn, entry = root._split_entries(entries)
            assert (lfn, sfn) == ('empty', 'EMPTY')
            cksum = lfn_checksum(entry.filename, entry.ext)
            # Filename with mod 13 chars (no \0 terminator)
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
                entry,
            ]


def test_fatdirectory_bad_lfn(fat12_disk):
    with DiskImage(fat12_disk) as img:
        with FatFileSystem(img.partitions[1].data) as fs:
            root = fs.open_dir(0)
            offset, entries = first_lfn_file(root)

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
