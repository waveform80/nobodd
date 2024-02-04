"""
A read-only TFTP server capable of reading FAT boot partitions from within
image files or devices. Intended to be paired with a block-device service (e.g.
NBD) for netbooting Raspberry Pis.
"""

import os
import sys
import logging
import argparse
from pathlib import Path
from socketserver import ThreadingMixIn

from .disk import DiskImage
from .fs import FatFileSystem
from .tftpd import TFTPBaseHandler, TFTPBaseServer
from .config import (
    CONFIG_LOCATIONS,
    ConfigArgumentParser,
    Board,
    port,
)

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
    :func:`~nobodd.config.get_config` and :func:`~nobodd.config.get_parser` for
    more information.
    """

    parser = ConfigArgumentParser(description=__doc__)
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
    defaults = parser.read_configs(CONFIG_LOCATIONS + tuple(
        p for p in Path(defaults['tftp'].pop('includedir')).glob('*.conf')
    ))

    # Fix-up defaults for [board:*] sections
    parser.set_defaults_from(defaults)
    parser.set_defaults(boards=parser.get_default('boards') + [
        Board.from_section(defaults, section)
        for section in defaults
        if section.startswith('board:')
    ])
    return parser


def main(args=None):
    """
    The main entry point for the :program:`nobodd` application. Takes *args*,
    the sequence of command line arguments to parse. Returns the exit code of
    the application (0 for a normal exit, and non-zero otherwise).

    If ``DEBUG=1`` is found in the application's environment, top-level
    exceptions will be printed with a full back-trace. ``DEBUG=2`` will launch
    PDB in port-mortem mode.
    """
    debug = int(os.environ.get('DEBUG', '0'))
    try:
        conf = get_parser().parse_args(args)
        boards = {
            board.serial: board
            for board in conf.boards
        }
        with BootServer((conf.listen, conf.port), boards) as server:
            server.logger.addHandler(logging.StreamHandler(sys.stderr))
            server.logger.setLevel(logging.DEBUG if debug else logging.INFO)
            server.serve_forever()
    except KeyboardInterrupt:
        print('Interrupted', file=sys.stderr)
        return 2
    except Exception as e:
        if not debug:
            print(str(e), file=sys.stderr)
            return 1
        elif debug == 1:
            raise
        else:
            import pdb
            pdb.post_mortem()
    else:
        return 0