# nobodd: a boot configuration tool for the Raspberry Pi
#
# Copyright (c) 2023-2024 Dave Jones <dave.jones@canonical.com>
# Copyright (c) 2023-2024 Canonical Ltd.
#
# SPDX-License-Identifier: GPL-3.0

import io
import codecs
import socket
import datetime as dt
from itertools import tee
from collections.abc import Mapping

# TODO Remove except when compatibility moves beyond Python 3.10
try:
    from itertools import pairwise
except ImportError:
    pairwise = None


def labels(desc):
    """
    Given the description of a C structure in *desc*, returns a tuple of the
    labels.

    The :class:`str` *desc* must contain one entry per line (blank lines are
    ignored) where each entry consists of whitespace separated type (in Python
    :mod:`struct` format) and label. For example::

        >>> EBPB = '''
        B     drive_number
        1x    reserved
        B     extended_boot_sig
        4s    volume_id
        11s   volume_label
        8s    file_system
        '''
        >>> labels(EBPB)
        ('drive_number', 'extended_boot_sig', 'volume_id', 'volume_label',
        'file_system')

    Note the amount of whitespace is arbitrary, and further that any entries
    with the type "x" (which is used to indicate padding) will be excluded from
    the result ("reserved" is missing from the result tuple above).

    The corresponding function :func:`formats` can be used to obtain a tuple
    of the types.
    """
    return tuple(
        label
        for line in desc.splitlines()
        if line
        for fmt, label in (line.split(None, 1),)
        if not fmt.endswith('x')
    )


def formats(desc, prefix='<'):
    """
    Given the description of a C structure in *desc*, returns a concatenated
    :class:`str` of the types with an optional *prefix* (for endianness).

    The :class:`str` *desc* must contain one entry per line (blank lines are
    ignored) where each entry consists of whitespace separated type (in Python
    :mod:`struct` format) and label. For example::

        >>> EBPB = '''
        B     drive_number
        1x    reserved
        B     extended_boot_sig
        4s    volume_id
        11s   volume_label
        8s    file_system
        '''
        >>> formats(EBPB)
        '<B1xB4s11s8s'

    Note the amount of whitespace is arbitrary, and further that any entries
    with the type "x" (which is used to indicate padding) are *not* excluded
    (unlike in :func:`labels`).

    The corresponding function :func:`labels` can be used to obtain a tuple
    of the labels.
    """
    return prefix + ''.join(
        fmt
        for line in desc.splitlines()
        if line
        for fmt, label in (line.split(None, 1),)
    )


def get_best_family(host, port):
    """
    Given a *host* name and a *port* specification (either a number or a
    service name), returns the network family (e.g. ``socket.AF_INET``) and
    socket address to listen on as a tuple.
    """
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_UDP)
    except socket.gaierror as exc:
        raise ValueError('invalid host and port combination') from exc
    for family, _, _, _, sockaddr in infos:
        return family, sockaddr
    raise ValueError('invalid host and port combination')


def format_address(address):
    """
    Given a socket *address*, return a suitable :class:`str` representation of
    it.

    Specifically, for IP4 addresses a simple "host:port" representation is
    used. For IP6 addresses (which typically incorporate ":" in the host
    portion), a "[host]:port" variant is used.
    """
    host, port, *extra = address
    if ':' in host:
        return f'[{host}]:{port}'
    else:
        return f'{host}:{port}'


