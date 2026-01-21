# nobodd: a boot configuration tool for the Raspberry Pi
#
# Copyright (c) 2026 Dave Jones <dave.jones@canonical.com>
# Copyright (c) 2026 Canonical Ltd.
#
# SPDX-License-Identifier: GPL-3.0

"""
Run shell-like commands against the file-system and/or FAT partitions within
file-system image. This is intended for use in scripting the preparation of
images for use with the :program:`nobodd-tftpd` server.
"""

import os
import re
import sys
import pwd
import grp
import stat
import mmap
import errno
import logging
import argparse
import datetime as dt
from pathlib import Path
from uuid import UUID
from importlib import resources
from importlib.metadata import version
from contextlib import contextmanager
from itertools import chain, repeat

from . import lang
from .disk import DiskImage
from .fs import FatFileSystem
from .path import FatPath
from .transfer import copy_bytes
from .config import ConfigArgumentParser


class StdPath:
    def __init__(self, for_write):
        self._for_write = for_write

    def __repr__(self):
        return f'{self.__class__.__name__}(for_write={self._for_write})'

    @property
    def name(self):
        return 'stdout' if self._for_write else 'stdin'

    def open(self, mode):
        if self._for_write and set(mode) == {'w', 'b'}:
            return sys.stdout.buffer
        elif not self._for_write and set(mode) == {'r', 'b'}:
            return sys.stdin.buffer
        else:
            raise ValueError(
                f'Cannot open {self.name} with mode {mode!r}')

    def unlink(self):
        raise FileNotFoundError(f'Cannot unlink {self.name}')


_image_re = re.compile(r'^(?P<image>.*?):(?P<part>[1-9][0-9]{,2})?(?P<path>/.*)$')

