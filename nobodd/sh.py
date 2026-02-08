# nobodd: a boot configuration tool for the Raspberry Pi
#
# Copyright (c) 2026 Dave Jones <dave.jones@canonical.com>
# Copyright (c) 2026 Canonical Ltd.
#
# SPDX-License-Identifier: GPL-3.0

"""
Run shell-like commands against the file-system and/or FAT partitions within
file-system image. This is intended for use in scripting the preparation of
images for use with the nobodd-tftpd server. Filenames will be parsed as
regular filenames unless they contain ":/" or ":N/" where N is a partition
number. If so, the portion before ":" is treated as an image file, the N
(if specified) the partition within that image (the first auto-detected FAT
partition is used if N is not specified), and the portion from "/" onwards as
an absolute path within that partition. As such the application may be used to
copy (or move) files to / from / within FAT file-systems within images.
"""

import os
import re
import sys
import pwd
import grp
import stat
import mmap
import logging
import datetime as dt
from uuid import UUID
from pathlib import Path
from importlib import resources
from importlib.metadata import version
from contextlib import contextmanager, nullcontext, suppress
from itertools import chain, repeat

from . import lang
from .disk import DiskImage
from .fs import FatFileSystem
from .path import FatPath
from .transfer import copy_bytes
from .config import ConfigArgumentParser


class StdPath:
    """
    A rudimentary path-like object representing stdin / stdout. Only supports
    the :attr:`name` property, and the :meth:`open` and :meth:`unlink`
    methods.
    """
    def __init__(self, for_write):
        self._for_write = for_write

    def __repr__(self):
        return f'{self.__class__.__name__}(for_write={self._for_write})'

    @property
    def name(self):
        """
        Returns the name of the standard stream this path represents.
        """
        return 'stdout' if self._for_write else 'stdin'

    def open(self, mode):
        """
        Returns the standard stream represented by the path.
        """
        # nullcontext used to ensure we don't attempt to close stdin / stdout
        # when we're closing other files
        if self._for_write and set(mode) == {'w', 'b'}:
            return nullcontext(sys.stdout.buffer)
        elif not self._for_write and set(mode) == {'r', 'b'}:
            return nullcontext(sys.stdin.buffer)
        else:
            raise ValueError(
                f'Cannot open {self.name} with mode {mode!r}')

    def unlink(self):
        """
        Raises an error if an attempt is made to remove a standard stream.
        """
        raise FileNotFoundError(f'Cannot unlink {self.name}')


def fat_types(disk):
    """
    Given *disk*, a :class:`~nobodd.disk.DiskImage`, yield tuples of
    (:class:`int`, :class:`str`) where the first item is the partition number,
    and the second is either the FAT type detected (one of "fat12", "fat16", or
    "fat32"), "maybefat" which indicates the partition type is valid for FAT
    (see below) but the FAT file-system couldn't be detected, or "notfat" which
    indicates the partition type is not valid for FAT.

    In order for a partition to be detected as FAT it must have a valid
    partition type (basic data or EFI system partition for GPT partition
    tables, or one of the FAT partition types for MBR tables), and a
    :class:`FatFileSystem` must be successfully constructed on its content.
    """
    fat_types = (
        {UUID('ebd0a0a2-b9e5-4433-87c0-68b6b72699c7'),
         UUID('c12a7328-f81f-11d2-ba4b-00a0c93ec93b')}
        if disk.partitions.style == 'gpt' else
        {0x01, 0x06, 0x0B, 0x0C, 0x0E, 0xEF}
    )
    for num, part in disk.partitions.items():
        with part:
            try:
                with FatFileSystem(part.data) as fs:
                    yield num, fs.fat_type
            except ValueError:
                yield num, 'maybefat' if part.type in fat_types else 'notfat'


_image_re = re.compile(r'^(?P<image>.*?):(?P<part>[1-9][0-9]{,2})?(?P<path>/.*)$')

