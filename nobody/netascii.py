import io
import os
import re
import codecs


_netascii_linesep = os.linesep.encode('ascii')
_netascii_re = re.compile(fr'({os.linesep}|\r)'.encode('ascii'))
def _netascii_match(m):
    if m.group(0) == b'\r':
        return b'\r\0'
    elif m.group(0) == _netascii_linesep:
        return b'\r\n'
    assert False, 'netascii encode mismatch'

def encode(s, errors='strict'):
    return _netascii_re.sub(
        _netascii_match, s.encode('ascii', errors=errors)), len(s)

def decode(s, errors='strict', final=False):
    s = bytes(s)
    buf = ''
    consumed = 0
    while s:
        i = s.find(b'\r')
        if i == -1:
            buf += s.decode('ascii', errors=errors)
            consumed += len(s)
            break
        elif i > 0:
            buf += s[:i].decode('ascii', errors=errors)
            s = s[i:]
            consumed += i
        elif len(s) > 1:
            if s[1] == 0x0:
                buf += '\r'
                s = s[2:]
                consumed += 2
            elif s[1] == 0xA:
                buf += os.linesep
                s = s[2:]
                consumed += 1
            else:
                buf += handle_error(errors)
                s = s[1:]
                consumed += 1
        elif final:
            buf += handle_error(errors)
            consumed += 1
            break
    return buf, consumed

def handle_error(errors):
    if errors == 'strict':
        raise UnicodeError('invalid netascii')
    elif errors == 'ignore':
        return ''
    elif errors == 'replace':
        return '?'
    else:
        raise ValueError('invalid errors setting for netascii')

class IncrementalEncoder(codecs.IncrementalEncoder):
    def encode(self, input, final=False):
        return encode(input, self.errors)[0]

class IncrementalDecoder(codecs.BufferedIncrementalDecoder):
    _buffer_decode = decode

class StreamWriter(codecs.StreamWriter):
    def encode(self, s, errors='strict'):
        return encode(s, errors)

class StreamReader(codecs.StreamReader):
    def decode(self, s, errors='strict', final=False):
        return decode(s, errors, final)

stateless_encode = encode

def stateless_decode(s, errors='strict'):
    with StreamReader(io.BytesIO(s), errors) as stream:
        return stream.read(), len(s)


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