class BufferedTranscoder(io.RawIOBase):
    """
    A read-only transcoder, somewhat similar to :class:`codecs.StreamRecoder`,
    but which strictly obeys the definition of the ``read`` method (with
    internal buffering).

    This class is primarily intended for use in :mod:`~nobodd.netascii` encoded
    transfers where it is used to transcode the underlying file stream into
    netascii encoding for the TFTP server.

    The built-in :class:`codecs.StreamRecoder` class would seem ideal for this
    but for one issue: under certain circumstances (including those involved in
    netascii encoding), it violates the contract of the ``read`` method by
    returning *more* bytes than requested. For example::

        >>> import io, codecs
        >>> latin1_stream = io.BytesIO('abcdé'.encode('latin-1'))
        >>> utf8_stream = codecs.StreamRecoder(latin1_stream,
        ... codecs.getencoder('utf-8'), codecs.getdecoder('utf-8'),
        ... codecs.getreader('latin-1'), codecs.getwriter('latin-1'))
        >>> utf8_stream.read(3)
        b'abc'
        >>> utf8_stream.read(1)
        b'd'
        >>> utf8_stream.read(1)
        b'\\xc3\\xa9'

    This is alluded to in the documentation of :class:`StreamReader.read` so it
    probably isn't a bug, but it is rather inconvenient when the caller is
    looking to fill a network packet of a specific size, and thus expects not
    to over-run.

    This class implements a rather simpler recoder, which is read-only, does
    not permit seeking, but by use of an internal buffer, guarantees that the
    :meth:`read` method (and associated methods like :meth:`readinto`) will
    not return more bytes than requested.

    It is constructed with the underlying *stream*, the name of the
    *output_encoding*, the name of the *input_encoding* (which defaults to the
    *output_encoding* when not specified), and the *errors* mode to use with
    the codecs. For example::

        >>> import io
        >>> from nobodd.tools import BufferedTranscoder
        >>> latin1_stream = io.BytesIO('abcdé'.encode('latin-1'))
        >>> utf8_stream = BufferedTranscoder(latin1_stream, 'utf-8', 'latin-1')
        >>> utf8_stream.read(4)
        b'abcd'
        >>> utf8_stream.read(1)
        b'\\xc3'
        >>> utf8_stream.read(1)
        b'\\xa9'
    """
    def __init__(self, stream, output_encoding, input_encoding=None,
                 errors='strict'):
        if input_encoding is None:
            input_encoding = output_encoding
        self._source = codecs.getreader(input_encoding)(stream, errors)
        self._encode = codecs.getencoder(output_encoding)
        self._buffer = bytearray()

    def readable(self):
        return True

    def readall(self):
        result = self._buffer + self._encode(self._source.read())[0]
        del self._buffer[:]
        return result

    def readinto(self, b):
        while len(self._buffer) < len(b):
            s = self._source.read(4096)
            if not s:
                break
            self._buffer.extend(self._encode(s)[0])
        to_read = min(len(b), len(self._buffer))
        b[:to_read] = self._buffer[:to_read]
        del self._buffer[:to_read]
        return to_read


class FrozenDict(Mapping):
    """
    A hashable, immutable mapping type.

    The arguments to :class:`FrozenDict` are processed just like those to
    :class:`dict`.
    """
    def __init__(self, *args):
        self._d = dict(*args)
        self._hash = None

    def __iter__(self):
        return iter(self._d)

    def __len__(self):
        return len(self._d)

    def __getitem__(self, key):
        return self._d[key]

    def __repr__(self):
        return f'{self.__class__.__name__}({self._d})'

    def __hash__(self):
        if self._hash is None:
            self._hash = hash((frozenset(self), frozenset(self.values())))
        return self._hash


# TODO Remove except when compatibility moves beyond Python 3.10
if pairwise is None:
    def pairwise(it):
        """
        Return successive overlapping pairs taken from the input iterable.

        The number of 2-tuples in the output iterator will be one fewer than
        the number of inputs. It will be empty if the input iterable has fewer
        than two values.
        """
        a, b = tee(it)
        next(b, None)
        return zip(a, b)


def decode_timestamp(date, time, cs=0):
    """
    Given the integers *date*,  *time*, and optionally *cs* (from various
    fields in :class:`~nobodd.fat.DirectoryEntry`), return a
    :class:`~datetime.datetime` with the decoded timestamp.
    """
    ms = cs * 10
    return dt.datetime(
        year=1980 + ((date & 0xFE00) >> 9),
        month=(date & 0x1E0) >> 5,
        day=(date & 0x1F),
        hour=(time & 0xF800) >> 11,
        minute=(time & 0x7E0) >> 5,
        second=(time & 0x1F) * 2 + (ms // 1000),
        microsecond=(ms % 1000) * 1000
    )


def encode_timestamp(ts):
    """
    Given a :class:`~datetime.datetime`, encode it as a FAT-compatible triple
    of three 16-bit integers representing (date, time, 1/100th seconds).
    """
    if not dt.datetime(1980, 1, 1) <= ts < dt.datetime(2100, 1, 1):
        raise ValueError(f'{ts} is outside the valid range for FAT timestamps')
    return (
        ((ts.year - 1980) << 9) | (ts.month << 5) | ts.day,
        (ts.hour << 11) | (ts.minute << 5) | (ts.second // 2),
        ((ts.second % 2) * 1000 + (ts.microsecond // 1000)) // 10
    )


def exclude(ranges, value):
    """
    Given a list non-overlapping of *ranges*, sorted in ascending order, this
    function modifies the range containing *value* (an integer, which must
    belong to one and only one range in the list) to exclude it.
    """
    for i, r in enumerate(ranges):
        if value in r:
            break
    else:
        return
    ranges[i:i + 1] = [
        r for r in (range(r.start, value), range(value + 1, r.stop)) if r]


def any_match(s, expressions):
    """
    Given a :class:`str` *s*, and *expressions*, a sequence of compiled
    regexes, return the :class:`re.Match` object from the first regex that
    matches *s*. If no regexes match, return :data:`None`.
    """
    for exp in expressions:
        m = exp.match(s)
        if m:
            return m
    return None
