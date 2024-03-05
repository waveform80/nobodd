# nobodd: a boot configuration tool for the Raspberry Pi
#
# Copyright (c) 2023-2024 Dave Jones <dave.jones@canonical.com>
# Copyright (c) 2023-2024 Canonical Ltd.
#
# SPDX-License-Identifier: GPL-3.0

"""
A read-only TFTP server capable of reading FAT boot partitions from within
image files or devices. Intended to be paired with a block-device service (e.g.
NBD) for netbooting Raspberry Pis.
"""

import os
import sys
import stat
import signal
import socket
import logging
import argparse
from pathlib import Path
from selectors import DefaultSelector, EVENT_READ

from . import lang
from .disk import DiskImage
from .fs import FatFileSystem
from .systemd import get_systemd
from .tftpd import TFTPBaseHandler, TFTPBaseServer
from .config import (
    CONFIG_LOCATIONS,
    ConfigArgumentParser,
    Board,
    port,
)

# NOTE: The fallback comes first here as Python 3.7 incorporates
# importlib.resources but at a version incompatible with our requirements.
# Ultimately the try clause should be removed in favour of the except clause
# once compatibility moves beyond Python 3.9
try:
    import importlib_resources as resources
except ImportError:
    from importlib import resources

# NOTE: Remove except when compatibility moves beyond Python 3.8
try:
    from importlib.metadata import version
except ImportError:
    from importlib_metadata import version


class BootHandler(TFTPBaseHandler):
    """
    A descendent of :class:`~nobodd.tftpd.TFTPBaseHandler` that resolves paths
    relative to the FAT file-system in the OS image associated with the Pi
    serial number which forms the initial directory.
    """

    def resolve_path(self, filename):
        """
        Resolves *filename* relative to the OS image associated with the
        initial directory.

        In other words, if the request is for :file:`1234abcd/config.txt`, the
        handler will look up the board with serial number ``1234abcd`` in
        :class:`BootServer.boards`, find the associated OS image, the FAT
        file-system within that image, and resolve :file:`config.txt` within
        that file-system.
        """
        p = Path(filename)
        if not p.parts:
            raise FileNotFoundError()
        try:
            serial = int(p.parts[0], base=16)
            board = self.server.boards[serial]
        except (ValueError, KeyError):
            raise FileNotFoundError(filename)
        if board.ip is not None and self.client_address[0] != board.ip:
            raise PermissionError(lang._('IP does not match'))
        boot_filename = Path('').joinpath(*p.parts[1:])
        try:
            image, fs = self.server.images[serial]
        except KeyError:
            image = DiskImage(board.image)
            fs = FatFileSystem(image.partitions[board.partition].data)
            self.server.images[serial] = (image, fs)
        return fs.root / boot_filename