@contextmanager
def get_paths(inputs, outputs, *, allow_std=False):
    """
    Given *inputs* and *outputs*, two iterables of filenames (or paths), which
    may include image prefixes (e.g. ``test.img:1/filename``), returns a
    :class:`dict` mapping each filename to a :class:`~pathlib.Path` or
    :class:`~nobodd.path.FatPath` instance.
    """
    def first_fat_partition(disk):
        for number, fat_type in fat_types(disk):
            if fat_type.startswith('fat'):
                return number
        raise ValueError('Unable to detect first FAT partition')

    paths = [
        # (path, image, partition, path_in_image, for_write)
        (path, None, None, path, for_write)
        if (match := _image_re.match(path)) is None else
        (path, match['image'], int(match['part'] or -1), match['path'], for_write)
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
                FatFileSystem(
                    images[image].partitions[
                        part if part != -1 else
                        first_fat_partition(images[image])
                    ].data
                )
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
        help=lang._("print more output"))
    parser.add_argument(
        '-q', '--quiet', dest='log_level',
        action='store_const', const=logging.CRITICAL,
        help=lang._("print no output"))
    commands = parser.add_subparsers(title=lang._("commands"))

    help_cmd = commands.add_parser(
        'help', description=lang._(do_help.__doc__),
        help=lang._("displays help for the specified command"))
    help_cmd.add_argument(
        'cmd', metavar='command', nargs='?',
        help=lang._("the command to display help for"))
    help_cmd.set_defaults(func=do_help)

    cat_cmd = commands.add_parser(
        'cat', description=lang._(do_cat.__doc__),
        help=lang._("concatenate content into a single output"))
    cat_cmd.add_argument(
        'filenames', nargs='*',
        help=lang._("the input files"))
    cat_cmd.add_argument(
        '-o', '--output', metavar='filename', default='-',
        help=lang._("the output file (default: stdout)"))
    cat_cmd.set_defaults(func=do_cat)

    cp_cmd = commands.add_parser(
        'cp', description=lang._(do_cp.__doc__),
        help=lang._("copy files and directories"))
    cp_cmd.add_argument(
        'filenames', nargs='+',
        help=lang._("the files or directories to copy"))
    cp_cmd.add_argument(
        'dest',
        help=lang._("the directory to copy into or the file to replace"))
    cp_cmd.add_argument(
        '-r', '-R', '--recursive', action='store_true',
        help=lang._("copy directories and their contents recursively"))
    cp_cmd.set_defaults(func=do_cp)

    ls_cmd = commands.add_parser(
        'ls', description=lang._(do_ls.__doc__),
        help=lang._("list directory contents"))
    ls_cmd.add_argument(
        'filenames', nargs='+',
        help=lang._("the files or directories to list"))
    ls_cmd.add_argument(
        '-a', '--all', action='store_true',
        help=lang._("do not ignore entries beginning with ."))
    ls_cmd.add_argument(
        '-l', dest='long', action='store_true',
        help=lang._("show details beside listed entries"))
    ls_cmd.add_argument(
        '--sort', default='name',
        help=lang._("sort on name (the default) / size / time / none"))
    ls_cmd.add_argument(
        '-U', dest='sort', action='store_const', const='none',
        help=lang._("disable sorting"))
    ls_cmd.add_argument(
        '-S', dest='sort', action='store_const', const='size',
        help=lang._("sort by file size"))
    ls_cmd.add_argument(
        '-t', dest='sort', action='store_const', const='time',
        help=lang._("sort by modification time"))
    ls_cmd.add_argument(
        '-X', dest='sort', action='store_const', const='extension',
        help=lang._("sort by entry extension"))
    ls_cmd.set_defaults(func=do_ls)

    mkdir_cmd = commands.add_parser(
        'mkdir', description=lang._(do_mkdir.__doc__),
        help=lang._("make directories"))
    mkdir_cmd.add_argument(
        'filenames', nargs='+',
        help=lang._("the directories to create"))
    mkdir_cmd.add_argument(
        '-p', '--parents', action='store_true',
        help=lang._("create parent directories as required"))
    mkdir_cmd.set_defaults(func=do_mkdir)

    mv_cmd = commands.add_parser(
        'mv', description=lang._(do_mv.__doc__),
        help=lang._("move files and directories"))
    mv_cmd.add_argument(
        'filenames', nargs='+',
        help=lang._("the files or directories to copy"))
    mv_cmd.add_argument(
        'dest',
        help=lang._("the directory to move into or the file to replace"))
    mv_cmd.set_defaults(func=do_mv)

    rm_cmd = commands.add_parser(
        'rm', description=lang._(do_rm.__doc__),
        help=lang._("removes files or directories"))
    rm_cmd.add_argument(
        'filenames', nargs='+',
        help=lang._("the files or directories to remove"))
    rm_cmd.add_argument(
        '-r', '-R', '--recursive', action='store_true',
        help=lang._("remove directories and their contents recursively"))
    rm_cmd.add_argument(
        '-f', '--force', action='store_true',
        help=lang._("do not error on non-existent arguments and never "
                    "prompt"))
    rm_cmd.set_defaults(func=do_rm)

    rmdir_cmd = commands.add_parser(
        'rmdir', description=lang._(do_rmdir.__doc__),
        help=lang._("remove empty directories"))
    rmdir_cmd.add_argument(
        'filenames', nargs='+',
        help=lang._("the directories to remove"))
    rmdir_cmd.set_defaults(func=do_rmdir)

    touch_cmd = commands.add_parser(
        'touch', description=lang._(do_touch.__doc__),
        help=lang._("update file timestamps"))
    touch_cmd.add_argument(
        'filenames', nargs='+',
        help=lang._("the files to create or modify the timestamps of"))
    touch_cmd.set_defaults(func=do_touch)

    return parser


