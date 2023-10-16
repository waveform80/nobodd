import logging
from pathlib import Path
from threading import Thread, Lock
from socketserver import DatagramRequestHandler, UDPServer, ThreadingMixIn

from . import netascii
from .tools import BufferedTranscoder
from .tftp import (
    Packet,
    RRQPacket,
    DATAPacket,
    ACKPacket,
    ERRORPacket,
    Error,
)


class TransferDone(Exception):
    pass


class TFTPClientState:
    __slots__ = (
        'address', 'block_size', 'block_num', 'last_block', 'source', 'mode')

    def __init__(self, address, path, mode='octet', block_size=512):
        self.address = address
        self.source = path.open('rb')
        if mode == 'netascii':
            self.source = BufferedTranscoder(
                self.source, 'netascii', 'ascii', errors='replace')
        self.mode = mode
        self.block_size = block_size
        self.block_num = 0
        self.last_block = None

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


class TFTPHandler(DatagramRequestHandler):
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
        # Destroy any sub-server currently serving this client on this
        # specific port
        with self.server.sub_lock:
            try:
                server, thread = self.server.sub_threads.pop(
                    self.client_address)
            except KeyError:
                pass
            else:
                server.done = True
        try:
            state = TFTPClientState(
                self.client_address,
                self.resolve_path(packet.filename),
                packet.mode)
        except PermissionError:
            return ERRORPacket(Error.NOT_AUTH)
        except FileNotFoundError:
            return ERRORPacket(Error.NOT_FOUND)
        except OSError as exc:
            return ERRORPacket(Error.UNDEFINED, str(exc))
        else:
            self.server.logger.info(
                '%s:%s - GET %s (%s)', *self.client_address,
                packet.filename, packet.mode)
            # Construct a new server with an ephemeral port to handler all
            # further packets from this connection. We cause the server to
            # send the first DATA packet instead of returning it, as it must
            # originate from the ephemeral port, not the main server port
            server = TFTPSubServer(self.server, state)
            thread = Thread(target=server.serve_forever)
            packet = DATAPacket(1, state.get(1))
            self.server.logger.debug(
                '%s:%s - starting server on %s:%s', *self.client_address,
                *server.server_address)
            thread.start()
            with self.server.sub_lock:
                self.server.sub_threads[self.client_address] = (server, thread)
            self.server.logger.debug(
                '%s:%s <- %s:%s - %r', *self.client_address,
                *server.server_address, packet)
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
            return super().handle()

    def do_ACK(self, packet):
        state = self.server.client_state
        try:
            return DATAPacket(packet.block + 1, state.get(packet.block + 1))
        except (ValueError, OSError) as exc:
            return ERRORPacket(Error.UNDEFINED, str(exc))
        except TransferDone:
            self.server.logger.info(
                '%s:%s - finished', *self.client_address)
            self.server.done = True

    def do_ERROR(self, packet):
        self.server.done = True


class TFTPBaseServer(UDPServer):
    allow_reuse_address = True
    allow_reuse_port = True
    logger = logging.getLogger('tftpd')
    sub_timeout = 1

    def __init__(self, address, handler_class):
        assert issubclass(handler_class, TFTPBaseHandler)
        self.sub_lock = Lock()
        self.sub_threads = {}
        super().__init__(address, handler_class)

    def server_close(self):
        with self.sub_lock:
            for server, thread in self.sub_threads.values():
                print(f'Shutting down {thread}')
                server.done = True
                server.shutdown()
            for server, thread in self.sub_threads.values():
                thread.join(timeout=self.sub_timeout)
                if not thread.is_alive():
                    warnings.warn(
                        RuntimeWarning(
                    f'failed to shutdown client thread for '
                    f'{self.client_address}'))

    def service_actions(self):
        super().service_actions()
        # Shutdown and remove servers (and their threads) which have finished.
        # Currently this runs in the main server's thread and can potentially
        # slow down accepting new requests; if this becomes a bottle-neck just
        # farm this out to a separate "reaper" thread
        with self.sub_lock:
            to_remove = {
                address
                for address, (server, thread) in self.sub_threads.items()
                if server.done
            }
            to_shutdown = [
                self.sub_threads.pop(address)
                for address in to_remove
            ]
        for server, thread in to_shutdown:
            self.logger.debug(
                '%s:%s - shutting down server on %s:%s',
                *server.client_state.address, *server.server_address)
            server.shutdown()
            thread.join(timeout=self.sub_timeout)
            if thread.is_alive():
                raise RuntimeError(
                    f'failed to shutdown thread for {server.server_address}')


class TFTPSubServer(UDPServer):
    allow_reuse_address = True
    logger = TFTPBaseServer.logger

    def __init__(self, main_server, client_state):
        self.done = False
        host, port = main_server.server_address
        super().__init__((host, 0), TFTPSubHandler)
        self.client_state = client_state


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
