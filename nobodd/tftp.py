# nobodd: a boot configuration tool for the Raspberry Pi
#
# Copyright (c) 2023-2024 Dave Jones <dave.jones@canonical.com>
# Copyright (c) 2023-2024 Canonical Ltd.
#
# SPDX-License-Identifier: GPL-3.0

import re
import struct
from enum import IntEnum

from . import lang
from .tools import labels, formats, FrozenDict


# The following references were essential in constructing this module; the
# original TFTP version 2 [RFC1350], the TFTP option extension [RFC2347], and
# the wikipedia page documenting the protocol [1].
#
# [1]: https://en.wikipedia.org/wiki/Trivial_File_Transfer_Protocol
# [RFC1350]: https://datatracker.ietf.org/doc/html/rfc1350
# [RFC2347]: https://datatracker.ietf.org/doc/html/rfc2347


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
TFTP_MODES = frozenset({TFTP_BINARY, TFTP_NETASCII})

TFTP_TSIZE = 'tsize'
TFTP_OPTIONS = frozenset({TFTP_TSIZE, TFTP_BLKSIZE, TFTP_TIMEOUT,
                          TFTP_UTIMEOUT})


class OpCode(IntEnum):
    """
    Enumeration of op-codes for the `Trivial File Transfer Protocol`_ (TFTP).
    These appear at the start of any TFTP packet to indicate what sort of
    packet it is.

    .. _Trivial File Transfer Protocol: https://en.wikipedia.org/wiki/Trivial_File_Transfer_Protocol
    """
    RRQ   = 1
    WRQ   = 2
    DATA  = 3
    ACK   = 4
    ERROR = 5
    OACK  = 6


class Error(IntEnum):
    """
    Enumeration of error status for the `Trivial File Transfer Protocol`_
    (TFTP). These are used in packets with :class:`OpCode` ``ERROR`` to
    indicate the sort of error that has occurred.

    .. _Trivial File Transfer Protocol: https://en.wikipedia.org/wiki/Trivial_File_Transfer_Protocol
    """
    UNDEFINED    = 0
    NOT_FOUND    = 1
    NOT_AUTH     = 2
    DISK_FULL    = 3
    BAD_OP       = 4
    UNKNOWN_ID   = 5
    EXISTS       = 6
    UNKNOWN_USER = 7
    INVALID_OPT  = 8


class Packet:
    """
    Abstract base class for all TFTP packets. This provides the class method
    :meth:`Packet.from_bytes` which constructs and returns the appropriate
    concrete sub-class for the :class:`OpCode` found at the beginning of the
    packet's data.

    Instances of the concrete classes may be converted back to :class:`bytes`
    simply by calling :class:`bytes` on them::

        >>> b = b'\\x00\\x01config.txt\\0octet\\0'
        >>> r = Packet.from_bytes(b)
        >>> r
        RRQPacket(filename='config.txt', mode='octet', options=FrozenDict({}))
        >>> bytes(r)
        b'\\x00\\x01config.txt\\x00octet\\x00'

    Concrete classes can also be constructed directly, for conversion into
    :class:`bytes` during transfer::

        >>> bytes(ACKPacket(block=10))
        b'\\x00\\x04\\x00\\n'
        >>> bytes(RRQPacket('foo', 'netascii', {'tsize': 0}))
        b'\\x00\\x01foo.txt\\x00netascii\\x00tsize\\x000\\x00'
    """
    __slots__ = ()
    opcode = None

    def __repr__(self):
        fields = ', '.join(
            f'{field}={getattr(self, field)!r}'
            for field in self.__class__.__slots__)
        return f'{self.__class__.__name__}({fields})'

    @classmethod
    def from_bytes(cls, s):
        """
        Given a :class:`bytes`-string *s*, checks the :class:`OpCode` at the
        front, and constructs one of the concrete packet types defined below,
        returning (instead of :class:`Packet` which is abstract)::

            >>> Packet.from_bytes(b'\\x00\\x01config.txt\\0octet\\0')
            RRQPacket(filename='config.txt', mode='octet', options=FrozenDict({}))
        """
        opcode, = struct.unpack_from('!H', s)
        try:
            cls = {
                OpCode.RRQ:   RRQPacket,
                OpCode.WRQ:   WRQPacket,
                OpCode.DATA:  DATAPacket,
                OpCode.ACK:   ACKPacket,
                OpCode.ERROR: ERRORPacket,
                OpCode.OACK:  OACKPacket,
            }[opcode]
        except KeyError:
            raise ValueError(lang._(
                'invalid packet opcode {opcode}'.format(opcode=opcode)))
        else:
            return cls.from_data(s[2:])

    @classmethod
    def from_data(cls, data):
        """
        Constructs an instance of the packet class with the specified *data*
        (which is everything in the :class:`bytes`-string passed to
        :meth:`from_bytes` minus the header). This method is not implemented in
        :class:`Packet` but is expected to be implemented in any concrete
        descendant.
        """
        raise NotImplementedError()


