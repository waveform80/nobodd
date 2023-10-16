import struct
from enum import IntEnum, auto

from .tools import labels, formats


# The following references were essential in constructing this module; the
# original TFTP version 2 [RFC1350], and the wikipedia page documenting the
# protocol [1].
#
# [1]: https://en.wikipedia.org/wiki/Trivial_File_Transfer_Protocol
# [RFC1350]: https://datatracker.ietf.org/doc/html/rfc1350


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
            OpCode.RRQ:   RRQPacket,
            OpCode.DATA:  DATAPacket,
            OpCode.ACK:   ACKPacket,
            OpCode.ERROR: ERRORPacket,
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
