import io

import pytest

from nobodd.transfer import *


def test_copy_bytes():
    source = io.BytesIO(b"ABCDEFG\x00" * 100000)
    target = io.BytesIO()
    copy_bytes(source, target)
    assert source.getvalue() == target.getvalue()


def test_copy_short_range():
    source = io.BytesIO(b"ABCDEFG\x00" * 100000)
    target = io.BytesIO()
    copy_bytes(source, target, byterange=range(100, 10001))
    assert source.getvalue()[100:10001] == target.getvalue()


def test_copy_range():
    source = io.BytesIO(b"ABCDEFG\x00" * 100000)
    target = io.BytesIO()
    copy_bytes(source, target, byterange=range(100, 90001))
    assert source.getvalue()[100:90001] == target.getvalue()


def test_copy_badrange():
    source = io.BytesIO(b"ABCDEFG\x00" * 100000)
    target = io.BytesIO()
    with pytest.raises(ValueError):
        copy_bytes(source, target, byterange=range(100, 10001, 3))


def test_copy_no_readinto():
    class MySource:
        def __init__(self, data):
            self._pos = 0
            self._data = data

        def read(self, n=-1):
            if n == -1:
                n = len(self._data) - self._pos
            result = self._data[self._pos:self._pos + n]
            self._pos += len(result)
            return result

        def seek(self, pos):
            self._pos = pos

    source = MySource(b"ABCDEFG\x00" * 100000)
    target = io.BytesIO()
    copy_bytes(source, target)
    assert source._data == target.getvalue()

    source.seek(0)
    target = io.BytesIO()
    copy_bytes(source, target, byterange=range(100, 90001))
    assert source._data[100:90001] == target.getvalue()
