# nobodd: a boot configuration tool for the Raspberry Pi
#
# Copyright (c) 2023-2024 Dave Jones <dave.jones@canonical.com>
# Copyright (c) 2023-2024 Canonical Ltd.
#
# SPDX-License-Identifier: GPL-3.0

import os
import codecs

from . import lang


# The following references were essential in constructing this module; the
# original TELNET specification [RFC764], and the wikipedia page documenting
# the TFTP protocol [1].
#
# [1]: https://en.wikipedia.org/wiki/Trivial_File_Transfer_Protocol
# [RFC764]: https://datatracker.ietf.org/doc/html/rfc764
# [RFC1350]: https://datatracker.ietf.org/doc/html/rfc1350


_netascii_linesep = os.linesep.encode('ascii')

def encode(s, errors='strict', final=False):
    """
    Encodes the :class:`str` *s*, which must only contain valid ASCII
    characters, to the netascii :class:`bytes` representation.

    The *errors* parameter specifies the handling of encoding errors in the
    typical manner ('strict', 'ignore', 'replace', etc). The *final* parameter
    indicates whether this is the end of the input. This only matters on the
    Windows platform where the line separator is '\\r\\n' in which case a
    trailing '\\r' character *may* be the start of a newline sequence.

    The return value is a tuple of the encoded :class:`bytes` string, and the
    number of characters consumed from *s* (this may be less than the length of
    *s* when *final* is :data:`False`).
    """
    # We can pre-allocate the output array as the transform guarantees the
    # length of output <= 2 * length of the input (largest transform in all
    # cases is b'\r' -> b'\r\0')
    buf_in = s.encode('ascii', errors=errors)
    buf_out = bytearray(len(buf_in) * 2)
    pos_in = pos_out = 0

    def encode_newline():
        nonlocal buf_out, pos_out, pos_in
        buf_out[pos_out:pos_out + 2] = b'\r\n'
        pos_out += 2
        pos_in += len(_netascii_linesep)

    def encode_cr():
        nonlocal buf_out, pos_out, pos_in
        buf_out[pos_out:pos_out + 2] = b'\r\0'
        pos_out += 2
        pos_in += 1

    while pos_in < len(buf_in):
        i = min(
            len(buf_in) if j == -1 else j
            for j in (
                buf_in.find(_netascii_linesep[0], pos_in),
                buf_in.find(b'\r', pos_in),
            )
        )
        if i > pos_in:
            buf_out[pos_out:pos_out + i - pos_in] = buf_in[pos_in:i]
            pos_out += i - pos_in
            pos_in = i
        elif len(_netascii_linesep) == 1:
            # Non-windows case
            if buf_in[i] == _netascii_linesep[0]:
                encode_newline()
            else: # buf_in[i] == b'\r'[0]
                encode_cr()
        else:
            # Windows case
            if len(buf_in) > pos_in + 1:
                if buf_in[i + 1] == _netascii_linesep[1]:
                    encode_newline()
                else:
                    encode_cr()
            else:
                if final:
                    encode_cr()
                break
    return bytes(buf_out[:pos_out]), pos_in


