import os
import sys
import shlex
import socket
import logging
import argparse
import subprocess as sp
from pathlib import Path
from uuid import UUID

from . import config
from .disk import DiskImage
from .fs import FatFileSystem


def fqdn():
    return 'localhost'


def get_parser():
    defaults = config.get_config()

    parser = config.ConfigArgumentParser()
    parser.add_argument(
        'template', type=Path,
        help="The template image to copy")
    parser.add_argument(
        'target', type=Path,
        help="The target image to create and customize")
    parser.add_argument(
        '--size', type=config.size, default='16GB',
        help="The size to expand the target image to; default: %(default)s`")
    parser.add_argument(
        '--nbd-host', type=str, default=fqdn(),
        help="The hostname of the nbd server to connect to for the root "
        "device; defaults to the local machine's FQDN")
    parser.add_argument(
        '--nbd-name', type=str, default=None,
        help="The name of the nbd share to use as the root device; defaults "
        "to the stem of the *target* name")
    parser.add_argument(
        '--cmdline', type=str, default='cmdline.txt',
        help="The name of the file containing the kernel command line on the "
        "boot partition; default: %(default)s")
    parser.add_argument(
        '--boot-partition', type=int, default=None,
        help="Which partition is the boot partition within the template "
        "image; default is the first FAT partition found in the image")
    parser.add_argument(
        '--root-partition', type=int, default=None,
        help="Which partition is the root partition within the template "
        "image; default is the first non-FAT partition found in the image")
    parser.set_defaults_from(defaults)
    return parser


def run(*cmdline, capture_output=False):
    logging.info(' '.join(shlex.quote(str(part)) for part in cmdline))
    kwargs = {'check': True}
    if capture_output:
        kwargs['capture_output'] = True
        kwargs['text'] = True
    return sp.run([str(s) for s in cmdline], **kwargs)


def prepare_cmdline(conf, root):
    cmdline = root / conf.cmdline
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
        'root=/dev/nbd0p2',
    ]
    cmdline.write_text(' '.join(params))


def prepare_image(conf):
    try:
        run('cp', '--reflink=auto', conf.template, conf.target)
        with conf.target.open('ab') as f:
            size = f.seek(0, os.SEEK_END)
            if size < conf.size:
                f.seek(conf.size)
                f.truncate()
        with (
            DiskImage(conf.target) as img,
            FatFileSystem(img.partitions[conf.boot_partition].data) as fs
        ):
            prepare_cmdline(conf, fs.root)
    except OSError:
        conf.target.unlink()
        raise


def main(args=None):
    debug = int(os.environ.get('DEBUG', '0'))
    try:
        conf = get_parser().parse_args(args)
        logging.root.addHandler(logging.StreamHandler(sys.stderr))
        logging.root.setLevel(logging.INFO)
        if conf.boot_partition is None or conf.root_partition is None:
            with (
                conf.template.open('rb') as img_file,
                DiskImage(img_file) as img
            ):
                fat_type = (
                    UUID('ebd0a0a2-b9e5-4433-87c0-68b6b72699c7')
                    if img.partitions.style == 'gpt' else 12)
                for num, part in img.partitions.items():
                    with part:
                        if conf.boot_partition is None and part.type == fat_type:
                            conf.boot_partition = num
                        if conf.root_partition is None and part.type != fat_type:
                            conf.root_partition = num
                        if conf.boot_partition is not None:
                            if conf.root_partition is not None:
                                break
        if conf.nbd_host is None:
            conf.nbd_host = socket.getfqdn()
        if conf.nbd_name is None:
            conf.nbd_name = conf.target.stem

        prepare_image(conf)
    except KeyboardInterrupt:
        if not debug:
            print('Interrupted', file=sys.stderr)
            return 1
        elif debug == 1:
            raise
        else:
            import pdb
            pdb.post_mortem()
    else:
        return 0
