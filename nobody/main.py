import sys

from .fs import DiskImage

def main():
    img = DiskImage(sys.argv[1])
    print(img.partitions.style)
    for part in img.partitions:
        print(part)
    return 0
