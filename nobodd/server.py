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
from socketserver import ThreadingMixIn
from selectors import DefaultSelector, EVENT_READ

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
            raise PermissionError('IP does not match')
        boot_filename = Path('').joinpath(*p.parts[1:])
        try:
            image, fs = self.server.images[serial]
        except KeyError:
            image = DiskImage(board.image)
            fs = FatFileSystem(image.partitions[board.partition].data)
            self.server.images[serial] = (image, fs)
        return fs.root / boot_filename


class BootServer(ThreadingMixIn, TFTPBaseServer):
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
        self.boards = boards
        self.images = {}
        if isinstance(server_address, int):
            if not stat.S_ISSOCK(os.fstat(server_address).st_mode):
                raise RuntimeError(
                    f'inherited fd {server_address} is not a socket')
            # If we've been passed an fd directly, we don't actually want the
            # super-class to go allocating a socket but we can't avoid it so we
            # allocate an ephemeral localhost socket, then close it and just
            # overwrite self.socket
            super().__init__(
                ('127.0.0.1', 0), BootHandler, bind_and_activate=False)
            self.socket.close()
            self.socket = socket.fromfd(
                server_address, self.address_family, self.socket_type)
            # TODO Check family and type?
            self.server_address = self.socket.getsockname()
        else:
            super().__init__(server_address, BootHandler)

    def server_close(self):
        super().server_close()
        for image, fs in self.images.values():
            fs.close()
            image.close()
        self.images.clear()


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
        help="the address on which to listen for connections "
        "(default: %(default)s)")
    tftp_section.add_argument(
        '--port',
        key='port', type=port, metavar='PORT',
        help="the port on which to listen for connections "
        "(default: %(default)s)")
    tftp_section.add_argument(
        '--includedir',
        key='includedir', type=Path, metavar='PATH',
        help=argparse.SUPPRESS)

    parser.add_argument(
        '--board', dest='boards', type=Board.from_string, action='append',
        metavar='SERIAL,FILENAME[,PART[,IP]]', default=[],
        help="can be specified multiple times to define boards which are to "
        "be served boot images over TFTP; if PART is omitted the default is "
        "1; if IP is omitted the IP address will not be checked")

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


class ReloadConfig(Exception):
    """
    Exception class raised in :func:`main` to cause a reload. Should never
    propogate outside this routine.
    """


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
    sd = get_systemd()

    while True:
        try:
            conf = get_parser().parse_args(args)
            boards = {
                board.serial: board
                for board in conf.boards
            }
            if not boards:
                raise RuntimeError('No boards defined')

            if conf.listen == 'stdin':
                # Yes, this should always be zero but ... just in case
                server_address = sys.stdin.fileno()
            elif conf.listen == 'systemd':
                fds = sd.listen_fds()
                if len(fds) != 1:
                    raise RuntimeError(
                        f'Expected 1 fd from systemd but got {len(fds)}')
                server_address, name = fds.popitem()
            else:
                server_address = (conf.listen, conf.port)

            with \
                BootServer(server_address, boards) as server, \
                DefaultSelector() as selector:

                server.logger.addHandler(logging.StreamHandler(sys.stderr))
                server.logger.setLevel(logging.DEBUG if debug else logging.INFO)
                selector.register(exit_read, EVENT_READ)
                selector.register(server, EVENT_READ)
                sd.ready()
                server.logger.info('Ready')
                while True:
                    for key, events in selector.select():
                        if key.fileobj == exit_read:
                            code = exit_read.recv(4)
                            if code == b'INT ':
                                sd.stopping()
                                server.logger.warning('Interrupted')
                                return 2
                            elif code == b'TERM':
                                sd.stopping()
                                server.logger.warning('Terminated')
                                return 0
                            elif code == b'HUP ':
                                server.logger.info('Reloading configuration')
                                raise ReloadConfig('SIGHUP')
                            else:
                                assert False, 'internal error'
                        elif key.fileobj == server:
                            server.handle_request()
                        else:
                            assert False, 'internal error'
        except ReloadConfig:
            sd.reloading()
            continue
        except Exception as e:
            sd.stopping()
            if not debug:
                print(str(e), file=sys.stderr)
                return 1
            elif debug == 1:
                raise
            else:
                import pdb
                pdb.post_mortem()
                return 1