def decode(s, errors='strict', final=False):
    """
    Decodes the :class:`bytes` string *s*, which must contain a netascii
    encoded string, to the :class:`str` representation (which can only contain
    ASCII characters).

    The *errors* parameter specifies the handling of encoding errors in the
    typical manner ('strict', 'ignore', 'replace', etc). The *final* parameter
    indicates whether this is the end of the input. This matters as a trailing
    '\\r' in the input is the beginning of a newline sequence, an encoded
    '\\r', or an error (in other cases).

    The return value is a tuple of the decoded :class:`str`, and the number of
    characters consumed from *s* (this may be less than the length of *s* when
    *final* is :data:`False`).
    """
    # We can pre-allocate the output array as the transform guarantees the
    # length of output <= length of the input
    buf_in = bytes(s)
    buf_out = bytearray(len(buf_in))
    pos_in = pos_out = 0
    while pos_in < len(buf_in):
        i = buf_in.find(b'\r', pos_in)
        if i == -1:
            i = len(buf_in)
        if i > pos_in:
            buf_out[pos_out:pos_out + i - pos_in] = buf_in[pos_in:i]
            pos_out += i - pos_in
            pos_in = i
        elif len(buf_in) > pos_in + 1:
            if buf_in[i + 1] == 0x0: # b'\0'
                buf_out[pos_out] = 0xD # b'\r'
                pos_out += 1
                pos_in += 2
            elif buf_in[i + 1] == 0xA: # b'\n'
                buf_out[pos_out:pos_out + len(_netascii_linesep)] = _netascii_linesep
                pos_out += len(_netascii_linesep)
                pos_in += 2
            else:
                err_out = handle_error(errors)
                buf_out[pos_out:pos_out + len(err_out)] = err_out
                pos_out += len(err_out)
                pos_in += 1
        else:
            if final:
                err_out = handle_error(errors)
                buf_out[pos_out:pos_out + len(err_out)] = err_out
                pos_out += len(err_out)
                pos_in += 1
            break
    return buf_out[:pos_out].decode('ascii', errors=errors), pos_in

def handle_error(errors):
    if errors == 'strict':
        raise UnicodeError(lang._('invalid netascii'))
    elif errors == 'ignore':
        return b''
    elif errors == 'replace':
        return b'?'
    else:
        raise ValueError(lang._('invalid errors setting for netascii'))


class IncrementalEncoder(codecs.BufferedIncrementalEncoder):
    r"""
    Use :func:`codecs.iterencode` to utilize this class for encoding:

    .. code-block:: pycon

        >>> import os
        >>> os.linesep
        '\n'
        >>> import nobodd.netascii
        >>> import codecs
        >>> it = ['foo', '\n', 'bar\r']
        >>> b''.join(codecs.iterencode(it, 'netascii'))
        b'foo\r\nbar\r\0'
    """
    @staticmethod
    def _buffer_encode(s, errors, final=False):
        return encode(s, errors, final)

class IncrementalDecoder(codecs.BufferedIncrementalDecoder):
    r"""
    Use :func:`codecs.iterdecode` to utilize this class for encoding:

    .. code-block:: pycon

        >>> import os
        >>> os.linesep
        '\n'
        >>> import nobodd.netascii
        >>> import codecs
        >>> it = [b'foo\r', b'\n', b'bar\r', b'\0']
        >>> ''.join(codecs.iterdecode(it, 'netascii'))
        'foo\nbar\r'
    """
    @staticmethod
    def _buffer_decode(s, errors, final=False):
        return decode(s, errors, final)


class StreamWriter(codecs.StreamWriter):
    def __init__(self, stream, errors='strict'):
        super().__init__(stream, errors)
        self._final = False
        self.reset()

    def encode(self, s, errors='strict'):
        encoded, consumed = encode(self._buf + s, errors, final=self._final)
        self._buf = (self._buf + s)[consumed:]
        return encoded, consumed

    def flush(self):
        self._final = True
        try:
            self.write('')
            self.stream.flush()
        finally:
            self._final = False

    def reset(self):
        super().reset()
        self._buf = ''

class StreamReader(codecs.StreamReader):
    def decode(self, s, errors='strict', final=False):
        return decode(s, errors, final)


def stateless_encode(s, errors='strict'):
    return encode(s, errors, final=True)

def stateless_decode(s, errors='strict'):
    return decode(s, errors, final=True)


def find_netascii(name):
    if name.lower() == 'netascii':
        return codecs.CodecInfo(
            name='netascii',
            encode=stateless_encode,
            decode=stateless_decode,
            incrementalencoder=IncrementalEncoder,
            incrementaldecoder=IncrementalDecoder,
            streamreader=StreamReader,
            streamwriter=StreamWriter,
        )

codecs.register(find_netascii)
