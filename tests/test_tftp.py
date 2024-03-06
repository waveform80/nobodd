# nobodd: a boot configuration tool for the Raspberry Pi
#
# Copyright (c) 2024 Dave Jones <dave.jones@canonical.com>
# Copyright (c) 2024 Canonical Ltd.
#
# SPDX-License-Identifier: GPL-3.0

import pytest

from nobodd.tftp import *


def test_rrq_init():
    pkt = RRQPacket('foo.txt', 'octet', {'blksize': '1428'})
    assert pkt.filename == 'foo.txt'
    assert pkt.mode == 'octet'
    assert pkt.options == {'blksize': '1428'}
    assert repr(pkt) == (
        "RRQPacket(filename='foo.txt', mode='octet', options="
        "FrozenDict({'blksize': '1428'}))")
    pkt = RRQPacket('bar.txt', 'netascii')
    assert pkt.filename == 'bar.txt'
    assert pkt.mode == 'netascii'
    assert pkt.options == {}


def test_rrq_roundtrip():
    pkt = Packet.from_bytes(b'\x00\x01foo.txt\x00octet\x00blksize\x001428\x00')
    pkt2 = Packet.from_bytes(bytes(pkt))
    assert pkt.filename == pkt2.filename
    assert pkt.mode == pkt2.mode
    assert pkt.options == pkt2.options
    with pytest.raises(ValueError):
        Packet.from_bytes(b'\x00\x01foo.txt\x00')
    with pytest.raises(ValueError):
        Packet.from_bytes(b'\x00\x01foo.txt\x00ebcdic\x00\x00')


def test_data_init():
    pkt = DATAPacket('1', b'\0' * 512)
    assert pkt.block == 1
    assert len(pkt.data) == 512
    assert repr(pkt) == (
        "DATAPacket(block=1, data=b'" +
        "\\x00" * 512 +
        "')")
    with pytest.raises(ValueError):
        DATAPacket(1000000, b'\0' * 512)


def test_data_roundtrip():
    pkt = Packet.from_bytes(b'\x00\x03\x00\x01' + b'\x00' * 512)
    pkt2 = Packet.from_bytes(bytes(pkt))
    assert pkt.block == pkt2.block
    assert pkt.data == pkt2.data


def test_ack_init():
    pkt = ACKPacket('10')
    assert pkt.block == 10
    with pytest.raises(ValueError):
        ACKPacket(1000000)


def test_ack_roundtrip():
    pkt = Packet.from_bytes(b'\x00\x04\x00\x0A')
    pkt2 = Packet.from_bytes(bytes(pkt))
    assert pkt.block == pkt2.block


def test_error_init():
    pkt = ERRORPacket('1')
    assert pkt.error == Error.NOT_FOUND
    assert pkt.message == 'File not found'
    pkt = ERRORPacket('0', 'Everything is on fire')
    assert pkt.error == Error.UNDEFINED
    assert pkt.message == 'Everything is on fire'


def test_error_roundtrip():
    pkt = Packet.from_bytes(b'\x00\x05\x00\x01')
    pkt2 = Packet.from_bytes(bytes(pkt))
    assert pkt.error == pkt2.error
    assert pkt.message == pkt2.message


def test_oack_init():
    pkt = OACKPacket({'blksize': '1428'})
    assert pkt.options == {'blksize': '1428'}


def test_oack_roundtrip():
    pkt = Packet.from_bytes(b'\x00\x06blksize\x001428\x00')
    pkt2 = Packet.from_bytes(bytes(pkt))
    assert pkt.options == pkt2.options


def test_bad_init():
    with pytest.raises(ValueError):
        Packet.from_bytes(b'\x00\x08\x00\x00\x00\x00')
