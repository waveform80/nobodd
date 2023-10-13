import struct
from enum import IntEnum, auto
from collections import namedtuple
from socketserver import DatagramRequestHandler, ThreadingUDPServer

from . import netascii
from .tools import labels, formats


class OpCode(IntEnum):
    RRQ = 1
    WRQ = auto()
    DATA = auto()
    ACK = auto()
    ERROR = auto()


class Error(IntEnum):
    UNDEFINED = 0
    NOT_FOUND = auto()
    NOT_AUTH = auto()
    DISK_FULL = auto()
    BAD_OP = auto()
    UNKNOWN_ID = auto()
    EXISTS = auto()
    UNKNOWN_USER = auto()


class Packet:
    __slots__ = ()
    opcode = None

    def __repr__(self):
        fields = ', '.join(
            f'{field}={getattr(self, field)!r}'
            for field in self.__class__.__slots__)
        return f'{self.__class__.__name__}({fields})'

    @classmethod
    def from_bytes(cls, s):
        opcode, = struct.unpack_from('!H', s)
        return {
            OpCode.RRQ:   RRQ,
            OpCode.DATA:  DATA,
            OpCode.ACK:   ACK,
            OpCode.ERROR: ERROR,
        }[opcode].from_data(s[2:])

    @classmethod
    def from_data(cls, data):
        raise NotImplementedError()


class RRQPacket(Packet):
    __slots__ = ('filename', 'mode')
    opcode = OpCode.RRQ

    def __init__(self, filename, mode):
        self.filename = str(filename)
        self.mode = str(mode).lower()

    def __bytes__(self):
        return struct.pack(
            f'!H{len(self.filename)}sx{len(self.mode)}sx',
            self.opcode, self.filename.encode('ascii'),
            self.mode.encode('ascii'))

    @classmethod
    def from_data(cls, data):
        filename, mode = data.split(b'\0', 1)
        # Technically the filename must be in ASCII format (7-bit chars in an
        # 8-bit field), but given ASCII is a strict subset of UTF-8, and that
        # UTF-8 cannot include NUL chars, I see no harm in permitting UTF-8
        # encoded filenames
        filename = filename.decode('utf-8')
        mode = mode.rstrip(b'\0').decode('ascii').lower()
        if mode not in ('netascii', 'octet'):
            raise ValueError('unsupported file mode')
        return cls(filename, mode)


class DATAPacket(Packet):
    __slots__ = ('block', 'data')
    opcode = OpCode.DATA

    def __init__(self, block, data):
        self.block = int(block)
        self.data = bytes(data)

    def __bytes__(self):
        return struct.pack(
            f'!HH{len(self.data)}s', self.opcode, self.block, self.data)

    @classmethod
    def from_data(cls, data):
        block, = struct.unpack_from('!H', data)
        return cls(block, data[2:])


class ACKPacket(Packet):
    __slots__ = ('block',)
    opcode = OpCode.ACK

    def __init__(self, block):
        self.block = int(block)

    def __bytes__(self):
        return struct.pack(f'!HH', self.opcode, self.block)

    @classmethod
    def from_data(cls, data):
        block, = struct.unpack_from('!H', data)
        return cls(block)


class ERRORPacket(Packet):
    __slots__ = ('error', 'message')
    opcode = OpCode.ERROR

    def __init__(self, error, message=None):
        self.error = Error(error)
        if message is None:
            self.message = {
                Error.UNDEFINED:    'Undefined error',
                Error.NOT_FOUND:    'File not found',
                Error.NOT_AUTH:     'Access violation',
                Error.DISK_FULL:    'Disk full or allocation exceeded',
                Error.BAD_OP:       'Illegal TFTP operation',
                Error.UNKNOWN_ID:   'Unknown transfer ID',
                Error.EXISTS:       'File already exists',
                Error.UNKNOWN_USER: 'No such user',
            }[self.error]
        else:
            self.message = str(message)

    def __bytes__(self):
        return struct.pack(
            f'!HH{len(self.message)}sx', self.opcode, self.error,
            self.message.encode('ascii'))

    @classmethod
    def from_data(cls, data):
        error, = struct.unpack_from('!H', data)
        return cls(error, data[2:].rstrip(b'\0').decode('ascii', 'replace'))


class TFTPHandler(DatagramRequestHandler):
    def handle(self):
        try:
            packet = Packet.from_bytes(self.rfile.read())
            handler = getattr(self, 'do_' + packet.opcode.name)
            response = handler(packet)
        except AttributeError as exc:
            response = (
                ERRORPacket(Error.UNDEFINED, 'Unsupported operation, {exc!s}'),)
        except ValueError as exc:
            response = (
                ERRORPacket(Error.UNDEFINED, f'Invalid request, {exc!s}'),)
        except:
            response = (ERRORPacket(Error.UNDEFINED, 'Server error'),)
        finally:
            self.send_response(response)

    def send_response(self, packets):
        for packet in packets:
            self.wfile.write(packet.as_bytes)
            self.wfile.flush()

    def do_RRQ(self, packet):
        pass

    def do_ACK(self, packet):
        pass

    def do_ERROR(self, packet):
        pass


class TFTPServer(ThreadingUDPServer):
    allow_reuse_address = True
    allow_reuse_port = True
