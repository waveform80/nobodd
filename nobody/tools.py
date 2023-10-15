import io
import codecs


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