def do_help(config):
    """
    With no arguments, displays a list of %(prog)s commands. If a command name
    is given, displays the description and options for the named command.
    """
    if config.cmd is not None:
        get_parser().parse_args([config.cmd, '-h'])
    else:
        get_parser().parse_args(['-h'])


def do_cat(config):
    """
    Concatenate content from the given files, writing it to stdout by default.
    If - is given as a filename, or if no filenames are specified, stdin is
    read. In order to permit output to a file within an image, -o is provided
    to specify an output other than stdout.
    """
    with get_paths(config.filenames, [config.output], allow_std=True) as paths:
        with paths[config.output].open('wb') as out_f:
            for filename in config.filenames:
                path = paths[filename]
                with path.open('rb') as in_f:
                    copy_bytes(in_f, out_f)


def do_ls(config):
    """
    List information about the files, or the contents of the directories given.
    Entries will be sorted alphabetically, unless another ordering is
    explicitly specified. By default, hidden files (beginning with ".") are
    excluded from the output, unless -a is provided.
    """
    now = dt.datetime.now(tz=dt.timezone.utc)
    key = {
        'none': lambda p: 0,
        'name': lambda p: p.parts,
        'size': lambda p: -p.stat().st_size,
        'extension': lambda p: list(reversed(p.suffixes)),
        'time': lambda p: -p.stat().st_mtime,
    }[config.sort]
    def key_from_value(items):
        k, v = items
        return key(v)

    def print_entry(filename, path):
        # This stat() call may seem pointless for the second case, but ensures
        # we error in the case of attempting to access a non-existent file
        st = path.stat()
        if config.long:
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
                f'{filename}'
            )
        else:
            print(filename)

    with get_paths(config.filenames, []) as paths:
        first_line = True
        for filename, path in sorted(paths.items(), key=key_from_value):
            if not path.is_dir():
                print_entry(filename, path)
                first_line = False
        for filename, path in sorted(paths.items(), key=key_from_value):
            if path.is_dir():
                if not first_line:
                    print()
                first_line = False
                if len(paths) > 1:
                    print(f'{filename}:')
                if config.all:
                    with suppress(FileNotFoundError):
                        print_entry('.', path / '.')
                    with suppress(FileNotFoundError):
                        print_entry('..', path / '..')
                for entry in sorted(path.iterdir(), key=key):
                    if config.all or not entry.name.startswith('.'):
                        print_entry(entry.name, entry)


