import io
import struct
import logging
from pathlib import Path
from enum import IntEnum, auto
from collections import namedtuple
from socketserver import BaseRequestHandler, ThreadingUDPServer

from . import netascii
from .tools import labels, formats, BufferedTranscoder


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


class TransferDone(Exception):
    pass


class TFTPClientState:
    __slots__ = (
        'block_size', 'block_num', 'last_block', 'source', 'mode', 'server')

    def __init__(self, request, path, mode='octet', block_size=512):
        self.source = path.open('rb')
        if mode == 'netascii':
            self.source = BufferedTranscoder(
                self.source, 'netascii', 'ascii', errors='replace')
        self.mode = mode
        self.block_size = block_size
        self.block_num = 0
        self.last_block = None
        #self.server = request.server.get_server(request.client_address)

    def get(self, block_num):
        if self.block_num + 1 == block_num:
            if self.done:
                raise TransferDone('last block acknowledged')
            self.block_num = block_num
            self.last_block = self.source.read(self.block_size)
            return self.last_block
        elif self.block_num == block_num:
            # Re-transmit last block (because last DATA packet was presumably
            # lost). In this case neither last_block nor block_num are updated
            if self.last_block is not None:
                return self.last_block
        raise ValueError('invalid block number requested')

    @property
    def done(self):
        return (
            self.last_block is not None and
            len(self.last_block) < self.block_size)


class TFTPHandler(BaseRequestHandler):
    client_states = {}

    def setup(self):
        self.packet, self.socket = self.request
        self.rfile = io.BytesIO(self.packet)
        self.wfile = io.BytesIO()

    def finish(self):
        self.socket.sendto(self.wfile.getvalue(), self.client_address)

    def resolve_path(self, filename):
        raise NotImplementedError

    def handle(self):
        try:
            packet = Packet.from_bytes(self.rfile.read())
            self.server.logger.debug(
                '%s:%s -> %r', *self.client_address, packet)
            response = getattr(self, 'do_' + packet.opcode.name)(packet)
        except AttributeError as exc:
            self.server.logger.warning(
                '%s:%s - err - unsupported operation %s',
                *self.client_address, exc)
            response = ERRORPacket(
                Error.UNDEFINED, f'Unsupported operation, {exc!s}')
        except ValueError as exc:
            self.server.logger.warning(
                '%s:%s - err - invalid request %s', *self.client_address, exc)
            response = ERRORPacket(Error.UNDEFINED, f'Invalid request, {exc!s}')
        except Exception as exc:
            self.server.logger.exception(exc)
            response = ERRORPacket(Error.UNDEFINED, 'Server error')
        finally:
            if response is not None:
                self.server.logger.debug(
                    '%s:%s <- %r', *self.client_address, response)
                self.wfile.write(bytes(response))

    def do_RRQ(self, packet):
        try:
            state = TFTPClientState(
                self, self.resolve_path(packet.filename), packet.mode)
        except PermissionError:
            return ERRORPacket(Error.NOT_AUTH)
        except FileNotFoundError:
            return ERRORPacket(Error.NOT_FOUND)
        except OSError as exc:
            return ERRORPacket(Error.UNDEFINED, str(exc))
        else:
            TFTPHandler.client_states[self.client_address] = state
            self.server.logger.info(
                '%s:%s - %s - %s', *self.client_address,
                packet.mode, packet.filename)
            return DATAPacket(1, state.get(1))

    def do_ACK(self, packet):
        try:
            state = TFTPHandler.client_states[self.client_address]
        except KeyError:
            return ERRORPacket(Error.UNKNOWN_ID)
        else:
            try:
                return DATAPacket(packet.block + 1, state.get(packet.block + 1))
            except (ValueError, OSError) as exc:
                return ERRORPacket(Error.UNDEFINED, str(exc))
            except TransferDone:
                self.server.logger.info(
                    '%s:%s - finished', *self.client_address)
                del TFTPHandler.client_states[self.client_address]

    def do_ERROR(self, packet):
        try:
            del TFTPHandler.client_states[self.client_address]
        except KeyError:
            pass


class TFTPServer(ThreadingUDPServer):
    allow_reuse_address = True
    allow_reuse_port = True
    logger = logging.getLogger('tftpd')

    #def get_server(self, client_address):
    #    return TFTPServer(NEW_SOCKET(), self.RequestHandlerClass)


class SimpleTFTPHandler(TFTPHandler):
    def resolve_path(self, filename):
        p = Path(filename).resolve()
        if self.server.base_path in p.parents:
            return p
        else:
            raise PermissionError(
                f'{filename} is outside {self.server.base_path}')


class SimpleTFTPServer(TFTPServer):
    def __init__(self, server_address, base_path):
        self.base_path = Path(base_path).resolve()
        super().__init__(server_address, SimpleTFTPHandler)
