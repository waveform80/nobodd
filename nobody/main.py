import sys
import logging

from .disk import DiskImage
from .fs import FatFileSystem
from .tftp import SimpleTFTPServer


def main():
    server = SimpleTFTPServer(('0.0.0.0', 1069), '.')
    server.logger.addHandler(logging.StreamHandler(sys.stderr))
    server.logger.setLevel(logging.INFO)
    server.serve_forever()


def main2():
    filename, partition, pattern = sys.argv[1:]
    partition = int(partition)

    img = DiskImage(filename)
    print(img.partitions.style)
    for part in img.partitions:
        print(part)
    fs = FatFileSystem(img.partitions[partition].data)
    print(fs.fat_type)
    print(fs.label)
    print(fs.root.stat())
    if pattern:
        for path in fs.root.glob(pattern):
            print(path)
    else:
        for path in fs.root.iterdir():
            print(path)
    return 0
