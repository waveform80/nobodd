import io
import codecs
import socket
import datetime as dt
from itertools import tee
from collections.abc import Mapping


def labels(desc):
    return tuple(
        label
        for line in desc.splitlines()
        if line
        for fmt, label in (line.split(None, 1),)
        if not fmt.endswith('x')
    )


def formats(desc, prefix='<'):
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
    host, port, *extra = address
    if ':' in host:
        return f'[{host}]:{port}'
    else:
        return f'{host}:{port}'


class BufferedTranscoder(io.RawIOBase):
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

    The arguments to ``FrozenDict`` are processed just like those to ``dict``.
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


def pairwise(it):
    a, b = tee(it)
    next(b, None)
    return zip(a, b)


def decode_timestamp(date, time, ms=0):
    """
    Given the integers *date*,  *time*, and optionally *ms* (from various
    fields in :class:`~nobodd.fat.DirectoryEntry`), return a
    :class:`~datetime.datetime` with the decoded timestamp.
    """
    return dt.datetime(
        year=1980 + ((date & 0xFE00) >> 9),
        month=(date & 0x1E0) >> 5,
        day=(date & 0x1F),
        hour=(time & 0xF800) >> 11,
        minute=(time & 0x7E0) >> 5,
        second=(time & 0x1F) * 2 + (ms // 1000),
        microsecond=(ms % 100) * 1000
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
        (ts.hour << 1) | (ts.minute << 5) | (ts.second // 2),
        ((ts.second % 2) * 1000 + (ts.microsecond // 1000)) // 10
    )
