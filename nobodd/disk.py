import os
import mmap
import uuid
from binascii import crc32
from collections.abc import Mapping

from .mbr import MBRHeader, MBRPartition
from .gpt import GPTHeader, GPTPartition


class DiskImage:
    """
    Represents a disk image, specified by *filename_or_obj* which must be a
    :class:`str` or :class:`~pathlib.Path` naming the file, or a file-like
    object.

    If a file-like object is provided, it *must* have a ``fileno`` method which
    returns a valid file-descriptor number (the class uses :class:`~mmap.mmap`
    internally which requires a "real" file).

    The disk image is expected to be partitioned with either an `MBR`_ or a
    `GPT`_. The partitions within the image can be enumerated with the
    :attr:`partitions` attribute. The instance can (and should) be used as
    a context manager; exiting the context will call the :meth:`close` method
    implicitly.

    If specified, *sector_size* is the size of sectors (in bytes) within the
    disk image. This defaults to 512 bytes, and should almost always be left
    alone.

    .. _MBR: https://en.wikipedia.org/wiki/Master_boot_record
    .. _GPT: https://en.wikipedia.org/wiki/GUID_Partition_Table
    """
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
        self._map = None
        self._mem = None
        self._file = None

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
            partition 4 to be defined between partition 1 and 2.

        .. note::

            In the case of MBR partition tables, it is particularly common to
            have missing partition numbers as the primary layout only permits 4
            partitions. Hence, the "extended partitions" scheme numbers
            partitions from 5. However, if not all primary partitions are
            defined, there will be a "jump" from, say, partition 2 to partition
            5.
        """
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
        head = GPTHeader.from_buffer(self._mem, self._ss)
        if head.signature == b'EFI PART':
            return DiskPartitionsGPT(self._mem, head, self._ss)
        head = MBRHeader.from_buffer(self._mem, 0)
        if head.boot_sig == 0xAA55:
            return DiskPartitionsMBR(self._mem, head, self._ss)
        raise ValueError(
            f'Unable to determine partitioning scheme in use by {self._file}')


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
            f'<{self.__class__.__name__} size={len(self._mem)} '
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


class DiskPartitionsGPT(Mapping):
    """
    Provides a :class:`~collections.abc.Mapping` from partition number to
    :class:`DiskPartition` instances for a `GPT`_.

    *mem* is the buffer covering the whole disk image, and *header* is a
    :class:`~nobodd.gpt.GPTHeader` instance decoded from the front of the
    `GPT`_. *sector_size* specifies the sector size of the disk image, which
    should almost always be left at the default of 512 bytes.

    The :attr:`style` instance attribute can be queried to determine this is a
    GPT.

    .. autoattribute:: style
    """
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
                yield index + 1


class DiskPartitionsMBR(Mapping):
    """
    Provides a :class:`~collections.abc.Mapping` from partition number to
    :class:`DiskPartition` instances for a `MBR`_.

    *mem* is the buffer covering the whole disk image, and *header* is a
    :class:`~nobodd.gpt.MBRHeader` instance decoded from the front of the
    `MBR`_. *sector_size* specifies the sector size of the disk image, which
    should almost always be left at the default of 512 bytes.

    The :data:`style` instance attribute can be queried to determine this is a
    MBR style partition table.

    .. autoattribute:: style
    """
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
