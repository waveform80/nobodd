"""
A read-only TFTP server capable of reading FAT boot partitions from within
image files or devices. Intended to be paired with a block-device service (e.g.
NBD) for netbooting Raspberry Pis.
"""

import os
import sys
import logging
from pathlib import Path
from socketserver import ThreadingMixIn

from . import config
from .disk import DiskImage
from .fs import FatFileSystem
from .tftpd import TFTPBaseHandler, TFTPBaseServer


class BootHandler(TFTPBaseHandler):
    def resolve_path(self, filename):
        p = Path(filename)
        if not p.parts:
            raise FileNotFoundError()
        try:
            serial = int(p.parts[0], base=16)
            board = self.server.boards[serial]
        except (ValueError, KeyError):
            raise FileNotFoundError(filename)
        boot_filename = Path('').joinpath(*p.parts[1:])
        try:
            image, fs = self.server.images[serial]
        except KeyError:
            image = DiskImage(board.image)
            fs = FatFileSystem(image.partitions[board.partition].data)
            self.server.images[serial] = (image, fs)
        return fs.root / boot_filename


class BootServer(ThreadingMixIn, TFTPBaseServer):
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
    defaults = config.get_config()
    parser = config.get_parser(defaults, description=__doc__)
    parser.set_defaults_from(defaults)
    return parser


def main(args=None):
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
