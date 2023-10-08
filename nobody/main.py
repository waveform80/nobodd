import sys

from .disk import DiskImage
from .fs import FatFileSystem

def main():
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
        for path in fs.root.rglob(pattern):
            print(path)
    else:
        for path in fs.root.iterdir():
            print(path)
    return 0
