import uuid
from binascii import crc32

import pytest

from nobodd.gpt import *


def test_gpt_header_from_buffer(gpt_disk):
    gpt_disk.seek(1 * 512)
    head = gpt_disk.read(512)
    gpt_disk.seek(2 * 512)
    table = gpt_disk.read(128 * 128)

    h = GPTHeader.from_buffer(head)
    assert h.signature == b'EFI PART'
    assert h.revision == 0x10000
    assert h.header_size == GPTHeader._FORMAT.size
    assert h.header_crc32 == crc32(bytes(h._replace(header_crc32=0)))
    assert h.current_lba == 1
    assert h.backup_lba == 65535
    assert h.first_usable_lba == 34
    assert h.last_usable_lba == 65502
    assert uuid.UUID(bytes_le=h.disk_guid) == uuid.UUID(
        '733B49A8-6918-4E44-8D3D-47ED9B481335')
    assert h.part_table_lba == 2
    assert h.part_table_size == 128
    assert h.part_entry_size == 128
    assert h.part_table_crc32 == crc32(table)


def test_gpt_header_from_bytes(gpt_disk):
    gpt_disk.seek(1 * 512)
    head = gpt_disk.read(512)

    h1 = GPTHeader.from_bytes(head[:GPTHeader._FORMAT.size])
    h2 = GPTHeader.from_buffer(head)
    assert h1 == h2


def test_gpt_header_to_bytes(gpt_disk):
    gpt_disk.seek(1 * 512)
    head = gpt_disk.read(512)

    h = GPTHeader.from_buffer(head)
    assert head[:GPTHeader._FORMAT.size] == bytes(h)


def test_gpt_partition_from_buffer(gpt_disk):
    gpt_disk.seek(2 * 512)
    table = gpt_disk.read(128 * 128)

    part1 = GPTPartition.from_buffer(table, offset=0)
    assert part1.part_label.decode('utf-16le').rstrip('\0') == 'big-part'
    assert part1.flags == 0
    assert part1.first_lba == 2048
    assert part1.last_lba == 18431
    assert uuid.UUID(bytes_le=part1.type_guid) == uuid.UUID(
        'EBD0A0A2-B9E5-4433-87C0-68B6B72699C7')

    part2 = GPTPartition.from_buffer(table, offset=GPTPartition._FORMAT.size)
    assert part2.part_label.decode('utf-16le').rstrip('\0') == 'little-part1'
    assert part2.flags == 0
    assert part2.first_lba == 18432
    assert part2.last_lba == 18831
    assert uuid.UUID(bytes_le=part1.type_guid) == uuid.UUID(
        'EBD0A0A2-B9E5-4433-87C0-68B6B72699C7')


def test_gpt_partition_from_bytes(gpt_disk):
    gpt_disk.seek(2 * 512)
    table = gpt_disk.read(128 * 128)

    p1 = GPTPartition.from_bytes(table[:GPTPartition._FORMAT.size])
    p2 = GPTPartition.from_buffer(table)
    assert p1 == p2


def test_gpt_partition_to_bytes(gpt_disk):
    gpt_disk.seek(2 * 512)
    table = gpt_disk.read(128 * 128)

    p = GPTPartition.from_buffer(table)
    assert table[:GPTPartition._FORMAT.size] == bytes(p)
