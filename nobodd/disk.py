# nobodd: a boot configuration tool for the Raspberry Pi
#
# Copyright (c) 2023-2024 Dave Jones <dave.jones@canonical.com>
# Copyright (c) 2023-2024 Canonical Ltd.
#
# SPDX-License-Identifier: GPL-3.0

import os
import mmap
import uuid
import warnings
from binascii import crc32
from collections.abc import Mapping

from . import lang
from .mbr import MBRHeader, MBRPartition
from .gpt import GPTHeader, GPTPartition


class DiskImage:
    """
    Represents a disk image, specified by *filename_or_obj* which must be a
    :class:`str` or :class:`~pathlib.Path` naming the file, or a file-like
    object.

    If a file-like object is provided, it *must* have a
    :attr:`~io.IOBase.fileno` method which returns a valid file-descriptor
    number (the class uses :class:`~mmap.mmap` internally which requires a
    "real" file).

    The disk image is expected to be partitioned with either an `MBR`_
    partition table or a `GPT`_. The partitions within the image can be
    enumerated with the :attr:`partitions` attribute. The instance can (and
    should) be used as a context manager; exiting the context will call the
    :meth:`close` method implicitly.

    If specified, *sector_size* is the size of sectors (in bytes) within the
    disk image. This defaults to 512 bytes, and should almost always be left
    alone. The *access* parameter controls the access used when constructing
    the memory mapping. This defaults to :data:`mmap.ACCESS_READ` for read-only
    access. If you wish to write to file-systems within the disk image, change
    this to :data:`mmap.ACCESS_WRITE`. You may also use
    :data:`mmap.ACCESS_COPY` for read-write mappings that don't actually affect
    the underlying disk image.

    .. note::

        Please note that this library provides no means to re-partition disk
        images, just the ability to re-write files within FAT partitions.

    .. _MBR: https://en.wikipedia.org/wiki/Master_boot_record
    .. _GPT: https://en.wikipedia.org/wiki/GUID_Partition_Table
    """
    def __init__(self, filename_or_obj, sector_size=512, access=mmap.ACCESS_READ):
        self._ss = sector_size
        if isinstance(filename_or_obj, os.PathLike):
            filename_or_obj = filename_or_obj.__fspath__()
        self._opened = isinstance(filename_or_obj, str)
        if self._opened:
            self._file = open(
                filename_or_obj, 'r+b' if access == mmap.ACCESS_WRITE else 'rb')
        else:
            self._file = filename_or_obj
        self._map = mmap.mmap(self._file.fileno(), 0, access=access)
        self._mem = memoryview(self._map)
        self._partitions = None

    def __repr__(self):
        return (
            f'<{self.__class__.__name__} file={self._file!r} '
            f'style={self.style!r} signature={self.signature!r}>')

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        """
        Destroys the memory mapping used on the file provided. If the file was
        opened by this class, it will also be closed. This method is
        idempotent and is implicitly called when the instance is used as a
        context manager.

        .. note::

            All mappings derived from this one *must* be closed before calling
            this method. By far the easiest means of arranging this is to
            consistently use context managers with all instances derived from
            this.
        """
        if self._map is not None:
            self._mem.release()
            self._map.close()
            if self._opened:
                self._file.close()
        self._partitions = None
        self._map = None
        self._mem = None
        self._file = None

    @property
    def style(self):
        """
        The style of partition table in use on the disk image. Will be one of
        the strings, 'gpt' or 'mbr'.
        """
        return self.partitions.style

    @property
    def signature(self):
        """
        The identifying signature of the disk. In the case of a GPT partitioned
        disk, this is a :class:`~uuid.UUID`. In the case of MBR, this is a
        32-bit integer number.
        """
        return self.partitions.signature

    @property
    def partitions(self):
        """
        Provides access to the partitions in the image as a
        :class:`~collections.abc.Mapping` of partition number to
        :class:`DiskPartition` instances.

        .. warning::

            Disk partition numbers start from 1 and need not be contiguous, or
            ordered.

            For example, it is perfectly valid to have partition 1 occur later
            on disk than partition 2, for partition 3 to be undefined, and
            partition 4 to be defined between partition 1 and 2. The partition
            number is essentially little more than an arbitrary key.

            In the case of MBR partition tables, it is particularly common to
            have missing partition numbers as the primary layout only permits 4
            partitions. Hence, the "extended partitions" scheme numbers
            partitions from 5. However, if not all primary partitions are
            defined, there will be a "jump" from, say, partition 2 to partition
            5.
        """
        # This is a bit hacky, but reliable enough for our purposes. We check
        # for the "EFI PART" signature at the start of sector 1 and, if we find
        # it, we assume we're dealing with GPT. We don't check for a protective
        # or hybrid MBR because we wouldn't use it in any case. Otherwise we,
        # check for a valid MBR boot-signature at the appropriate offset.
        # Failing both of these, we raise an error.
        if self._partitions is None:
            for cls in (DiskPartitionsGPT, DiskPartitionsMBR):
                try:
                    self._partitions = cls(self._mem, self._ss)
                except ValueError:
                    pass
                else:
                    break
            else:
                raise ValueError(lang._(
                    'Unable to determine partitioning scheme in use by '
                    '{self._file}'.format(self=self)))
        return self._partitions


