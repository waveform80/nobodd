# nobodd: a boot configuration tool for the Raspberry Pi
#
# Copyright (c) 2023-2024 Dave Jones <dave.jones@canonical.com>
# Copyright (c) 2023-2024 Canonical Ltd.
#
# SPDX-License-Identifier: GPL-3.0

import io
import os
import sys
import socket
import logging
from pathlib import Path
from contextlib import suppress
from threading import Thread, Lock, Event
from socketserver import BaseRequestHandler, UDPServer
from time import monotonic_ns as time_ns

from . import netascii, lang
from .tools import BufferedTranscoder, get_best_family, format_address
from .tftp import (
    TFTP_BINARY,
    TFTP_NETASCII,
    TFTP_BLKSIZE,
    TFTP_TSIZE,
    TFTP_TIMEOUT,
    TFTP_UTIMEOUT,
    TFTP_MIN_BLKSIZE,
    TFTP_DEF_BLKSIZE,
    TFTP_MAX_BLKSIZE,
    TFTP_DEF_TIMEOUT_NS,
    TFTP_MIN_TIMEOUT_NS,
    TFTP_MAX_TIMEOUT_NS,
    TFTP_OPTIONS,
    Packet,
    RRQPacket,
    WRQPacket,
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
    """
    Exception raised internally to signal that a transfer has been completed.
    """

class AlreadyAcknowledged(ValueError):
    """
    Exception raised internally to indicate that a particular data packet was
    already acknowledged, and does not require repeated acknowlegement.
    """

class BadOptions(ValueError):
    """
    Exception raised when a client passes invalid options in a
    :class:`~nobodd.tftp.RRQPacket`.
    """


class TFTPClientState:
    """
    Represents the state of a single transfer with a client. Constructed with
    the client's *address* (format varies according to family), the *path* of
    the file to transfer (must be a :class:`~pathlib.Path`-like object,
    specifically one with a functioning :meth:`~pathlib.Path.open` method), and
    the *mode* of the transfer (must be either :data:`~nobodd.tftp.TFTP_BINARY`
    or :data:`~nobodd.tftp.TFTP_NETASCII`).

    .. attribute:: address

        The address of the client.

    .. attribute:: blocks

        An internal mapping of block numbers to blocks. This caches blocks that
        have been read, transmitted, but not yet acknowledged. As ``ACK``
        packets are received, blocks are removed from this cache.

    .. attribute:: block_size

        The size, in bytes, of blocks to transfer to the client.

    .. attribute:: mode

        The transfer mode. One of :data:`~nobodd.tftp.TFTP_BINARY` or
        :data:`~nobodd.tftp.TFTP_NETASCII`.

    .. attribute:: source

        The file-like object opened from the specified *path*.

    .. attribute:: timeout

        The timeout, in nano-seconds, to use before re-transmitting packets to
        the client.
    """
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
        self.timeout = TFTP_DEF_TIMEOUT_NS
        self.started = self.last_recv = time_ns()
        self.last_send = None

    def close(self):
        """
        Closes the source file associated with the client state. This method
        is idempotent.
        """
        if self.source is not None:
            self.source.close()
            self.source = None

    def negotiate(self, options):
        """
        Called with *options*, a mapping of option names to values (both
        :class:`str`) that the client wishes to negotiate.

        Currently supported options are defined in
        :data:`nobodd.tftp.TFTP_OPTIONS`. The original *options* mapping is
        left unchanged. Returns a new options mapping containing only those
        options that we understand and accept, and with values adjusted to
        those that we can support.

        Raises :exc:`BadOptions` in the case that the client requests
        pathologically silly or dangerous options.
        """
        # Strip out any options we don't support, but maintain the original
        # order of them (in accordance with RFC2347); this also ensures the
        # local options dict is distinct from the one passed in (so we can't
        # mutate it)
        options = {
            name: value
            for name, value in options.items()
            if name in TFTP_OPTIONS
        }
        # Reject stupid block sizes (less than 8 according to RFC2348, though
        # I'm sorely tempted to set this to 512!)
        if TFTP_BLKSIZE in options:
            self.block_size = min(TFTP_MAX_BLKSIZE, int(options[TFTP_BLKSIZE]))
            if self.block_size < TFTP_MIN_BLKSIZE:
                raise BadOptions('silly block size')
            options[TFTP_BLKSIZE] = self.block_size
        # There may be implementations or transfer modes where we cannot
        # (cheaply) determine the transfer size (netascii). In this case we
        # simply remove it from the negotiated options
        if TFTP_TSIZE in options:
            try:
                options[TFTP_TSIZE] = self.get_size()
            except OSError:
                del options[TFTP_TSIZE]
        # Accept timeout and utimeout with the latter taking precedence
        # regardless of its order in the options. If both are present, timeout
        # is removed from the returned options to indicate we accept utimeout
        if TFTP_TIMEOUT in options:
            try:
                self.timeout = int(options[TFTP_TIMEOUT]) * 1_000_000_000
            except ValueError:
                self.timeout = int(float(options[TFTP_TIMEOUT]) * 1_000_000_000)
        if TFTP_UTIMEOUT in options:
            self.timeout = int(options[TFTP_UTIMEOUT]) * 1_000
            with suppress(KeyError):
                del options[TFTP_TIMEOUT]
        if not TFTP_MIN_TIMEOUT_NS <= self.timeout <= TFTP_MAX_TIMEOUT_NS:
            raise BadOptions('silly timeout')
        return options

    def ack(self, block_num):
        """
        Specifies that *block_num* has been acknowledged by the client and can
        be removed from :attr:`blocks`, the internal block cache.
        """
        with suppress(KeyError):
            self.last_ack_size = len(self.blocks.pop(block_num))

    def get_block(self, block_num):
        """
        Returns the :class:`bytes` of the specified *block_num*.

        If the *block_num* has not been read yet, this will cause the
        :attr:`source` to be read. Otherwise, it will be returned from the
        as-yet unacknowledged block cache (in :attr:`blocks`). If the block
        has already been acknowledged, which may happen asynchronously, this
        will raise :exc:`AlreadyAcknowledged`.

        A :exc:`ValueError` is raised if an invalid block is requested.
        """
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
        """
        Attempts to calculate the size of the transfer. This is used when
        negotiating the ``tsize`` option.

        At first, :func:`os.fstat` is attempted on the open file; if this fails
        (e.g. because there's no valid ``fileno``), the routine will attempt to
        :meth:`~io.IOBase.seek` to the end of the file briefly to determine
        its size. Raises :exc:`OSError` in the case that the size cannot be
        determined.
        """
        try:
            # The most reliable method of determining size is to stat the
            # open fd (guarantees we're talking about the same file even if
            # that filename got re-written since we opened it)
            return os.fstat(self.source.fileno()).st_size
        except (OSError, AttributeError):
            # If the source doesn't have a fileno() attribute, fall back to
            # seeking to the end of the file (temporarily) to determine its
            # size. Again, this guarantees we're looking at the right file
            pos = self.source.tell()
            size = self.source.seek(0, io.SEEK_END)
            self.source.seek(pos)
            return size
        # Note that both these methods fail in the case of the netascii mode as
        # BufferedTranscoder has no fileno and is not seekable, but that's
        # entirely deliberate. We don't want to incur the potential expense of
        # determining the transfer size of a netascii transfer so we'll fail
        # with an OSError there (which in turn means the tsize negotation
        # will fail and the option will be excluded from OACK)

    @property
    def transferred(self):
        """
        Returns the number of bytes transferred to client and successfully
        acknowledged.
        """
        if self.last_ack_size is None:
            return 0
        else:
            return (self.blocks_read - 1) * self.block_size + self.last_ack_size

    @property
    def finished(self):
        """
        Indicates whether the transfer has completed or not. A transfer is
        considered complete when the final (under-sized) block has been sent to
        the client *and acknowledged*.
        """
        return (
            self.last_ack_size is not None and
            self.last_ack_size < self.block_size)


class TFTPHandler(BaseRequestHandler):
    """
    Abstract base handler for TFTP transfers.

    This handles decoding TFTP packets with the classes defined in
    :mod:`nobodd.tftp`. If the decoding is successful, it attempts to call a
    corresponding ``do_`` method (e.g. :meth:`~TFTPBaseHandler.do_RRQ`,
    :meth:`~TFTPSubHandler.do_ACK`) with the decoded packet. The handler must
    return a :class:`nobodd.tftp.Packet` in response.

    This base class defines no ``do_`` methods itself; see
    :class:`TFTPBaseHandler` and :class:`TFTPSubHandler`.
    """
    def setup(self):
        """
        Overridden to set up the :attr:`rfile` and :attr:`wfile` objects.
        """
        self.packet, self.socket = self.request
        self.rfile = io.BytesIO(self.packet)
        self.wfile = io.BytesIO()

    def handle(self):
        """
        Attempts to decode the incoming :class:`~nobodd.tftp.Packet` and
        dispatch it to an appropriately named ``do_`` method. If the method
        returns another :class:`~nobodd.tftp.Packet`, it will be sent as the
        response.
        """
        try:
            packet = Packet.from_bytes(self.rfile.read())
            self.server.logger.debug(
                '%s -> %s - %r',
                format_address(self.client_address),
                format_address(self.server.server_address), packet)
            response = getattr(self, 'do_' + packet.opcode.name)(packet)
        except AttributeError as exc:
            self.server.logger.warning(
                lang._('%s - ERROR - unsupported operation; %s'),
                format_address(self.client_address), exc)
            response = ERRORPacket(
                Error.UNDEFINED, f'Unsupported operation, {exc!s}')
        except ValueError as exc:
            self.server.logger.warning(
                lang._('%s - ERROR - invalid request; %s'),
                format_address(self.client_address), exc)
            response = ERRORPacket(Error.UNDEFINED, f'Invalid request, {exc!s}')
        except Exception as exc:
            self.server.logger.exception(
                lang._('%s - ERROR - unexpected error; %s'),
                format_address(self.client_address), exc, exc_info=exc)
            response = ERRORPacket(Error.UNDEFINED, 'Server error')
        finally:
            if response is not None:
                self.server.logger.debug(
                    '%s <- %s - %r',
                    format_address(self.client_address),
                    format_address(self.server.server_address), response)
                self.wfile.write(bytes(response))

    def finish(self):
        """
        Overridden to send the response written to :attr:`wfile`. Returns the
        number of bytes written.

        .. note::

            In contrast to the usual DatagramRequestHandler, this method does
            *not* send an empty packet in the event that :attr:`wfile` has no
            content, as that confused several TFTP clients.
        """
        buf = self.wfile.getvalue()
        if buf:
            # Return the number of bytes written; this is used in descendents
            # to track when we've *actually* written something
            return self.socket.sendto(buf, self.client_address)


class TFTPBaseHandler(TFTPHandler):
    """
    A abstract base handler for building TFTP servers.

    Implements :meth:`do_RRQ` to handle the initial
    :class:`~nobodd.tftp.RRQPacket` of a transfer. This calls the abstract
    :meth:`resolve_path` to obtain the :class:`~pathlib.Path`-like object
    representing the requested file. Descendents must (at a minimum) override
    :meth:`resolve_path` to implement a TFTP server.
    """

    def resolve_path(self, filename):
        """
        Given *filename*, as requested by a TFTP client, returns a
        :class:`~pathlib.Path`-like object.

        In the base class, this is an abstract method which raises
        :exc:`NotImplementedError`. Descendents must override this method to
        return a :class:`~pathlib.Path`-like object, specifically one with a
        working :meth:`~pathlib.Path.open` method, representing the file
        requested, or raise an :exc:`OSError` (e.g. :exc:`FileNotFoundError`)
        if the requested *filename* is invalid.
        """
        raise NotImplementedError

    def do_RRQ(self, packet):
        """
        Handles *packet*, the initial :class:`~nobodd.tftp.RRQPacket` of a
        connection.

        If option negotiation succeeds, and :meth:`resolve_path` returns a
        valid :class:`~pathlib.Path`-like object, this method will spin up a
        :class:`TFTPSubServer` instance in a background thread (see
        :class:`TFTPSubServers`) on an ephemeral port to handle all further
        interaction with this client.
        """
        try:
            self.server.logger.info(
                '%s - RRQ (%s) %s',
                format_address(self.client_address),
                packet.mode, packet.filename)
            state = TFTPClientState(
                self.client_address,
                self.resolve_path(packet.filename),
                packet.mode)
            options = state.negotiate(packet.options)
            if options:
                packet = OACKPacket(options)
            else:
                packet = DATAPacket(1, state.get_block(1))
        except BadOptions as exc:
            self.server.logger.info(
                lang._('%s - ERROR - bad options; %s'),
                format_address(self.client_address), exc)
            return ERRORPacket(Error.INVALID_OPT, str(exc))
        except PermissionError:
            self.server.logger.info(
                lang._('%s - ERROR - permission denied'),
                format_address(self.client_address))
            return ERRORPacket(Error.NOT_AUTH)
        except FileNotFoundError:
            self.server.logger.info(
                lang._('%s - ERROR - not found'),
                format_address(self.client_address))
            return ERRORPacket(Error.NOT_FOUND)
        except OSError as exc:
            self.server.logger.info(
                lang._('%s - ERROR - %s'),
                format_address(self.client_address), exc)
            return ERRORPacket(Error.UNDEFINED, str(exc))
        else:
            # Construct a new sub-server with an ephemeral port to handler all
            # further packets from this connection
            sub_server = TFTPSubServer(self.server, state)
            self.server.subs.add(sub_server)
            self.server.logger.debug(
                '%s <- %s - %r',
                format_address(self.client_address),
                format_address(sub_server.server_address), packet)
            # We cause the sub-server to send the first packet instead of
            # returning it for the main server to send, as it must originate
            # from the ephemeral port of the sub-server, not port 69
            sub_server.socket.sendto(bytes(packet), self.client_address)
            state.last_send = time_ns()
            return None

    def do_ERROR(self, packet):
        """
        Handles :class:`~nobodd.tftp.ERRORPacket` by ignoring it. The only way
        this should appear on the main port is at the start of a transfer,
        which would imply we're not going to start a transfer anyway.
        """
        return None


class TFTPSubHandler(TFTPHandler):
    """
    Handler for all client interaction after the initial
    :class:`~nobodd.tftp.RRQPacket`.

    Only the initial packet goes to the "main" TFTP port (69). After that, each
    transfer communicates between the client's original port (presumably in the
    ephemeral range) and an ephemeral server port, specific to that transfer.
    This handler is spawned by the main handler (a descendent of
    :class:`TFTPBaseHandler`) and deals with all further client communication.
    In practice this means it only handles :class:`~nobodd.tftp.ACKPacket` and
    :class:`~nobodd.tftp.ERRORPacket`.
    """

    def handle(self):
        """
        Overridden to verify that the incoming packet came from the address
        (and port) that originally spawned this sub-handler. Logs and otherwise
        ignores all packets that do not meet this criteria.
        """
        if self.client_address != self.server.client_state.address:
            self.server.logger.warning(
                lang._('%s - IGNORE - bad client for %s'),
                format_address(self.client_address),
                format_address(self.server.server_address))
            return None
        else:
            self.server.client_state.last_recv = time_ns()
            return super().handle()

    def finish(self):
        """
        Overridden to note the last time we communicated with this client. This
        is used by the re-transmit algorithm.
        """
        written = super().finish()
        if written is not None:
            self.server.client_state.last_send = time_ns()

    def do_ACK(self, packet):
        """
        Handles :class:`~nobodd.tftp.ACKPacket` by calling
        :meth:`TFTPClientState.ack`. Terminates the thread for this sub-handler
        if the transfer is complete, and otherwise sends the next
        :class:`~nobodd.tftp.DATAPacket` in response.
        """
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
            now = time_ns()
            duration = (now - state.started) / 1_000_000_000
            self.server.logger.info(
                lang._('%s - DONE - %.1f secs, %d bytes, ~%.1f Kb/s'),
                format_address(self.client_address),
                duration, state.transferred,
                state.transferred / duration / 1024)

    def do_ERROR(self, packet):
        """
        Handles :class:`~nobodd.tftp.ERRORPacket` by terminating the transfer
        (in accordance with the spec.)
        """
        self.server.done = True


class TFTPBaseServer(UDPServer):
    """
    A abstract base for building TFTP servers.

    To build a concrete TFTP server, make a descendent of
    :class:`TFTPBaseHandler` that overrides
    :meth:`~TFTPBaseHandler.resolve_path`, then make a descendent of this class
    that calls ``super().__init__`` with the overridden handler class. See
    :class:`SimpleTFTPHandler` and :class:`SimpleTFTPServer` for examples.

    .. note::

        While it is common to combine classes like
        :class:`~socketserver.UDPServer` and :class:`~socketserver.TCPServer`
        with the threading or fork-based mixins there is little point in doing
        so with :class:`TFTPBaseServer`.

        Only the initial packet of a TFTP transaction arrives on the "main"
        port; every packet after this is handled by a background thread with
        its own ephemeral port. Thus, multi-threading or multi-processing of
        the initial connection only applies to a single (minimal) packet.
    """
    allow_reuse_address = True
    allow_reuse_port = True
    logger = logging.getLogger('tftpd')

    def __init__(self, address, handler_class, bind_and_activate=True):
        assert issubclass(handler_class, TFTPBaseHandler)
        self.address_family, address = get_best_family(*address)
        super().__init__(address, handler_class, bind_and_activate)
        self.subs = TFTPSubServers()

    def server_close(self):
        super().server_close()
        self.subs.close()


class TFTPSubServer(UDPServer):
    """
    The server class associated with :class:`TFTPSubHandler`.

    You should never need to instantiate this class yourself. The base handler
    should create an instance of this to handle all communication with the
    client after the initial ``RRQ`` packet.
    """
    allow_reuse_address = True
    # NOTE: allow_reuse_port is left False as the sub-server is restricted to
    # ephemeral ports
    logger = TFTPBaseServer.logger

    def __init__(self, main_server, client_state):
        self.done = False
        self.address_family = main_server.address_family
        host, _, *suffix = main_server.server_address
        address = (host, 0) + tuple(suffix)
        super().__init__(address, TFTPSubHandler)
        self.client_state = client_state

    def service_actions(self):
        """
        Overridden to handle re-transmission after a timeout.
        """
        super().service_actions()
        now = time_ns()
        state = self.client_state
        if now - state.last_recv > state.timeout:
            if state.last_send is None:
                # TODO: Not sure this code can be reached?
                self.logger.error(
                    lang._('internal error; timeout without send'))
                self.done = True
            elif state.last_send - state.last_recv > state.timeout * 5:
                self.logger.warning(
                    lang._('%s - timed out to %s'),
                    format_address(self.client_state.address),
                    format_address(self.server_address))
                self.done = True
            elif now - state.last_send > state.timeout:
                for block, data in state.blocks.items():
                    packet = DATAPacket(block, data)
                    self.socket.sendto(bytes(packet), state.address)
                state.last_send = time_ns()


class TFTPSubServers(Thread):
    """
    Manager class for the threads running :class:`TFTPSubServer`.

    :class:`TFTPBaseServer` creates an instance of this to keep track of the
    background threads that are running transfers with :class:`TFTPSubServer`.
    """
    logger = TFTPBaseServer.logger

    def __init__(self):
        super().__init__()
        self._done = Event()
        self._lock = Lock()
        self._alive = {}
        self.start()

    def close(self):
        self._done.set()
        self.join(timeout=10)

    def add(self, server):
        """
        Add *server*, a :class:`TFTPSubServer` instance, as a new background
        thread to be tracked.
        """
        # Transfers are uniquely identified by TID (transfer ID) which consists
        # of the ephemeral server and client ports involved in the transfer. We
        # actually use the full ephemeral server and client address and port
        # combination (as we could be serving distinct networks on multiple
        # interfaces)
        tid = (server.server_address, server.client_state.address)
        # Override default poll_interval on serve_forever to permit
        # finer-grained timeouts (as supported by the utimeout extension)
        thread = Thread(
            target=server.serve_forever, kwargs={'poll_interval': 0.01})
        self.logger.debug(
            lang._('%s - starting server on %s'),
            format_address(server.client_state.address),
            format_address(server.server_address))
        with self._lock:
            with suppress(KeyError):
                self._remove(tid)
            self._alive[tid] = (server, thread)
        thread.start()

    def _remove(self, tid):
        """
        Shutdown the server and join the background thread responsible for the
        transfer with *tid*.
        """
        server, thread = self._alive.pop(tid)
        self.logger.debug(
            lang._('%s - shutting down server on %s'),
            format_address(server.client_state.address),
            format_address(server.server_address))
        server.shutdown()
        thread.join(timeout=10)
        if thread.is_alive():
            raise RuntimeError(lang._(
                'failed to shutdown thread for {server.server_address}'
                .format(server=server)))
        server.client_state.close()

    def run(self):
        """
        Watches background threads for completed or otherwise terminated
        transfers. Shuts down all remaining servers (and their corresponding
        threads) at termination.
        """
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
    """
    An implementation of :class:`TFTPBaseHandler` that overrides uses
    :attr:`SimpleTFTPServer.base_path` for :meth:`resolve_path`.
    """

    def resolve_path(self, filename):
        """
        Resolves *filename* against :attr:`SimpleTFTPServer.base_path`.
        """
        p = (self.server.base_path / filename).resolve()
        if self.server.base_path in p.parents:
            return p
        else:
            raise PermissionError(lang._(
                '{filename} is outside {self.server.base_path}'
                .format(filename=filename, self=self)))


class SimpleTFTPServer(TFTPBaseServer):
    """
    A trivial (pun intended) implementation of :class:`TFTPBaseServer` that
    resolves requested paths against *base_path* (a :class:`str` or
    :class:`~pathlib.Path`).

    .. attribute:: base_path

        The *base_path* specified in the constructor.
    """
    def __init__(self, server_address, base_path):
        self.base_path = Path(base_path).resolve()
        super().__init__(server_address, SimpleTFTPHandler)
