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
    TFTP_BINARY,
    TFTP_NETASCII,
    TFTP_BLKSIZE,
    TFTP_TSIZE,
    TFTP_TIMEOUT,
    TFTP_MIN_BLKSIZE,
    TFTP_DEF_BLKSIZE,
    TFTP_MAX_BLKSIZE,
    TFTP_MIN_TIMEOUT,
    TFTP_MAX_TIMEOUT,
    Packet,
    RRQPacket,
    DATAPacket,
    ACKPacket,
    ERRORPacket,
    OACKPacket,
    Error,
)


# The following references were essential in constructing this module; the
# various TFTP RFCs covering the protocol version 2 and its negotiated options
# [RFC1350], [RFC2347], [RFC2348], [RFC2349], the wikipedia page documenting
# the protocol [1], and Thiadmer Riemersma's notes on the protocol [2] and the
# various options commonly found in other implementations. Wireshark [3] was
# also extremely useful in analyzing bugs in the implementation.
#
# [1]: https://en.wikipedia.org/wiki/Trivial_File_Transfer_Protocol
# [2]: https://www.compuphase.com/tftp.htm
# [3]: https://www.wireshark.org/
# [RFC1350]: https://datatracker.ietf.org/doc/html/rfc1350
# [RFC2347]: https://datatracker.ietf.org/doc/html/rfc2347
# [RFC2348]: https://datatracker.ietf.org/doc/html/rfc2348
# [RFC2349]: https://datatracker.ietf.org/doc/html/rfc2349


class TransferDone(Exception):
    pass

class AlreadyAcknowledged(ValueError):
    pass

class BadOptions(ValueError):
    pass


class TFTPClientState:
    __slots__ = (
        'address', 'source', 'mode', 'started', 'last_recv',
        'blocks', 'blocks_read', 'block_size', 'last_ack_size')

    def __init__(self, address, path, mode=TFTP_BINARY):
        self.address = address
        self.source = path.open('rb')
        if mode == TFTP_NETASCII:
            self.source = BufferedTranscoder(
                self.source, TFTP_NETASCII, 'ascii', errors='replace')
        self.mode = mode
        self.blocks = {}
        self.blocks_read = 0
        self.block_size = TFTP_DEF_BLKSIZE
        self.last_ack_size = None
        self.started = self.last_recv = time()

    def negotiate(self, options):
        # Strip out any options we don't support, but maintain the original
        # order of them (in accordance with RFC2347); this also ensures the
        # local options dict is distinct from the one passed in (so we can't
        # mutate it)
        options = {
            name: value
            for name, value in options.items()
            if name in {TFTP_BLKSIZE, TFTP_TSIZE}
        }
        # Reject stupid block sizes (less than 8 according to RFC2348, though
        # I'm sorely tempted to set this to 512!)
        if TFTP_BLKSIZE in options:
            blksize = int(options[TFTP_BLKSIZE])
            if blksize < TFTP_MIN_BLKSIZE:
                raise BadOptions('silly block size')
            self.block_size = min(TFTP_MAX_BLKSIZE, blksize)
            options[TFTP_BLKSIZE] = self.block_size
        # There may be implementations or transfer modes where we cannot
        # (cheaply) determine the transfer size (netascii). In this case we
        # simply remove it from the negotiated options
        if TFTP_TSIZE in options:
            try:
                options[TFTP_TSIZE] = self.get_size()
            except OSError:
                del options[TFTP_TSIZE]
        if TFTP_TIMEOUT in options:
            options[TFTP_TIMEOUT] = int(options[TFTP_TIMEOUT])
            if not TFTP_MIN_TIMEOUT <= options[TFTP_TIMEOUT] <= TFTP_MAX_TIMEOUT:
                del options[TFTP_TIMEOUT]
        return options

    def ack(self, block_num):
        with suppress(KeyError):
            self.last_ack_size = len(self.blocks.pop(block_num))

    def get_block(self, block_num):
        if self.blocks_read + 1 == block_num:
            if self.finished:
                raise TransferDone('transfer completed')
            self.blocks[block_num] = self.source.read(self.block_size)
            self.blocks_read += 1
            return self.blocks[block_num]
        try:
            # Re-transmit unacknowledged block (because DATA packet was
            # presumably lost). In this case blocks_read is not updated
            return self.blocks[block_num]
        except KeyError:
            if block_num <= self.blocks_read:
                # The block was already transmitted and acknowledged
                # (re-transmit of ACK in case of timeout); ignore this
                raise AlreadyAcknowledged('no re-transmit necessary')
            else:
                # A "future" block number beyond those already ACKed is
                # requested; this is invalid
                raise ValueError('invalid block number requested')

    def get_size(self):
        try:
            # The most reliable method of determining size is to stat the
            # open fd (guarantees we're talking about the same file even if
            # that filename got re-written since we opened it)
            return os.fstat(self.source.fileno()).st_size
        except AttributeError:
            # If the source doesn't have a fileno() attribute, fall back to
            # seeking to the end of the file (temporarily) to determine its
            # size. Again, this guarantees we're looking at the right file
            pos = self.source.tell()
            size = self.source.seek(0, io.SEEK_END)
            self.source.seek(pos)
            return result
        # Note that both these methods fail in the case of the netascii mode as
        # BufferedTranscoder has no fileno and is not seekable, but that's
        # entirely deliberate. We don't want to incur the potential expense of
        # determining the transfer size of a netascii transfer so we'll fail
        # with an exception there (which in turn means the tsize negotation
        # will fail and the option will be excluded from OACK)

    @property
    def transferred(self):
        if self.last_ack_size is None:
            return 0
        else:
            return (self.blocks_read - 1) * self.block_size + self.last_ack_size

    @property
    def finished(self):
        return (
            self.last_ack_size is not None and
            self.last_ack_size < self.block_size)