class BootServer(TFTPBaseServer):
    """
    A descendent of :class:`~nobodd.tftpd.TFTPBaseServer` that is configured
    with *boards*, a mapping of Pi serial numbers to
    :class:`~nobodd.config.Board` instances, and uses :class:`BootHandler` as
    the handler class.

    .. attribute:: boards

        The mapping of Pi serial numbers to :class:`~nobodd.config.Board`
        instances.
    """
    def __init__(self, server_address, boards):
        if isinstance(server_address, int):
            fd = server_address
            # We're being passed an fd directly. In this case, we don't
            # actually want the super-class to go allocating a socket but we
            # can't avoid it so we allocate an ephemeral localhost socket, then
            # close it and overwrite self.socket. However, we need to remember
            # we don't *own* the socket, so self.server_close doesn't go
            # closing it
            self._own_sock = False
            if not stat.S_ISSOCK(os.fstat(fd).st_mode):
                raise RuntimeError(lang._(
                    'inherited fd {fd} is not a socket').format(fd=fd))
            super().__init__(
                ('127.0.0.1', 0), BootHandler, bind_and_activate=False)
            self.socket.close()
            try:
                # XXX Using socket's fileno argument in this way isn't
                # guaranteed to work on all platforms (though it should on
                # Linux); see https://bugs.python.org/issue28134 for more
                # details
                self.socket = socket.socket(fileno=fd)
                self.socket_type = self.socket.type
                if self.socket_type != socket.SOCK_DGRAM:
                    raise RuntimeError(lang._(
                        'inherited fd {fd} is not a datagram socket')
                        .format(fd=fd))
                # Setting self.address_family is required because TFTPSubServer
                # uses this to figure out the family of the ephemeral socket to
                # allocate for client connections
                self.address_family = self.socket.family
                if self.address_family not in (socket.AF_INET, socket.AF_INET6):
                    raise RuntimeError(lang._(
                        'inherited fd {fd} is not an INET or INET6 socket')
                        .format(fd=fd))
                self.server_address = self.socket.getsockname()
            except:
                # The server's initialization creates the TFTPSubServers thread
                # which must be terminated if we abort the initialization at
                # this point
                self.server_close()
                raise
        else:
            self._own_sock = True
            super().__init__(server_address, BootHandler)
        self.boards = boards
        self.images = {}

    def server_close(self):
        if not self._own_sock:
            # We're intending to close the server, but we don't actually own
            # the socket's fd; detach it to make sure it stays alive in case
            # we're reloading and want to re-create a socket from it again
            self.socket.detach()
        super().server_close()
        try:
            for image, fs in self.images.values():
                fs.close()
                image.close()
            self.images.clear()
        except AttributeError:
            # Ignore AttributeError in the case of early termination
            pass


def get_parser():
    """
    Returns the command line parser for the application, pre-configured with
    defaults from the application's configuration file(s). See
    :func:`~nobodd.config.ConfigArgumentParser` for more information.
    """
    parser = ConfigArgumentParser(
        description=__doc__,
        template=resources.files('nobodd') / 'default.conf')
    parser.add_argument(
        '--version', action='version', version=version('nobodd'))

    tftp_section = parser.add_argument_group('tftp', section='tftp')
    tftp_section.add_argument(
        '--listen',
        key='listen', type=str, metavar='ADDR',
        help=lang._(
            "the address on which to listen for connections (default: "
            "%(default)s)"))
    tftp_section.add_argument(
        '--port',
        key='port', type=port, metavar='PORT',
        help=lang._(
            "the port on which to listen for connections (default: "
            "%(default)s)"))
    tftp_section.add_argument(
        '--includedir',
        key='includedir', type=Path, metavar='PATH',
        help=argparse.SUPPRESS)

    parser.add_argument(
        '--board', dest='boards', type=Board.from_string, action='append',
        metavar='SERIAL,FILENAME[,PART[,IP]]', default=[],
        help=lang._(
            "can be specified multiple times to define boards which are to be "
            "served boot images over TFTP; if PART is omitted the default is "
            "1; if IP is omitted the IP address will not be checked"))

    # Reading the config twice is ... inelegant, but it's the simplest way to
    # handle the include path and avoid double-parsing values. The first pass
    # reads the default locations; the second pass re-reads the default
    # locations and whatever includes are found
    defaults = parser.read_configs(CONFIG_LOCATIONS)
    defaults = parser.read_configs(CONFIG_LOCATIONS + tuple(sorted(
        p for p in Path(defaults['tftp'].pop('includedir')).glob('*.conf')
    )))

    # Fix-up defaults for [board:*] sections
    parser.set_defaults_from(defaults)
    parser.set_defaults(boards=parser.get_default('boards') + [
        Board.from_section(defaults, section)
        for section in defaults
        if section.startswith('board:')
    ])
    return parser


# Signal handling; this stuff is declared globally primarily for testing
# purposes. The exit_write and exit_read sockets can be used by the test suite
# to simulate signals to the application, and the signals are registered
# outside of main to ensure this occurs in the Python main thread
# (signal.signal cannot be called from a subordinate thread)
exit_write, exit_read = socket.socketpair()