class RRQPacket(Packet):
    """
    Concrete type for ``RRQ`` (read request) packets.

    These packets are sent by a client to initiate a transfer. They include the
    *filename* to be sent, the *mode* to send it (one of the strings "octet" or
    "netascii"), and any *options* the client wishes to negotiate.
    """
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

    def __init__(self, filename, mode, options=None):
        self.filename = str(filename)
        self.mode = str(mode).lower()
        if options is None:
            options = ()
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
                    str(value).encode('ascii'), b'\0',
                )
            )),
        ))

    @classmethod
    def from_data(cls, data):
        try:
            filename, mode, suffix = cls.packet_re.match(data).groups()
        except AttributeError:
            raise ValueError(lang._('badly formed RRQ/WRQ packet'))
        # Technically the filename must be in ASCII format (7-bit chars in an
        # 8-bit field), but given ASCII is a strict subset of UTF-8, and that
        # UTF-8 cannot include NUL chars, I see no harm in permitting UTF-8
        # encoded filenames
        filename = filename.decode('utf-8')
        mode = mode.decode('ascii').lower()
        if mode not in TFTP_MODES:
            raise ValueError(lang._('unsupported file mode'))
        options = {
            match.group('name').decode('ascii').lower():
                match.group('value').decode('ascii').lower()
            for match in cls.options_re.finditer(suffix)
        }
        return cls(filename, mode, options)


class WRQPacket(RRQPacket):
    """
    Concrete type for ``WRQ`` (write request) packets.

    These packets are sent by a client to initiate a transfer to the server.
    They include the *filename* to be sent, the *mode* to send it (one of the
    strings "octet" or "netascii"), and any *options* the client wishes to
    negotiate.
    """
    __slots__ = ()
    opcode = OpCode.WRQ


class DATAPacket(Packet):
    """
    Concrete type for ``DATA`` packets.

    These are sent in response to ``RRQ``, ``WRQ``, or ``ACK`` packets and each
    contains a block of the file to transfer, *data* (by default, 512 bytes
    long unless this is the final ``DATA`` packet), and the *block* number.
    """
    __slots__ = ('block', 'data')
    opcode = OpCode.DATA

    def __init__(self, block, data):
        self.block = int(block)
        if not 1 <= self.block <= 65535:
            raise ValueError(f'invalid block (1..65535): {block}')
        self.data = bytes(data)

    def __bytes__(self):
        return struct.pack(
            f'!HH{len(self.data)}s', self.opcode, self.block, self.data)

    @classmethod
    def from_data(cls, data):
        block, = struct.unpack_from('!H', data)
        return cls(block, data[2:])


class ACKPacket(Packet):
    """
    Concrete type for ``ACK`` packets.

    These are sent in response to ``DATA`` packets, and acknowledge the
    successful receipt of the specified *block*.
    """
    __slots__ = ('block',)
    opcode = OpCode.ACK

    def __init__(self, block):
        self.block = int(block)
        if not 0 <= self.block <= 65535:
            raise ValueError(f'invalid block (0..65535): {block}')

    def __bytes__(self):
        return struct.pack(f'!HH', self.opcode, self.block)

    @classmethod
    def from_data(cls, data):
        block, = struct.unpack_from('!H', data)
        return cls(block)


class ERRORPacket(Packet):
    """
    Concrete type for ``ERROR`` packets.

    These are sent by either end of a transfer to indicate a fatal error
    condition. Receipt of an ``ERROR`` packet immediately terminates a transfer
    without further acknowledgment.

    The ``ERROR`` packet contains the *error* code (an :class:`Error` value)
    and a descriptive *message*.
    """
    __slots__ = ('error', 'message')
    opcode = OpCode.ERROR

    def __init__(self, error, message=None):
        self.error = Error(int(error))
        if message is None:
            self.message = {
                # NOTE: These messages are deliberately *not* marked for
                # translation as they are sent to the client
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
    """
    Concrete type for ``OACK`` packets.

    This is sent by the server instead of an initial ``DATA`` packet, when the
    client includes options in the ``RRQ`` packet. The content of the packet is
    all the *options* the server accepts, and their (potentially revised)
    values.
    """
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
            for match in cls.options_re.finditer(data)
        }
        return cls(options)
