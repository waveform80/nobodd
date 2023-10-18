import io
import logging
from pathlib import Path
from contextlib import suppress
from threading import Thread, Lock, Event
from socketserver import BaseRequestHandler, UDPServer, ThreadingMixIn
from time import monotonic as time

from . import netascii
from .tools import BufferedTranscoder
from .tftp import (
    Packet,
    RRQPacket,
    DATAPacket,
    ACKPacket,
    ERRORPacket,
    OACKPacket,
    Error,
)


class TransferDone(Exception):
    pass


class TFTPClientState:
    __slots__ = (
        'address', 'source', 'mode', 'last_seen',
        'blocks', 'blocks_read', 'block_size', 'last_block')

    def __init__(self, address, path, mode='octet', block_size=512):
        self.address = address
        self.source = path.open('rb')
        if mode == 'netascii':
            self.source = BufferedTranscoder(
                self.source, 'netascii', 'ascii', errors='replace')
        self.mode = mode
        self.blocks = {}
        self.blocks_read = 0
        self.block_size = block_size
        self.last_block = None
        self.last_seen = time()

    def ack(self, block_num):
        with suppress(KeyError):
            del self.blocks[block_num]

    def get(self, block_num):
        if self.blocks_read + 1 == block_num:
            if self.last_block is not None and not self.blocks:
                raise TransferDone('read past last block')
            self.blocks[block_num] = self.source.read(self.block_size)
            self.blocks_read += 1
            if len(self.blocks[block_num]) < self.block_size:
                self.last_block = block_num
            return self.blocks[block_num]
        # Re-transmit unacknowledged block (because DATA packet was presumably
        # lost). In this case blocks_read is not updated
        try:
            return self.blocks[block_num]
        except KeyError:
            raise ValueError('invalid block number requested')


class TFTPHandler(BaseRequestHandler):
    def setup(self):
        self.packet, self.socket = self.request
        self.rfile = io.BytesIO(self.packet)
        self.wfile = io.BytesIO()

    def finish(self):
        # We do this ourselves because the included DatagramRequestHandler
        # is happy to send out an empty UDP packet when the handler writes
        # nothing to wfile. This breaks certain TFTP clients; we want to
        # explicit send nothing in this case
        buf = self.wfile.getvalue()
        if buf:
            self.socket.sendto(buf, self.client_address)

    def handle(self):
        try:
            packet = Packet.from_bytes(self.rfile.read())
            self.server.logger.debug(
                '%s:%s -> %s:%s - %r', *self.client_address,
                *self.server.server_address, packet)
            response = getattr(self, 'do_' + packet.opcode.name)(packet)
        except AttributeError as exc:
            self.server.logger.warning(
                '%s:%s - unsupported operation %s',
                *self.client_address, exc)
            response = ERRORPacket(
                Error.UNDEFINED, f'Unsupported operation, {exc!s}')
        except ValueError as exc:
            self.server.logger.warning(
                '%s:%s - invalid request %s', *self.client_address, exc)
            response = ERRORPacket(Error.UNDEFINED, f'Invalid request, {exc!s}')
        except Exception as exc:
            self.server.logger.exception(exc)
            response = ERRORPacket(Error.UNDEFINED, 'Server error')
        finally:
            if response is not None:
                self.server.logger.debug(
                    '%s:%s <- %s:%s - %r', *self.client_address,
                    *self.server.server_address, response)
                self.wfile.write(bytes(response))


class TFTPBaseHandler(TFTPHandler):
    def resolve_path(self, filename):
        raise NotImplementedError

    def do_RRQ(self, packet):
        # Construct a new sub-server with an ephemeral port to handler all
        # further packets from this connection
        try:
            state = TFTPClientState(
                self.client_address,
                self.resolve_path(packet.filename),
                packet.mode,
                int(packet.options.get('blksize', 512)))
            options = {
                name: value
                for name, value in packet.options.items()
                if name in {'blksize'}
            }
            self.server.logger.info(
                '%s:%s - GET %s (%s)', *self.client_address,
                packet.filename, packet.mode)
            if options:
                packet = OACKPacket(options)
            else:
                packet = DATAPacket(1, state.get(1))
            server = TFTPSubServer(self.server, state)
            self.server.subs.add(server)
            self.server.logger.debug(
                '%s:%s <- %s:%s - %r', *self.client_address,
                *server.server_address, packet)
        except PermissionError:
            return ERRORPacket(Error.NOT_AUTH)
        except FileNotFoundError:
            return ERRORPacket(Error.NOT_FOUND)
        except OSError as exc:
            return ERRORPacket(Error.UNDEFINED, str(exc))
        else:
            # We cause the sub-server to send the first packet instead of
            # returning it for the main server to send, as it must originate
            # from the ephemeral port of the sub-server, not port 69
            server.socket.sendto(bytes(packet), self.client_address)
            return None

    def do_ERROR(self, packet):
        try:
            server, thread = self.server.sub_thread[self.client_address]
        except KeyError:
            pass
        else:
            server.done = True