@contextmanager
def get_paths(inputs, outputs, *, allow_std=False):
    """
    Given *inputs* and *outputs*, two iterables of filenames (or paths), which
    may include image prefixes (e.g. ``test.img:1/filename``), returns a
    :class:`dict` mapping each filename to a :class:`~pathlib.Path` or
    :class:`~nobodd.path.FatPath` instance.
    """
    paths = [
        (path, None, None, path, for_write)
        if (match := _image_re.match(path)) is None else
        (path, match['image'], int(match['part'] or 1), match['path'], for_write)
        for path, for_write in chain(
            zip(inputs, repeat(False)),
            zip(outputs, repeat(True)))
    ]
    access = {}
    parts = {}
    for path, image, part, part_path, for_write in paths:
        if image is not None:
            access[image] = for_write or access.get(image, False)
            parts.setdefault(image, []).append(part)
    images = {
        image: DiskImage(
            image,
            access=mmap.ACCESS_WRITE if output else mmap.ACCESS_READ)
        for image, output in access.items()
    }
    try:
        fses = {
            (image, part):
                FatFileSystem(images[image].partitions[part].data)
            for image, part_nums in parts.items()
            for part in part_nums
        }
    except KeyError:
        raise FileNotFoundError(f'Partition {part} not found in {image}')
    try:
        yield {
            path:
                StdPath(for_write) if allow_std and path == '-' else
                Path(path) if image is None else
                fses[(image, part)].root / part_path
            for path, image, part, part_path, for_write in paths
        }
    finally:
        for fs in fses.values():
            fs.close()
        for image in images.values():
            image.close()


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
        help=lang._("Print more output"))
    parser.add_argument(
        '-q', '--quiet', dest='log_level',
        action='store_const', const=logging.CRITICAL,
        help=lang._("Print no output"))
    commands = parser.add_subparsers(title=lang._("commands"))

    help_cmd = commands.add_parser(
        'help',
        description=lang._(
            "With no arguments, displays a list of %(prog)s commands. If a "
            "command name is given, displays the description and options "
            "for the named command"),
        help=lang._("Displays help for the specified command"))
    help_cmd.add_argument(
        'cmd', metavar='command', nargs='?',
        help=lang._("The command to display help for"))
    help_cmd.set_defaults(func=do_help)

    cat_cmd = commands.add_parser(
        'cat',
        description=lang._(
            "Concatenate content from the given files, writing it to "
            "stdout by default. If - is given as a filename, or if no "
            "filenames are specified, stdin is read. In order to permit "
            "output to a file within an image, -o is provided to specify "
            "an output other than stdout"),
        help=lang._("Concatenate content into a single output"))
    cat_cmd.add_argument(
        'filenames', nargs='*',
        help=lang._("The input files"))
    cat_cmd.add_argument(
        '-o', '--output', metavar='filename', default='-',
        help=lang._("The output file (default: stdout)"))
    cat_cmd.set_defaults(func=do_cat)

    rm_cmd = commands.add_parser(
        'rm',
        description=lang._(
            "Removes the files or directories specified"),
        help=lang._("Removes files or directories"))
    rm_cmd.add_argument(
        'filenames', nargs='+',
        help=lang._("The files or directories to remove"))
    rm_cmd.add_argument(
        '-r', '-R', '--recursive', action='store_true',
        help=lang._("Remove directories and their contents recursively"))
    rm_cmd.add_argument(
        '-f', '--force', action='store_true',
        help=lang._("Do not error on non-existent arguments and never "
                    "prompt"))
    rm_cmd.set_defaults(func=do_rm)

    rmdir_cmd = commands.add_parser(
        'rmdir',
        description=lang._(
            "Removes the directories specified, which must be empty"),
        help=lang._("Remove empty directories"))
    rmdir_cmd.add_argument(
        'filenames', nargs='+',
        help=lang._("The directories to remove"))
    rmdir_cmd.set_defaults(func=do_rmdir)

    mkdir_cmd = commands.add_parser(
        'mkdir',
        description=lang._(
            "Creates the directories specified, which must not exist either "
            "as directories or regular files"),
        help=lang._("Make directories"))
    mkdir_cmd.add_argument(
        'filenames', nargs='+',
        help=lang._("The directories to create"))
    mkdir_cmd.add_argument(
        '-p', '--parents', action='store_true',
        help=lang._("Create parent directories as required"))
    mkdir_cmd.set_defaults(func=do_mkdir)

    touch_cmd = commands.add_parser(
        'touch',
        description=lang._(
            "Update last modified timestamps, creating any files that do not "
            "already exist"),
        help=lang._("Update file timestamps"))
    touch_cmd.add_argument(
        'filenames', nargs='+',
        help=lang._("The files to create or modify the timestamps of"))
    touch_cmd.set_defaults(func=do_touch)

    ls_cmd = commands.add_parser(
        'ls',
        description=lang._(
            "List information about the files, or the contents of the "
            "directories given. Entries will be sorted alphabetically"),
        help=lang._("List directory contents"))
    ls_cmd.add_argument(
        'filenames', nargs='+',
        help=lang._("The files or directories to list"))
    ls_cmd.add_argument(
        '-a', '--all', action='store_true',
        help=lang._("Do not ignore entries beginning with ."))
    ls_cmd.add_argument(
        '-l', dest='long', action='store_true',
        help=lang._("Show details beside listed entries"))
    ls_cmd.add_argument(
        '--sort', default='name',
        help=lang._("Sort on name (the default) / size / time / none"))
    ls_cmd.add_argument(
        '-U', dest='sort', action='store_const', const='none',
        help=lang._("Disable sorting"))
    ls_cmd.add_argument(
        '-S', dest='sort', action='store_const', const='size',
        help=lang._("Sort by file size"))
    ls_cmd.add_argument(
        '-t', dest='sort', action='store_const', const='time',
        help=lang._("Sort by modification time"))
    ls_cmd.add_argument(
        '-X', dest='sort', action='store_const', const='extension',
        help=lang._("Sort by entry extension"))
    ls_cmd.set_defaults(func=do_ls)

    cp_cmd = commands.add_parser(
        'cp',
        description=lang._(
            "Copy the specified file over the target file, if only one source "
            "is given, or copy the specified files and directories into the "
            "target directory, if the target is a directory"),
        help=lang._("Copy files and directories"))
    cp_cmd.add_argument(
        'filenames', nargs='+',
        help=lang._("The files or directories to copy"))
    cp_cmd.add_argument(
        'dest',
        help=lang._("The directory to copy into or the file to replace"))
    cp_cmd.set_defaults(func=do_cp)

    mv_cmd = commands.add_parser(
        'mv',
        description=lang._(
            "Move the specified file over the target file, if only one source "
            "is given, or move the specified files and directories into the "
            "target directory, if the target is a directory"),
        help=lang._("Move files and directories"))
    mv_cmd.add_argument(
        'filenames', nargs='+',
        help=lang._("The files or directories to copy"))
    mv_cmd.add_argument(
        'dest',
        help=lang._("The directory to move into or the file to replace"))
    mv_cmd.set_defaults(func=do_mv)

    return parser


def do_help(config):
    if config.cmd is not None:
        get_parser().parse_args([config.cmd, '-h'])
    else:
        get_parser().parse_args(['-h'])


def do_cat(config):
    with get_paths(config.filenames, [config.output], allow_std=True) as paths:
        with paths[config.output].open('wb') as out_f:
            for filename in config.filenames:
                path = paths[filename]
                with path.open('rb') as in_f:
                    copy_bytes(in_f, out_f)