class DiskPartition:
    """
    Represents an individual disk partition within a :class:`DiskImage`.

    Instances of this class are returned as the values of the mapping provided
    by :attr:`DiskImage.partitions`. Instances can (and should) be used as a
    context manager to implicitly close references upon exiting the context.
    """
    def __init__(self, mem, label, type):
        self._mem = mem
        self._label = label
        self._type = type

    def __repr__(self):
        return (
            f'<{self.__class__.__name__} size={self._mem.nbytes} '
            f'label={self._label!r} type={self._type!r}>')

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        """
        Release the internal :class:`memoryview` reference. This method is
        idempotent and is implicitly called when the instance is used as a
        context manager.
        """
        self._mem.release()

    @property
    def type(self):
        """
        The type of the partition. For `GPT`_ partitions, this will be a
        :class:`uuid.UUID` instance. For `MBR`_ partitions, this will be an
        :class:`int`.
        """
        return self._type

    @property
    def label(self):
        """
        The label of the partition. `GPT`_ partitions may have a 36 character
        unicode label. `MBR`_ partitions do not have a label, so the string
        "Partition {num}" will be used instead (where *{num}* is the partition
        number).
        """
        return self._label

    @property
    def data(self):
        """
        Returns a buffer (specifically, a :class:`memoryview`) covering the
        contents of the partition in the owning :class:`DiskImage`.
        """
        return self._mem


class DiskPartitions(Mapping):
    """
    Abstract base class for the classes that handle specific partition layouts.
    Provides common handlers for :func:`repr` amongst other things.
    """
    def __repr__(self):
        partitions = '\n'.join(f'{key}: {part!r},' for key, part in self.items())
        return f'{self.__class__.__name__}({{\n{partitions}\n}})'


class DiskPartitionsGPT(DiskPartitions):
    """
    Provides a :class:`~collections.abc.Mapping` from partition number to
    :class:`DiskPartition` instances for a `GPT`_.

    *mem* is the buffer covering the whole disk image. *sector_size* specifies
    the sector size of the disk image, which should almost always be left at
    the default of 512 bytes.
    """
    style = 'gpt'

    def __init__(self, mem, sector_size=512):
        header = GPTHeader.from_buffer(mem, sector_size * 1)
        if header.signature != b'EFI PART':
            raise ValueError(lang._('Bad GPT signature'))
        if header.revision != 0x10000:
            raise ValueError(lang._('Unrecognized GPT version'))
        if header.header_size != GPTHeader._FORMAT.size:
            raise ValueError(lang._('Bad GPT header size'))
        if crc32(bytes(header._replace(header_crc32=0))) != header.header_crc32:
            raise ValueError(lang._('Bad GPT header CRC32'))
        self._mem = mem
        self._header = header
        self._ss = sector_size

    @property
    def signature(self):
        return uuid.UUID(bytes_le=self._header.disk_guid)

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
                yield index + 1


class DiskPartitionsMBR(DiskPartitions):
    """
    Provides a :class:`~collections.abc.Mapping` from partition number to
    :class:`DiskPartition` instances for a `MBR`_.

    *mem* is the buffer covering the whole disk image. *sector_size* specifies
    the sector size of the disk image, which should almost always be left at
    the default of 512 bytes.
    """
    style = 'mbr'

    def __init__(self, mem, sector_size=512):
        header = MBRHeader.from_buffer(mem, offset=0)
        if header.boot_sig != 0xAA55:
            raise ValueError(lang._('Bad MBR signature'))
        if header.zero != 0:
            raise ValueError(lang._('Bad MBR zero field'))
        self._mem = mem
        self._header = header
        self._ss = sector_size
        if len(self) == 1 and self[1].type == 0xEE:
            raise ValueError(lang._('Protective MBR; use GPT instead'))

    @property
    def signature(self):
        return self._header.disk_sig

    def _get_logical(self, ext_offset):
        logical_offset = ext_offset
        while True:
            ebr = MBRHeader.from_buffer(self._mem, logical_offset * self._ss)
            if ebr.boot_sig != 0xAA55:
                raise ValueError(lang._('Bad EBR signature'))
            # Yield the logical partition
            part = MBRPartition.from_bytes(ebr.partition_1)
            part = part._replace(first_lba=part.first_lba + logical_offset)
            yield part
            part = MBRPartition.from_bytes(ebr.partition_2)
            if part.part_type == 0x00 and part.first_lba == 0:
                break
            elif part.part_type not in (0x05, 0x0F):
                raise ValueError(lang._(
                    'Second partition in EBR at LBA {logical_offset} is not '
                    'another EBR or a terminal'
                    .format(logical_offset=logical_offset)))
            logical_offset = part.first_lba + ext_offset

    def _get_primary(self):
        mbr = self._header
        extended = False
        for num, buf in enumerate(mbr.partitions, start=1):
            part = MBRPartition.from_bytes(buf)
            if part.part_type in (0x05, 0x0F):
                if extended:
                    warnings.warn(UserWarning(lang._(
                        'Multiple extended partitions found')))
                extended = True
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