def on_sigint(signal, frame):
    exit_write.send(b'INT ')
signal.signal(signal.SIGINT, on_sigint)


def on_sigterm(signal, frame):
    exit_write.send(b'TERM')
signal.signal(signal.SIGTERM, on_sigterm)


def on_sighup(signal, frame):
    exit_write.send(b'HUP ')
signal.signal(signal.SIGHUP, on_sighup)


class ReloadRequest(Exception):
    """
    Exception class raised in :func:`request_loop` to cause a reload. Handled
    in :func:`main`.
    """


class TerminateRequest(Exception):
    """
    Exception class raised in :func:`request_loop` to cause service
    termination. Handled in :func:`main`. Takes the return code of the
    application as the first argument.
    """
    def __init__(self, returncode, message=''):
        super().__init__(message)
        self.returncode = returncode


def request_loop(server_address, boards):
    """
    The application's request loop. Takes the *server_address* to bind to,
    which may be a ``(address, port)`` tuple, or an :class:`int`
    file-descriptor passed by a service manager, and the *boards*
    configuration, a :class:`dict` mapping serial numbers to
    :class:`~nobodd.config.Board` instances.

    Raises :exc:`ReloadRequest` or :exc:`TerminateRequest` in response to
    certain signals, but is an infinite loop otherwise.
    """
    sd = get_systemd()

    with \
        BootServer(server_address, boards) as server, \
        DefaultSelector() as selector:

        selector.register(exit_read, EVENT_READ)
        selector.register(server, EVENT_READ)
        sd.ready()
        server.logger.info(lang._('Ready'))
        while True:
            for key, events in selector.select():
                if key.fileobj == exit_read:
                    code = exit_read.recv(4)
                    if code == b'INT ':
                        sd.stopping()
                        server.logger.warning(lang._('Interrupted'))
                        raise TerminateRequest(returncode=2)
                    elif code == b'TERM':
                        sd.stopping()
                        server.logger.warning(lang._('Terminated'))
                        raise TerminateRequest(returncode=0)
                    elif code == b'HUP ':
                        sd.reloading()
                        server.logger.info(lang._('Reloading configuration'))
                        raise ReloadRequest()
                    else:
                        assert False, f'internal error'
                elif key.fileobj == server:
                    server.handle_request()
                else:
                    assert False, 'internal error'


def main(args=None):
    """
    The main entry point for the :program:`nobodd-tftpd` application. Takes
    *args*, the sequence of command line arguments to parse. Returns the exit
    code of the application (0 for a normal exit, and non-zero otherwise).

    If ``DEBUG=1`` is found in the application's environment, top-level
    exceptions will be printed with a full back-trace. ``DEBUG=2`` will launch
    PDB in port-mortem mode.
    """
    try:
        debug = int(os.environ['DEBUG'])
    except (KeyError, ValueError):
        debug = 0
    lang.init()
    sd = get_systemd()

    BootServer.logger.addHandler(logging.StreamHandler(sys.stderr))
    BootServer.logger.setLevel(logging.DEBUG if debug else logging.INFO)

    while True:
        try:
            conf = get_parser().parse_args(args)
            boards = {
                board.serial: board
                for board in conf.boards
            }

            if conf.listen == 'stdin':
                # Yes, this should always be zero but ... just in case
                server_address = sys.stdin.fileno()
            elif conf.listen == 'systemd':
                fds = sd.listen_fds()
                if len(fds) != 1:
                    raise RuntimeError(lang._(
                        'Expected 1 fd from systemd but got {fds}'
                    ).format(fds=len(fds)))
                server_address, name = fds.popitem()
            else:
                server_address = (conf.listen, conf.port)
            request_loop(server_address, boards)
        except ReloadRequest:
            continue
        except TerminateRequest as err:
            return err.returncode
        except Exception as err:
            sd.stopping()
            if not debug:
                print(str(err), file=sys.stderr)
                return 1
            elif debug == 1:
                raise
            else:
                import pdb
                pdb.post_mortem()
                return 1