def do_rm(config):
    """
    Removes the files specified. If -r is given, will recursively remove
    directories and their contents as well.
    """
    def _remove_dir(path):
        for p in path.iterdir():
            if p.is_dir():
                _remove_dir(p)
                p.rmdir()
            else:
                p.unlink()

    with get_paths([], config.filenames) as paths:
        for filename in config.filenames:
            path = paths[filename]
            if config.recursive and path.is_dir():
                _remove_dir(path)
                path.rmdir()
            else:
                try:
                    path.unlink()
                except FileNotFoundError:
                    if not config.force:
                        raise


def do_rmdir(config):
    """
    Removes the directories specified, which must be empty.
    """
    with get_paths([], config.filenames) as paths:
        for filename in config.filenames:
            path = paths[filename]
            path.rmdir()


def do_mkdir(config):
    """
    Creates the directories specified, which must not exist either as
    directories or regular files.
    """
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
    """
    Update last modified timestamps, creating any files that do not already
    exist.
    """
    with get_paths([], config.filenames) as paths:
        for filename in config.filenames:
            path = paths[filename]
            path.touch()


def do_cp(config):
    """
    Copy the specified file over the target file, if only one source is given,
    or copy the specified files and directories into the target directory, if
    the target is a directory.
    """
    def _copy(source, dest):
        if source.is_dir():
            if config.recursive:
                dest.mkdir(exist_ok=True)
                for item in source.iterdir():
                    _copy(item, dest / item.name)
            elif any(source.iterdir()):
                raise IsADirectoryError(lang._(
                    '-r not specified; {filename} is a non-empty directory'
                ).format(filename=filename))
            else:
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
            raise NotADirectoryError(lang._(
                '{config.dest} is not a directory').format(config=config))
        else:
            _copy(paths[config.filenames[0]], paths[config.dest])


def do_mv(config):
    """
    Move the specified file over the target file, if only one source is given,
    or move the specified files and directories into the target directory, if
    the target is a directory.
    """
    def _move(source, dest):
        if same_fs(source, dest):
            source.rename(dest)
        elif source.is_dir():
            dest.mkdir(exist_ok=True)
            for item in source.iterdir():
                _move(item, dest / item.name)
            source.rmdir()
        else:
            with source.open('rb') as in_f:
                with dest.open('wb') as out_f:
                    copy_bytes(in_f, out_f)
            source.unlink()

    with get_paths([], config.filenames + [config.dest]) as paths:
        if paths[config.dest].is_dir():
            dest_root = paths[config.dest]
            for filename in config.filenames:
                source = paths[filename]
                _move(source, dest_root / source.name)
        elif len(config.filenames) > 1:
            raise NotADirectoryError(lang._(
                '{config.dest} is not a directory').format(config=config))
        else:
            for filename in config.filenames:
                _move(paths[filename], paths[config.dest])


def same_fs(path1, path2):
    """
    Test whether *path1* and *path2* (both either :class:`~pathlib.Path` or
    :class:`~nobodd.path.FatPath` instances) are part of the same file-system.

    Note that this does *not* mean part of the same mount in the Linux
    file-system. This returns :data:`True` if both paths are
    :class:`~pathlib.Path` instances, or if both paths are
    :class:`~nobodd.path.FatPath` instances and both belong to the same
    :class:`~nobodd.fs.FatFileSystem` instance.
    """
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
