import sys
import logging
from pathlib import Path
from socketserver import ThreadingMixIn

from .disk import DiskImage
from .fs import FatFileSystem
from .tftpd import TFTPBaseHandler, TFTPBaseServer


class BootHandler(TFTPBaseHandler):
    def resolve_path(self, filename):
        p = Path(filename)
        if p.parts:
            serial = p.parts[0]
            boot_filename = Path.joinpath(*p.parts[1:])
            try:
                fs = self.server.bootfs[serial]
            except KeyError:
                try:
                    image = self.server.images[serial]
                except KeyError:
                    try:
                        (
                            image_filename, partition, mac
                        ) = self.server.machines[serial]
                    except KeyError:
                        raise FileNotFoundError(filename)
                    image = DiskImage(image_filename)
                    self.server.images[serial] = image
                fs = FatFileSystem(image.partitions[partition].data)
                self.server.bootfs[serial] = fs
            return fs.root / boot_filename


class BootServer(ThreadingMixIn, TFTPBaseServer):
    def __init__(self, server_address, machines):
        self.machines = machines
        self.images = {}
        self.bootfs = {}
        super().__init__(server_address, BootHandler)

    def server_close(self):
        super().server_close()
        self.bootfs.clear()
        for image in self.images.values():
            image.close()
        self.images.clear()


def main():
    machines = {
        '89025d75': (
            'ubuntu-22.04.3-preinstalled-server-arm64+raspi.img', 1,
            'dc:a6:32:02:36:ba'),
    }
    with BootServer(('::', 69), machines) as server:
        server.logger.addHandler(logging.StreamHandler(sys.stderr))
        server.logger.setLevel(logging.INFO)
        server.serve_forever()