class TFTPSubHandler(TFTPHandler):
    def handle(self):
        if self.client_address != self.server.client_state.address:
            self.server.logger.warning(
                '%s:%s - bad client for %s:%s', *self.client_address,
                *self.server.server_address)
        else:
            self.server.client_state.last_seen = time()
            return super().handle()

    def do_ACK(self, packet):
        state = self.server.client_state
        try:
            state.ack(packet.block)
            return DATAPacket(packet.block + 1, state.get(packet.block + 1))
        except (ValueError, OSError) as exc:
            self.server.done = True
            return ERRORPacket(Error.UNDEFINED, str(exc))
        except TransferDone:
            self.server.done = True
            self.server.logger.info(
                '%s:%s - GET finished', *self.client_address)

    def do_ERROR(self, packet):
        self.server.done = True


class TFTPBaseServer(UDPServer):
    allow_reuse_address = True
    allow_reuse_port = True
    logger = logging.getLogger('tftpd')

    def __init__(self, address, handler_class):
        assert issubclass(handler_class, TFTPBaseHandler)
        self.subs = TFTPSubServers()
        super().__init__(address, handler_class)

    def server_close(self):
        super().server_close()
        self.subs.close()


class TFTPSubServer(UDPServer):
    allow_reuse_address = True
    # NOTE: allow_reuse_port is left False as the sub-server is restricted to
    # ephemeral ports
    logger = TFTPBaseServer.logger
    sub_timeout = 5

    def __init__(self, main_server, client_state):
        self.done = False
        host, port = main_server.server_address
        super().__init__((host, 0), TFTPSubHandler)
        self.client_state = client_state

    def service_actions(self):
        super().service_actions()
        if time() - self.client_state.last_seen > self.sub_timeout:
            self.logger.warning(
                '%s:%s - timed out to %s:%s', *self.client_state.address,
                *self.server_address)
            self.done = True


class TFTPSubServers(Thread):
    logger = TFTPBaseServer.logger

    def __init__(self):
        super().__init__()
        self._done = Event()
        self._lock = Lock()
        self._alive = {}
        self.start()

    def close(self):
        self._done.set()

    def add(self, server):
        # Transfers are uniquely identified by TID (transfer ID) which consists
        # of the ephemeral server and client ports involved in the transfer. We
        # actually use the full ephemeral server and client address and port
        # combination (as we could be serving distinct networks on multiple
        # interfaces)
        tid = (server.server_address, server.client_state.address)
        thread = Thread(target=server.serve_forever)
        self.logger.debug(
            '%s:%s - starting server on %s:%s', *server.client_state.address,
            *server.server_address)
        with self._lock:
            with suppress(KeyError):
                self._remove(tid)
            self._alive[tid] = (server, thread)
        thread.start()

    def _remove(self, tid):
        server, thread = self._alive.pop(tid)
        self.logger.debug(
            '%s:%s - shutting down server on %s:%s',
            *server.client_state.address, *server.server_address)
        server.shutdown()
        thread.join(timeout=10)
        if thread.is_alive():
            raise RuntimeError(
                f'failed to shutdown thread for {server.server_address}')

    def run(self):
        while not self._done.wait(0.01):
            with self._lock:
                to_remove = {
                    tid
                    for tid, (server, thread) in self._alive.items()
                    if server.done
                }
                for tid in to_remove:
                    self._remove(tid)
        with self._lock:
            while self._alive:
                self._remove(next(iter(self._alive)))


class SimpleTFTPHandler(TFTPBaseHandler):
    def resolve_path(self, filename):
        p = Path(filename).resolve()
        if self.server.base_path in p.parents:
            return p
        else:
            raise PermissionError(
                f'{filename} is outside {self.server.base_path}')


class SimpleTFTPServer(ThreadingMixIn, TFTPBaseServer):
    def __init__(self, server_address, base_path):
        self.base_path = Path(base_path).resolve()
        super().__init__(server_address, SimpleTFTPHandler)
