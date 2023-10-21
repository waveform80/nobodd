import os
import mmap
import uuid
from binascii import crc32
from collections.abc import Mapping

from .mbr import MBRHeader, MBRPartition
from .gpt import GPTHeader, GPTPartition


class DiskImage:
    def __init__(self, filename_or_obj, sector_size=512):
        self._ss = sector_size
        if isinstance(filename_or_obj, os.PathLike):
            filename_or_obj = filename_or_obj.__fspath__()
        self._opened = isinstance(filename_or_obj, str)
        if self._opened:
            self._file = open(filename_or_obj, 'rb')
        else:
            self._file = filename_or_obj
        self._map = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        self._mem = memoryview(self._map)

    def __repr__(self):
        return f'<{self.__class__.__name__} file={self._file!r}>'

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self._map is not None:
            self._mem.release()
            self._map.close()
            if self._opened:
                self._file.close()
        self._map = None
        self._mem = None
        self._file = None

    @property
    def partitions(self):
        # This is a bit hacky, but reliable enough for our purposes. We check
        # for the "EFI PART" signature at the start of LBA1 and, if we find it,
        # we assume we're dealing with GPT. We don't check for a protective or
        # hybrid MBR because we wouldn't use it in any case. Otherwise we,
        # check for a valid MBR boot-signature at the appropriate offset.
        # Failing both of these, we raise an error.
        #
        # Note that, *theoretically*, "EFI PART" could appear in the bootstrap
        # code at the start of the MBR. However, I'm treating that as
        # sufficiently weird that it's not worth guarding against.
        head = GPTHeader.from_buffer(self._mem, 0)
        if head.signature == b'EFI PART':
            return DiskPartitionsGPT(self._mem, head, self._ss)
        head = GPTHeader.from_buffer(self._mem, self._ss)
        if head.signature == b'EFI PART':
            return DiskPartitionsGPT(self._mem, head, self._ss)
        head = MBRHeader.from_buffer(self._mem, 0)
        if head.boot_sig == 0xAA55:
            return DiskPartitionsMBR(self._mem, head, self._ss)
        raise ValueError(
            f'Unable to determine partitioning scheme in use by {self._file}')


class DiskPartition:
    def __init__(self, mem, label, type):
        self._mem = mem
        self._label = label
        self._type = type

    def __repr__(self):
        return (
            f'<{self.__class__.__name__} size={len(self._mem)} '
            f'label={self._label!r} type={self._type!r}>')

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self._mem.release()

    @property
    def type(self):
        return self._type

    @property
    def label(self):
        return self._label

    @property
    def data(self):
        return self._mem


class DiskPartitionsGPT(Mapping):
    style = 'gpt'

    def __init__(self, mem, header, sector_size=512):
        if not isinstance(header, GPTHeader):
            raise ValueError('header must be a GPTHeader instance')
        if header.signature != b'EFI PART':
            raise ValueError('Bad GPT signature')
        if header.revision != b'\x00\x00\x01\x00':
            raise ValueError('Unrecognized GPT version')
        if header.header_size != GPTHeader._FORMAT.size:
            raise ValueError('Bad GPT header size')
        data = bytearray(header.raw)
        data[0x10:0x14] = b'\x00\x00\x00\x00'
        if crc32(data) != header.header_crc32:
            raise ValueError('Bad GPT header CRC32')
        self._mem = mem
        self._header = header
        self._ss = sector_size

    def _get_table(self):
        start = self._header.part_table_lba
        table_sectors = ((
            (self._header.part_table_size * self._header.part_entry_size) +
            self._ss - 1) // self._ss)
        return self._mem[self._ss * start:self._ss * (start + table_sectors)]

    def __len__(self):
        with self._get_table() as table:
            count = 0
            for offset in range(0, len(table), self._header.part_entry_size):
                entry = GPTPartition.from_buffer(table, offset)
                if entry.type_guid != b'\x00' * 16:
                    count += 1
            return count

    def __getitem__(self, index):
        if not 1 <= index <= self._header.part_table_size:
            raise KeyError(index)
        with self._get_table() as table:
            entry = GPTPartition.from_buffer(
                table, self._header.part_entry_size * (index - 1))
            if entry.part_guid == b'\x00' * 16:
                raise KeyError(index)
            start = self._ss * entry.first_lba
            finish = self._ss * (entry.last_lba + 1)
            return DiskPartition(
                mem=self._mem[start:finish],
                type=uuid.UUID(bytes_le=entry.type_guid),
                label=entry.part_label.decode('utf-16-le').rstrip('\x00'))

    def __iter__(self):
        with self._get_table() as table:
            for index in range(self._header.part_table_size):
                entry = GPTPartition.from_buffer(
                    table, self._header.part_entry_size * index)
                if entry.part_guid == b'\x00' * 16:
                    continue
                yield index


class DiskPartitionsMBR(Mapping):
    style = 'mbr'

    def __init__(self, mem, header, sector_size=512):
        if not isinstance(header, MBRHeader):
            raise ValueError('header must be a MBRHeader instance')
        if header.boot_sig != 0xAA55:
            raise ValueError('Bad MBR signature')
        self._mem = mem
        self._header = header
        self._ss = sector_size

    def _get_logical(self, ext_offset):
        logical_offset = ext_offset
        while True:
            ebr = MBRHeader.from_buffer(self._mem, logical_offset * self._ss)
            if ebr.boot_sig != 0xAA55:
                raise ValueError('Bad EBR signature')
            # Yield the logical partition
            part = MBRPartition.from_string(ebr.partition_1)
            part = part._replace(first_lba=part.first_lba + logical_offset)
            yield part
            part = MBRPartition.from_string(ebr.partition_2)
            if part.part_type == 0x00 and part.first_lba == 0:
                break
            elif part.part_type not in (0x05, 0x0F):
                raise ValueError(
                    'Second partition in EBR at LBA {logical_offset) is not '
                    'another EBR or a terminal')
            logical_offset = part.first_lba + ext_offset

    def _get_primary(self):
        mbr = self._header
        ebr = None
        for num, buf in enumerate(mbr.partitions, start=1):
            part = MBRPartition.from_string(buf)
            if part.part_type in (0x05, 0x0F):
                if ebr is not None:
                    warnings.warn(
                        UserWarning('Multiple extended partitions found'))
                yield from enumerate(self._get_logical(part.first_lba), start=5)
            elif part.part_type != 0x00:
                yield num, part

    def __len__(self):
        return sum(1 for num, part in self._get_primary())

    def __getitem__(self, index):
        for num, part in self._get_primary():
            if num == index:
                last_lba = part.first_lba + part.part_size
                return DiskPartition(
                    mem=self._mem[self._ss * part.first_lba:self._ss * last_lba],
                    type=part.part_type,
                    label=f'Partition {num}')
        raise KeyError(index)

    def __iter__(self):
        for num, part in self._get_primary():
            yield num
