import io
import codecs
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
