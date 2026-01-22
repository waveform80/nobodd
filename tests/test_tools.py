# nobodd: a boot configuration tool for the Raspberry Pi
#
# Copyright (c) 2024 Dave Jones <dave.jones@canonical.com>
# Copyright (c) 2024 Canonical Ltd.
#
# SPDX-License-Identifier: GPL-3.0

import re
import socket
import datetime as dt
from textwrap import dedent
from unittest import mock
from zoneinfo import ZoneInfo

import pytest

from nobodd.tools import *


@pytest.fixture()
def ebpb(request):
    return dedent("""
        B     drive_number
        1x    reserved
        B     extended_boot_sig
        4s    volume_id
        11s   volume_label
        8s    file_system
        """)


def test_labels(ebpb):
    assert labels(ebpb) == (
        'drive_number',
        'extended_boot_sig',
        'volume_id',
        'volume_label',
        'file_system'
    )


def test_formats(ebpb):
    assert formats(ebpb) == '<B1xB4s11s8s'
    assert formats(ebpb, prefix='!') == '!B1xB4s11s8s'


def test_get_best_family():
    assert get_best_family('127.0.0.1', 8000) == (socket.AF_INET, ('127.0.0.1', 8000))
    assert get_best_family('::1', 8000) == (socket.AF_INET6, ('::1', 8000, 0, 0))
    with pytest.raises(ValueError):
        get_best_family('127.0.0.1', -1)
    with mock.patch('nobodd.tools.socket.getaddrinfo') as getaddrinfo:
        getaddrinfo.return_value = []
        with pytest.raises(ValueError):
            get_best_family('127.0.0.1', 65538)


def test_format_address():
    assert format_address(('localhost', 80)) == 'localhost:80'
    assert format_address(('127.0.0.1', 8000)) == '127.0.0.1:8000'
    assert format_address(('::1', 1234)) == '[::1]:1234'


def test_buffered_transcoder_read():
    latin1_stream = io.BytesIO('abcdé'.encode('latin-1'))
    utf8_stream = BufferedTranscoder(latin1_stream, 'utf-8', 'latin-1')
    assert utf8_stream.readable()
    assert utf8_stream.read(4) == b'abcd'
    assert utf8_stream.read(1) == b'\xc3'
    assert utf8_stream.read(1) == b'\xa9'
    assert utf8_stream.read(1) == b''


def test_buffered_transcoder_readall():
    latin1_stream = io.BytesIO('abcdé'.encode('latin-1'))
    utf8_stream = BufferedTranscoder(latin1_stream, 'utf-8', 'latin-1')
    assert utf8_stream.readable()
    assert utf8_stream.readall() == b'abcd\xc3\xa9'


def test_buffered_transcoder_readinto():
    latin1_stream = io.BytesIO('abcdé'.encode('latin-1'))
    utf8_stream = BufferedTranscoder(latin1_stream, 'utf-8', 'latin-1')
    assert utf8_stream.readable()
    buf = bytearray(5)
    assert utf8_stream.readinto(buf) == 5
    assert buf == b'abcd\xc3'
    assert utf8_stream.readinto(buf) == 1
    assert buf[:1] == b'\xa9'


def test_buffered_transcoder_identity():
    utf8_stream_1 = io.BytesIO('abcdé'.encode('utf-8'))
    utf8_stream_2 = BufferedTranscoder(utf8_stream_1, 'utf-8')
    assert utf8_stream_2.readable()
    assert utf8_stream_2.readall() == b'abcd\xc3\xa9'


def test_frozendict():
    d = FrozenDict({1: 2, 3: 4})
    assert len(d) == 2
    assert set(d) == {1, 3}
    assert d[1] == 2
    assert hash(d) == hash((frozenset({1, 3}), frozenset({2, 4})))
    # Twice to test cached hash
    assert hash(d) == hash((frozenset({1, 3}), frozenset({2, 4})))
    assert repr(FrozenDict({1: 2})) == "FrozenDict({1: 2})"


def test_decode_timestamp():
    assert decode_timestamp(33, 0, 0) == dt.datetime(
        1980, 1, 1, tzinfo=dt.timezone.utc)
    tz = ZoneInfo('America/New_York')
    assert decode_timestamp(0x2999, 0x645c, 0x32, tz=tz) == dt.datetime(
        2000, 12, 25, 12, 34, 56, 500000, tzinfo=tz)


def test_encode_timestamp():
    with pytest.raises(ValueError):
        encode_timestamp(dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc))
    assert encode_timestamp(
        dt.datetime(1980, 1, 1, tzinfo=dt.timezone.utc)) == (33, 0, 0)
    tz = ZoneInfo('America/New_York')
    assert encode_timestamp(
        dt.datetime(2000, 12, 25, 12, 34, 56, 500000, tzinfo=tz)
    ) == (0x2999, 0x645c, 0x32)


def test_timestamp_roundtrip():
    # Resolution is limited to 10ms units
    tz = dt.timezone.utc
    now = dt.datetime.now(tz=tz)
    now = now.replace(
        microsecond=(now.microsecond // 10000) * 10000)
    assert decode_timestamp(*encode_timestamp(now), tz=tz) == now
    tz = ZoneInfo('America/New_York')
    now = dt.datetime.now(tz=tz)
    now = now.replace(
        microsecond=(now.microsecond // 10000) * 10000)
    assert decode_timestamp(*encode_timestamp(now), tz=tz) == now


def test_exclude():
    r = [range(10)]
    exclude(r, 5)
    assert r == [range(5), range(6, 10)]
    exclude(r, 5)
    assert r == [range(5), range(6, 10)]
    exclude(r, 0)
    assert r == [range(1, 5), range(6, 10)]
    for i in range(1, 5):
        exclude(r, i)
    assert r == [range(6, 10)]
    for i in range(6, 10):
        exclude(r, i)
    assert r == []


def test_any_match():
    r = [
        re.compile('foo'),
        re.compile('bar$'),
        re.compile('(...)bar$'),
    ]
    assert any_match('foobar', r).group() == 'foo'
    assert any_match('foobar', r).span() == (0, 3)
    assert any_match('oobar', r) is None
    assert any_match('bar', r).group() == 'bar'
    assert any_match('bar', r).span() == (0, 3)
    assert any_match('bazbar', r).group() == 'bazbar'
    assert any_match('bazbar', r).groups() == ('baz',)
    assert any_match('bazbar', r).span() == (0, 6)
