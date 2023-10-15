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
    # We can pre-allocate the output array as the transform guarantees the
    # length of output <= length of the input
    buf_in = bytes(s)
    buf_out = bytearray(len(s))
    pos_in = pos_out = consumed = 0
    while pos_in < len(buf_in):
        i = buf_in.find(b'\r', pos_in)
        if i == -1:
            i = len(buf_in)
        if i > pos_in:
            buf_out[pos_out:pos_out + i - pos_in] = buf_in[pos_in:i]
            pos_out += i - pos_in
            pos_in = i
        elif len(buf_in) > pos_in + 1:
            if buf_in[i + 1] == 0x0:
                buf_out[pos_out] = 0xD
                pos_out += 1
                pos_in += 2
            elif buf_in[i + 1] == 0xA:
                buf_out[pos_out:pos_out + len(_netascii_linesep)] = _netascii_linesep
                pos_out += len(_netascii_linesep)
                pos_in += 2
            else:
                err_out = handle_error(errors)
                buf_out[pos_out:pos_out + len(err_out)] = err_out
                pos_out += len(t)
                pos_in += 1
        elif final:
            err_out = handle_error(errors)
            buf_out[pos_out:pos_out + len(err_out)] = err_out
            pos_out += len(t)
            pos_in += 1
            break
    return buf_out[:pos_out].decode('ascii', errors=errors), pos_in

def handle_error(errors):
    if errors == 'strict':
        raise UnicodeError('invalid netascii')
    elif errors == 'ignore':
        return b''
    elif errors == 'replace':
        return b'?'
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
