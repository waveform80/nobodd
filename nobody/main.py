import sys

from .disk import DiskImage
from .fs import FatFileSystem

def main():
    img = DiskImage(sys.argv[1])
    print(img.partitions.style)
    for part in img.partitions:
        print(part)
    fs = FatFileSystem(img.partitions[1].data)
    print(fs.fat_type)
    print(fs.label)
    print(fs.root.stat())
    print('ls /')
    for p in fs.root.iterdir():
        print(p)
    d = fs.root / 'adir/nobody'
    import pudb; pudb.set_trace()
    print(d.parents)
    print('ls /adir/nobody/*.py')
    for p in (fs.root / 'adir/nobody').iterdir():
        print(p)
    return 0

img = DiskImage('../test.img')
fs = FatFileSystem(img.partitions[1].data)