def do_ls(config):
    key = {
        'none': lambda p: 0,
        'name': lambda p: p.name,
        'size': lambda p: p.stat().st_size,
        'extension': lambda p: list(reversed(p.suffixes)),
        'time': lambda p: p.stat().st_mtime,
    }[config.sort]

    def print_entry(path):
        if config.long:
            st = path.stat()
            now = dt.datetime.now(tz=dt.timezone.utc)
            mtime = dt.datetime.fromtimestamp(st.st_mtime, tz=dt.timezone.utc)
            fmt = (
                '%b %-2d %H:%M' if now - mtime < dt.timedelta(days=183) else
                '%b %-2d %-5Y')
            print(
                f'{stat.filemode(st.st_mode)} '
                f'{st.st_nlink:2d} '
                f'{pwd.getpwuid(st.st_uid).pw_name} '
                f'{grp.getgrgid(st.st_gid).gr_name} '
                f'{st.st_size:8d} '
                f'{mtime:{fmt}} '
                f'{path.name}'
            )
        else:
            print(path.name)

    with get_paths(config.filenames, []) as paths:
        for index, filename in enumerate(config.filenames):
            if len(config.filenames) > 1:
                if index > 0:
                    print()
                print(f'{filename}:')
            path = paths[filename]
            if path.is_dir():
                for entry in sorted(path.iterdir(), key=key):
                    if config.all or not entry.name.startswith('.'):
                        print_entry(entry)
            else:
                print_entry(path)


def do_rm(config):
    # TODO: Implement -r
    with get_paths([], config.filenames) as paths:
        for filename in config.filenames:
            path = paths[filename]
            path.rmdir()


def do_rmdir(config):
    with get_paths([], config.filenames) as paths:
        for filename in config.filenames:
            path = paths[filename]
            path.unlink()


def do_mkdir(config):
    with get_paths([], config.filenames) as paths:
        for filename in config.filenames:
            path = paths[filename]
            if config.parents:
                to_make = []
                while path != path.parent and not path.exists():
                    to_make.append(path)
                    path = path.parent
            else:
                to_make = [path]
            for p in reversed(to_make):
                p.mkdir()


def do_touch(config):
    with get_paths([], config.filenames) as paths:
        for filename in config.filenames:
            path = paths[filename]
            path.touch()


def do_cp(config):
    # TODO: Make this more efficient at re-writing files; when target exists,
    # open in r+b mode, truncate to source size, then seek(0) and copy
    # TODO: Implement -r
    def _copy(source, dest):
        if source.is_dir():
            if any(source.iterdir()):
                raise IsADirectoryError(
                    f'{filename} is a non-empty directory')
            dest.mkdir()
        else:
            with source.open('rb') as in_f:
                with dest.open('wb') as out_f:
                    copy_bytes(in_f, out_f)

    with get_paths(config.filenames, [config.dest]) as paths:
        if paths[config.dest].is_dir():
            dest_root = paths[config.dest]
            for filename in config.filenames:
                source = paths[filename]
                _copy(source, dest_root / source.name)
        elif len(config.filenames) > 1:
            raise NotADirectoryError(f'{config.dest} is not a directory')
        else:
            for filename in config.filenames:
                _copy(paths[filename], paths[config.dest])


def do_mv(config):
    def _move(source, dest):
        if source.is_dir():
            if any(source.iterdir()):
                raise IsADirectoryError(
                    f'{filename} is a non-empty directory')
            dest.mkdir()
        elif same_fs(source, dest):
            source.rename(dest)
        else:
            with source.open('rb') as in_f:
                with dest.open('wb') as out_f:
                    copy_bytes(in_f, out_f)
            source.unlink()

    with get_paths(config.filenames, [config.dest]) as paths:
        if paths[config.dest].is_dir():
            dest_root = paths[config.dest]
            for filename in config.filenames:
                source = paths[filename]
                _move(source, dest_root / source.name)
        elif len(config.filenames) > 1:
            raise NotADirectoryError(f'{config.dest} is not a directory')
        else:
            for filename in config.filenames:
                _move(paths[filename], paths[config.dest])


def same_fs(path1, path2):
    return (
        (
            # Both paths are in the Linux file-system
            isinstance(path1, Path) and
            isinstance(path2, Path)
        ) or (
            # Both paths are FatFileSystem paths, and both belong to the same
            # FatFileSystem instance
            isinstance(path1, FatPath) and
            isinstance(path2, FatPath) and
            path1.fs is path2.fs
        )
    )


def main(args=None):
    """
    The main entry point for the :program:`nobodd-sh` application. Takes
    *args*, the sequence of command line arguments to parse. Returns the exit
    code of the application (0 for a normal exit, non-zero for an error).

    If ``DEBUG=1`` is found in the application's environment, top-level
    exceptions will be printed with a full back-trace. ``DEBUG=2`` will launch
    PDB in post-mortem mode.
    """
    try:
        debug = int(os.environ['DEBUG'])
    except (KeyError, ValueError):
        debug = 0
    lang.init()

    try:
        conf = get_parser().parse_args(args)
        conf.func(conf)
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
