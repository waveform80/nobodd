import io
import os
import codecs

import pytest

from nobodd.netascii import *


def test_encode():
    assert ''.encode('netascii') == b''
    assert 'foo'.encode('netascii') == b'foo'
    assert f'foo{os.linesep}bar'.encode('netascii') == b'foo\r\nbar'
    assert 'lf\n crlf\r\n cr\r eof'.encode('netascii') == {
        '\r':   b'lf\n crlf\r\n\n cr\r\n eof',
        '\n':   b'lf\r\n crlf\r\0\r\n cr\r\0 eof',
        '\r\n': b'lf\n crlf\r\n cr\r\0 eof',
    }[os.linesep]


def test_decode():
    assert b''.decode('netascii') == ''
    assert b'foo'.decode('netascii') == 'foo'
    assert b'foo\r\nbar'.decode('netascii') == f'foo{os.linesep}bar'
    assert {
        '\r':   b'lf\n crlf\r\n\n cr\r\n eof',
        '\n':   b'lf\r\n crlf\r\0\r\n cr\r\0 eof',
        '\r\n': b'lf\n crlf\r\n cr\r\0 eof',
    }[os.linesep].decode('netascii') == 'lf\n crlf\r\n cr\r eof'


def test_decode_errors():
    with pytest.raises(UnicodeError):
        b'crcr\r\r'.decode('netascii', errors='strict')
    assert b'crcr\r\r'.decode('netascii', errors='replace') == 'crcr??'
    assert b'crcr\r\r'.decode('netascii', errors='ignore') == 'crcr'
    with pytest.raises(ValueError):
        b'crcr\r\r'.decode('netascii', errors='foo')


def test_incremental_encoder():
    assert list(codecs.iterencode([''], 'netascii')) == []
    assert list(codecs.iterencode(['fo', 'o'], 'netascii')) == [b'fo', b'o']
    assert list(codecs.iterencode(['foo', os.linesep, 'bar'], 'netascii')) == [
        b'foo', b'\r\n', b'bar']
    assert b''.join(codecs.iterencode([
        f'foo{os.linesep[0]}', f'{os.linesep[1:]}bar'
    ], 'netascii')) == b'foo\r\nbar'
    assert list(codecs.iterencode(['foo', '\r', 'bar\r'], 'netascii')) == {
        '\r':   [b'foo', b'\r\n', b'bar\r\n'],
        '\n':   [b'foo', b'\r\0', b'bar\r\0'],
        '\r\n': [b'foo', b'\r\0bar', b'\r\0'],
    }[os.linesep]
    assert list(codecs.iterencode(['lf\n ', 'crlf\r\n ', 'cr\r ', 'eof'], 'netascii')) == {
        '\r':   [b'lf\n ', b'crlf\r\n\n ', b'cr\r\n ', b'eof'],
        '\n':   [b'lf\r\n ', b'crlf\r\0\r\n ', b'cr\r\0 ', b'eof'],
        '\r\n': [b'lf\n ', b'crlf\r\n ', b'cr\r\0 ', b'eof'],
    }[os.linesep]


def test_incremental_decoder():
    assert list(codecs.iterdecode([b''], 'netascii')) == []
    assert list(codecs.iterdecode([b'fo', b'o'], 'netascii')) == ['fo', 'o']
    assert list(codecs.iterdecode([b'foo\r', b'\nbar'], 'netascii')) == ['foo', f'{os.linesep}bar']
    assert list(codecs.iterdecode({
        '\r':   [b'lf\n ', b'crlf\r\n\n ', b'cr\r\n ', b'eof'],
        '\n':   [b'lf\r\n ', b'crlf\r\0\r\n ', b'cr\r\0 ', b'eof'],
        '\r\n': [b'lf\n ', b'crlf\r\n ', b'cr\r\0 ', b'eof'],
    }[os.linesep], 'netascii')) == ['lf\n ', 'crlf\r\n ', 'cr\r ', 'eof']


def test_stream_writer():
    with io.BytesIO() as buf, codecs.getwriter('netascii')(buf) as writer:
        writer.write('')
        assert buf.getvalue() == b''
        writer.write('foo')
        assert buf.getvalue() == b'foo'
        writer.write('\r')
        assert buf.getvalue() == {
            '\r':   b'foo\r\n',
            '\n':   b'foo\r\0',
            '\r\n': b'foo',
        }[os.linesep]
        writer.write('\n')
        assert buf.getvalue() == {
            '\r':   b'foo\r\n\n',
            '\n':   b'foo\r\0\r\n',
            '\r\n': b'foo\r\n',
        }[os.linesep]
        writer.write('\r')
        writer.flush()
        assert buf.getvalue() == {
            '\r':   b'foo\r\n\n\r\n',
            '\n':   b'foo\r\0\r\n\r\0',
            '\r\n': b'foo\r\n\r\0',
        }[os.linesep]


def test_stream_reader():
    with io.BytesIO() as buf, codecs.getreader('netascii')(buf, errors='replace') as reader:
        buf.write(b'foo\r\nbar\r\0\r\r')
        buf.seek(0)
        assert reader.read(0) == ''
        assert reader.read(3) == 'foo'
        assert reader.read(len(os.linesep)) == os.linesep
        assert reader.read(3) == 'bar'
        assert reader.read(1) == '\r'
        assert reader.read(1) == '?'
