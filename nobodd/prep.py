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

from .disk import DiskImage
from .fs import FatFileSystem
from .config import CONFIG_LOCATIONS, ConfigArgumentParser, size

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
        'image', type=Path,
        help="The target image to customize")
    parser.add_argument(
        '--size', type=size, default='16GB',
        help="The size to expand the image to; default: %(default)s")
    parser.add_argument(
        '--nbd-host', type=str, default=socket.getfqdn(),
        help="The hostname of the nbd server to connect to for the root "
        "device; defaults to the local machine's FQDN")
    parser.add_argument(
        '--nbd-name', type=str, default=None,
        help="The name of the nbd share to use as the root device; defaults "
        "to the stem of the *image* name")
    parser.add_argument(
        '--cmdline', type=str, default='cmdline.txt',
        help="The name of the file containing the kernel command line on the "
        "boot partition; default: %(default)s")
    parser.add_argument(
        '--boot-partition', type=int, default=None,
        help="Which partition is the boot partition within the image; "
        "default is the first FAT partition (identified by partition type) "
        "found in the image")
    parser.add_argument(
        '--root-partition', type=int, default=None,
        help="Which partition is the root partition within the image "
        "default is the first non-FAT partition (identified by partition "
        "type) found in the image")

    defaults = parser.read_configs(CONFIG_LOCATIONS)
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
            {0x01, 0x06, 0x0B, 0x0C, 0x0E, 0x0F, 0xEF}
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
        conf.logger.setLevel(logging.INFO)
        if conf.boot_partition is None or conf.root_partition is None:
            detect_partitions(conf)
        if conf.nbd_name is None:
            conf.nbd_name = conf.image.stem

        prepare_image(conf)
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
