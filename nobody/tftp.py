import re
import struct
from enum import IntEnum, auto

from .tools import labels, formats, FrozenDict


# The following references were essential in constructing this module; the
# original TFTP version 2 [RFC1350], and the wikipedia page documenting the
# protocol [1].
#
# [1]: https://en.wikipedia.org/wiki/Trivial_File_Transfer_Protocol
# [RFC1350]: https://datatracker.ietf.org/doc/html/rfc1350


TFTP_BLKSIZE = 'blksize'
TFTP_MIN_BLKSIZE = 8
TFTP_DEF_BLKSIZE = 512
TFTP_MAX_BLKSIZE = 65464

TFTP_TIMEOUT = 'timeout'
TFTP_UTIMEOUT = 'utimeout'
TFTP_MIN_TIMEOUT_NS = 10_000_000 # 10ms
TFTP_MAX_TIMEOUT_NS = 255_000_000_000 # 255s
TFTP_DEF_TIMEOUT_NS = 1_000_000_000 # 1s

TFTP_BINARY = 'octet'
TFTP_NETASCII = 'netascii'
TFTP_MODES = {TFTP_BINARY, TFTP_NETASCII}

TFTP_TSIZE = 'tsize'
TFTP_OPTIONS = {TFTP_TSIZE, TFTP_BLKSIZE, TFTP_TIMEOUT, TFTP_UTIMEOUT}


class OpCode(IntEnum):
    RRQ = 1
    WRQ = auto()
    DATA = auto()
    ACK = auto()
    ERROR = auto()
    OACK = auto()


class Error(IntEnum):
    UNDEFINED = 0
    NOT_FOUND = auto()
    NOT_AUTH = auto()
    DISK_FULL = auto()
    BAD_OP = auto()
    UNKNOWN_ID = auto()
    EXISTS = auto()
    UNKNOWN_USER = auto()
    INVALID_OPT = auto()


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
            OpCode.OACK:  OACKPacket,
        }[opcode].from_data(s[2:])

    @classmethod
    def from_data(cls, data):
        raise NotImplementedError()


class RRQPacket(Packet):
    __slots__ = ('filename', 'mode', 'options')
    opcode = OpCode.RRQ
    options_re = re.compile(
        rb'(?P<name>[\x20-\xFF]+)\0(?P<value>[\x01-\xFF]*)\0')
    packet_re = re.compile(
        rb'^'
        rb'(?P<filename>[\x20-\xFF]+)\0'
        rb'(?P<mode>[a-zA-Z]+)\0'
        rb'(?P<options>(?:[\x20-\xFF]+\0[\x01-\xFF]*\0)*)'
        rb'.*')

    def __init__(self, filename, mode, options):
        self.filename = str(filename)
        self.mode = str(mode).lower()
        self.options = FrozenDict(options)

    def __bytes__(self):
        return b''.join((
            struct.pack('!H', self.opcode),
            self.filename.encode('ascii'), b'\0',
            self.mode.encode('ascii'), b'\0',
            b''.join(tuple(
                s
                for name, value in self.options.items()
                for s in (
                    name.encode('ascii'), b'\0',
                    value.encode('ascii'), b'\0',
                )
            )),
        ))

    @classmethod
    def from_data(cls, data):
        try:
            filename, mode, suffix = cls.packet_re.match(data).groups()
        except AttributeError:
            raise ValueError('badly formed RRQ packet')
        # Technically the filename must be in ASCII format (7-bit chars in an
        # 8-bit field), but given ASCII is a strict subset of UTF-8, and that
        # UTF-8 cannot include NUL chars, I see no harm in permitting UTF-8
        # encoded filenames
        filename = filename.decode('utf-8')
        mode = mode.decode('ascii').lower()
        if mode not in TFTP_MODES:
            raise ValueError('unsupported file mode')
        options = {
            match.group('name').decode('ascii').lower():
                match.group('value').decode('ascii').lower()
            for match in cls.options_re.finditer(suffix)
        }
        return cls(filename, mode, options)


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


class OACKPacket(Packet):
    __slots__ = ('options',)
    opcode = OpCode.OACK
    options_re = RRQPacket.options_re

    def __init__(self, options):
        self.options = FrozenDict(options)

    def __bytes__(self):
        return struct.pack('!H', self.opcode) + b''.join(tuple(
            s
            for name, value in self.options.items()
            for s in (
                name.encode('ascii'), b'\0',
                str(value).encode('ascii'), b'\0',
            )
        ))

    @classmethod
    def from_data(cls, data):
        options = {
            match.group('name').decode('ascii').lower():
                match.group('value').decode('ascii').lower()
            for match in cls.options_re.finditer(suffix)
        }
        return cls(options)