class TFTPHandler(BaseRequestHandler):
    def setup(self):
        self.packet, self.socket = self.request
        self.rfile = io.BytesIO(self.packet)
        self.wfile = io.BytesIO()

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

    def finish(self):
        # We do this ourselves because socketserver.DatagramRequestHandler
        # sends out an empty UDP packet when the handler writes nothing to
        # wfile. This breaks certain TFTP clients; we want to do nothing in
        # this case
        buf = self.wfile.getvalue()
        if buf:
            self.socket.sendto(buf, self.client_address)


class TFTPBaseHandler(TFTPHandler):
    def resolve_path(self, filename):
        # Must be overridden by descendents to provide a Path(-like) object
        # representing the requested *filename*
        raise NotImplementedError

    def do_RRQ(self, packet):
        try:
            state = TFTPClientState(
                self.client_address,
                self.resolve_path(packet.filename),
                packet.mode)
            self.server.logger.info(
                '%s:%s - GET %s (%s)', *self.client_address,
                packet.filename, packet.mode)
            options = state.negotiate(packet.options)
            if options:
                packet = OACKPacket(options)
            else:
                packet = DATAPacket(1, state.get_block(1))
            # Construct a new sub-server with an ephemeral port to handler all
            # further packets from this connection
            server = TFTPSubServer(
                self.server, state, options.get(TFTP_TIMEOUT))
            self.server.subs.add(server)
            self.server.logger.debug(
                '%s:%s <- %s:%s - %r', *self.client_address,
                *server.server_address, packet)
        except BadOptions as exc:
            return ERRORPacket(Error.INVALID_OPT, str(exc))
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
        # Ignore error packets to the main port entirely; the only legitimate
        # circumstance for this is rejection of negotiated options, in which
        # case we're not going to start a transfer anyway and no return
        # acknowledgement is required
        pass


class TFTPSubHandler(TFTPHandler):
    def handle(self):
        if self.client_address != self.server.client_state.address:
            self.server.logger.warning(
                '%s:%s - bad client for %s:%s', *self.client_address,
                *self.server.server_address)
            return None
        else:
            self.server.client_state.last_recv = time()
            return super().handle()

    def do_ACK(self, packet):
        state = self.server.client_state
        try:
            state.ack(packet.block)
            return DATAPacket(packet.block + 1, state.get_block(packet.block + 1))
        except AlreadyAcknowledged:
            pass
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
    retry_timeout = None
    fail_timeout = 5

    def __init__(self, main_server, client_state, timeout=None):
        self.done = False
        host, port = main_server.server_address
        super().__init__((host, 0), TFTPSubHandler)
        self.client_state = client_state
        if timeout is not None:
            self.retry_timeout = timeout
            self.fail_timeout = timeout * 3

    def service_actions(self):
        super().service_actions()
        if self.retry_timeout is not None:
            if time() - self.client_state.last_recv > self.retry_timeout:
                # TODO re-transmit last packet
                pass
        if time() - self.client_state.last_recv > self.fail_timeout:
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
