# nobodd: a boot configuration tool for the Raspberry Pi
#
# Copyright (c) 2024 Dave Jones <dave.jones@canonical.com>
# Copyright (c) 2024 Canonical Ltd.
#
# SPDX-License-Identifier: GPL-3.0

import pytest

from nobodd.mbr import *


def test_mbr_header_from_buffer(mbr_disk):
    with mbr_disk.open('rb') as source:
        source.seek(0)
        head = source.read(512)

        h = MBRHeader.from_buffer(head)
        assert h.boot_sig == 0xAA55
        assert h.zero == 0
        assert h.disk_sig == 0x3b1190bc
        assert h.copy_protect == 0


def test_mbr_header_from_bytes(mbr_disk):
    with mbr_disk.open('rb') as source:
        source.seek(0)
        head = source.read(512)

        h1 = MBRHeader.from_bytes(head[:MBRHeader._FORMAT.size])
        h2 = MBRHeader.from_buffer(head)
        assert h1 == h2


def test_mbr_header_to_bytes(mbr_disk):
    with mbr_disk.open('rb') as source:
        source.seek(0)
        head = source.read(512)

        h = MBRHeader.from_buffer(head)
        assert head[:MBRHeader._FORMAT.size] == bytes(h)


def test_mbr_header_partitions(mbr_disk):
    with mbr_disk.open('rb') as source:
        source.seek(0)
        head = source.read(512)

        h = MBRHeader.from_buffer(head)
        assert len(h.partitions) == 4
        assert h.partition_1 == h.partitions[0]


def test_mbr_partition_from_buffer(mbr_disk):
    with mbr_disk.open('rb') as source:
        source.seek(0)
        head = source.read(512)

        h = MBRHeader.from_buffer(head)
        part1 = MBRPartition.from_buffer(h.partition_1)
        assert part1.status == 0
        assert part1.part_type == 0xC
        assert part1.first_lba == 2048
        assert part1.part_size == 16384

        part2 = MBRPartition.from_buffer(h.partition_2)
        assert part2.status == 0
        assert part2.part_type == 0xC
        assert part2.first_lba == 18432
        assert part2.part_size == 401


def test_mbr_partition_from_bytes(mbr_disk):
    with mbr_disk.open('rb') as source:
        source.seek(0)
        head = source.read(512)

        h = MBRHeader.from_buffer(head)
        p1 = MBRPartition.from_bytes(h.partition_1)
        p2 = MBRPartition.from_buffer(h.partition_1)
        assert p1 == p2


def test_mbr_partition_to_bytes(mbr_disk):
    with mbr_disk.open('rb') as source:
        source.seek(0)
        head = source.read(512)

        h = MBRHeader.from_buffer(head)
        p = MBRPartition.from_buffer(h.partition_1)
        assert h.partition_1 == bytes(p)
