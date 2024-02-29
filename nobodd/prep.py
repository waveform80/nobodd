# nobodd: a boot configuration tool for the Raspberry Pi
#
# Copyright (c) 2023-2024 Dave Jones <dave.jones@canonical.com>
# Copyright (c) 2023-2024 Canonical Ltd.
#
# SPDX-License-Identifier: GPL-3.0

"""
Customizes an OS image to prepare it for netbooting via TFTP. Specifically,
this expands the image to a specified size (the assumption being the image is a
copy of a minimally sized template image), then updates the kernel command line
on the boot partition  to point to an NBD server.
"""

import os
import sys
import mmap
import socket
import logging
import argparse
from pathlib import Path
from uuid import UUID
from shutil import copyfileobj

from .disk import DiskImage
from .fs import FatFileSystem
from .config import (
    CONFIG_LOCATIONS,
    ConfigArgumentParser,
    size,
    serial,
    Board,
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
    parser.add_argument(
        '-v', '--verbose', dest='log_level',
        action='store_const', const=logging.INFO,
        help="Print more output")
    parser.add_argument(
        '-q', '--quiet', dest='log_level',
        action='store_const', const=logging.CRITICAL,
        help="Print no output")

    parser.add_argument(
        'image', type=Path,
        help="The target image to customize")
    parser.add_argument(
        '-s', '--size', type=size, default='16GB',
        help="The size to expand the image to; default: %(default)s")
    parser.add_argument(
        '--nbd-host', type=str, metavar='HOST', default=socket.getfqdn(),
        help="The hostname of the nbd server to connect to for the root "
        "device; defaults to the local machine's FQDN")
    parser.add_argument(
        '--nbd-name', type=str, metavar='NAME', default=None,
        help="The name of the nbd share to use as the root device; defaults "
        "to the stem of the *image* name")
    parser.add_argument(
        '--cmdline', type=str, metavar='NAME', default='cmdline.txt',
        help="The name of the file containing the kernel command line on the "
        "boot partition; default: %(default)s")
    parser.add_argument(
        '--boot-partition', type=int, metavar='NUM', default=None,
        help="Which partition is the boot partition within the image; "
        "default is the first FAT partition (identified by partition type) "
        "found in the image")
    parser.add_argument(
        '--root-partition', type=int, metavar='NUM', default=None,
        help="Which partition is the root partition within the image "
        "default is the first non-FAT partition (identified by partition "
        "type) found in the image")
    parser.add_argument(
        '-C', '--copy', type=Path, metavar='PATH', action='append', default=[],
        help="Copy the specified file or directory into the boot partition. "
        "This may be given multiple times to specify multiple items to copy")
    parser.add_argument(
        '-R', '--remove', type=Path, metavar='PATH', action='append', default=[],
        help="Remove the specified file or directory from the boot "
        "partition. This may be given multiple times to specify multiple "
        "items to delete")
    parser.add_argument(
        '--serial', type=serial, metavar='HEX', default=None,
        help="Defines the serial number of the Raspberry Pi that will be "
        "served this image. When this option is given, a board configuration "
        "compatible with nobodd-tftpd may be output with --tftpd-conf")
    parser.add_argument(
        '--tftpd-conf', type=argparse.FileType('w'), metavar='FILE', default=None,
        help="If specified, write a board configuration compatible with "
        "nobodd-tftpd to the specified file; requires --serial to be given")
    parser.add_argument(
        '--nbd-conf', type=argparse.FileType('w'), metavar='FILE', default=None,
        help="If specified, write a share configuration compatible with "
        "nbd-server to the specified file")

    defaults = parser.read_configs(CONFIG_LOCATIONS)
    parser.set_defaults(log_level=logging.WARNING)
    parser.set_defaults_from(defaults)
    return parser


def prepare_image(conf):
    """
    Given the script's configuration in *conf*, an :class:`argparse.Namespace`,
    resize the target image, and re-write the kernel command line within its
    boot partition to point to the configured NBD server and share.
    """
    with conf.image.open('ab') as f:
        size = f.seek(0, os.SEEK_END)
        if size < conf.size:
            conf.logger.info(f'Resizing %s to %d bytes', conf.image, conf.size)
            f.seek(conf.size)
            f.truncate()
        else:
            conf.logger.info(
                'Skipping resize; %s is already %d bytes or larger',
                conf.image, conf.size)
    with \
        DiskImage(conf.image, access=mmap.ACCESS_WRITE) as img, \
        FatFileSystem(img.partitions[conf.boot_partition].data) as fs:

        remove_items(fs, conf)
        copy_items(fs, conf)
        rewrite_cmdline(fs, conf)


def remove_items(fs, conf):
    """
    In *fs*, a :class:`~nobodd.fs.FatFileSystem`, remove all items in the
    :class:`list` *conf.remove*, where *conf* is the script's configuration.

    If any item is a directory, it and all files under it will be removed
    recursively. If an item in *to_remove* does not exist, a warning will be
    printed, but no error is raised.
    """
    for item in conf.remove:
        item = fs.root / str(item)
        if item.exists():
            conf.logger.info(
                'Removing %s from partition %d', item, conf.boot_partition)
            if item.is_dir():
                dirs = []
                for subitem in item.rglob('*'):
                    if subitem.is_dir():
                        dirs.append(subitem)
                    else:
                        subitem.unlink()
                for subitem in dirs:
                    subitem.rmdir()
                item.rmdir()
            else:
                item.unlink()
        else:
            conf.logger.warning(
                "No such file/dir %s in partition %d", item, conf.boot_partition)


def copy_items(fs, conf):
    """
    Copy all :class:`~pathlib.Path` items in the :class:`list` *conf.copy* into
    *fs*, a :class:`~nobodd.fs.FatFileSystem`, where *conf* is the script's
    configuration.

    If an item is a directory, it and all files under it will be copied
    recursively. If an item is a hard-link or a sym-link it will be copied as a
    regular file (since FAT does not support links). If an item does not exist,
    an :exc:`OSError` will be raised. This is in contrast to :func:`to_remove`
    since it is assumed that control over the source file-system is under the
    caller's control, which is not the case in :func:`to_remove`.
    """
    for item in conf.copy:
        conf.logger.info(
            'Copying %s into partition %d', item, conf.boot_partition)
        if item.is_dir():
            copy_root = fs.root / item.name
            copy_root.mkdir(exist_ok=True)
            for subitem in item.rglob('*'):
                name = subitem.relative_to(item)
                if subitem.is_dir():
                    (copy_root / str(name)).mkdir(exist_ok=True)
                else:
                    with \
                        subitem.open('rb') as source, \
                        (copy_root / str(name)).open('wb') as target:

                        copyfileobj(source, target)
        else:
            with \
                item.open('rb') as source, \
                (fs.root / item.name).open('wb') as target:

                copyfileobj(source, target)


def rewrite_cmdline(fs, conf):
    """
    Given the script's configuration *conf*, find the file *conf.cmdline*
    containing the kernel command-line in the :class:`~nobodd.fs.FatFileSystem`
    *fs*, and re-write it to point the NBD share specified.
    """
    cmdline = fs.root / conf.cmdline
    conf.logger.info(
        'Re-writing %s in partition %d', conf.cmdline, conf.boot_partition)
    params = cmdline.read_text()
    try:
        params = params[:params.index('\n')]
    except ValueError:
        pass # no newline in the file
    params = [
        param
        for param in params.split()
        if not param.startswith('root=')
    ]
    params[:0] = [
        'ip=dhcp',
        f'nbdroot={conf.nbd_host}/{conf.nbd_name}',
        f'root=/dev/nbd0p{conf.root_partition}',
    ]
    cmdline.write_text(' '.join(params))


def detect_partitions(conf):
    """
    Given the script's configuration in *conf*, an :class:`argparse.Namespace`,
    open the target image, and attempt to detect the root and/or boot
    partition.
    """
    conf.logger.info('Detecting partitions')
    with \
        conf.image.open('rb') as img_file, \
        DiskImage(img_file) as img:

        fat_types = (
            {UUID('ebd0a0a2-b9e5-4433-87c0-68b6b72699c7'),
             UUID('c12a7328-f81f-11d2-ba4b-00a0c93ec93b')}
            if img.partitions.style == 'gpt' else
            {0x01, 0x06, 0x0B, 0x0C, 0x0E, 0xEF}
        )
        for num, part in img.partitions.items():
            with part:
                if part.type in fat_types:
                    if conf.boot_partition is None:
                        try:
                            fs = FatFileSystem(part.data)
                        except ValueError:
                            continue
                        else:
                            conf.boot_partition = num
                            conf.logger.info(
                                'Boot partition is %d (%s)',
                                conf.boot_partition, fs.fat_type)
                            fs.close()
                else:
                    if conf.root_partition is None:
                        try:
                            fs = FatFileSystem(part.data)
                        except ValueError:
                            conf.root_partition = num
                            conf.logger.info(
                                'Root partition is %d',
                                conf.root_partition)
                        else:
                            fs.close()
                            continue
                if conf.boot_partition is not None:
                    if conf.root_partition is not None:
                        break
    if conf.boot_partition is None:
        raise ValueError('Unable to detect boot partition')
    if conf.root_partition is None:
        raise ValueError('Unable to detect root partition')


def main(args=None):
    """
    The main entry point for the :program:`nobodd-prep` application. Takes
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

    try:
        conf = get_parser().parse_args(args)
        conf.logger = logging.getLogger('prep')
        conf.logger.addHandler(logging.StreamHandler(sys.stderr))
        conf.logger.setLevel(logging.DEBUG if debug else conf.log_level)
        if conf.boot_partition is None or conf.root_partition is None:
            detect_partitions(conf)
        if conf.nbd_name is None:
            conf.nbd_name = conf.image.stem

        prepare_image(conf)
        if conf.tftpd_conf is not None and conf.serial is not None:
            board = Board(conf.serial, conf.image, conf.boot_partition, None)
            conf.tftpd_conf.write(str(board))
            conf.tftpd_conf.write('\n')
        if conf.nbd_conf is not None:
            conf.nbd_conf.write(f"[{conf.nbd_name}]\n")
            conf.nbd_conf.write(f"exportname = {conf.image}\n")
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
