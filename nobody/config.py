import os
import re
import socket
from pathlib import Path
from contextlib import suppress
from fnmatch import fnmatchcase
from collections import namedtuple
from configparser import ConfigParser
from argparse import ArgumentParser, SUPPRESS

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


# The locations to attempt to read the configuration from
XDG_CONFIG_HOME = Path(os.environ.get('XDG_CONFIG_HOME', '~/.config'))
CONFIG_LOCATIONS = (
    Path('/etc/nobody.conf'),
    Path('/usr/local/etc/nobody.conf'),
    Path(XDG_CONFIG_HOME / 'nobody.conf'),
    Path('~/.nobody.conf'),
)


class ConfigArgumentParser(ArgumentParser):
    """
    A variant of :class:`~argparse.ArgumentParser` that links arguments to
    specified keys in a :class:`~configparser.ConfigParser` instance.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._config_map = {}

    def add_argument(self, *args, section=None, key=None, **kwargs):
        """
        Adds *section* and *key* parameters. These link the new argument to the
        specified configuration entry.

        The default for the argument can be specified directly as usual, or
        can be read from the configuration (see :meth:`set_defaults`). When
        arguments are parsed, the value assigned to this argument will be
        copied to the associated configuration entry.
        """
        return self._add_config_action(
            *args, method=super().add_argument, section=section, key=key,
            **kwargs)

    def add_argument_group(self, title=None, description=None, section=None):
        """
        Adds a new argument group object and returns it.

        The new argument group will likewise accept *section* and *key*
        parameters on its :meth:`add_argument` method. The *section* parameter
        will default to the value of the *section* parameter passed to this
        method (but may be explicitly overridden).
        """
        group = super().add_argument_group(title=title, description=description)
        def add_argument(*args, section=section, key=None,
                         _add_arg=group.add_argument, **kwargs):
            return self._add_config_action(
                *args, method=_add_arg, section=section, key=key, **kwargs)
        group.add_argument = add_argument
        return group

    def _add_config_action(self, *args, method, section, key, **kwargs):
        assert callable(method), 'method must be a callable'
        if (section is None) != (key is None):
            raise ValueError('section and key must be specified together')
        try:
            if kwargs['action'] in ('store_true', 'store_false'):
                type = boolean
        except KeyError:
            type = kwargs.get('type', str)
        action = method(*args, **kwargs)
        if key is not None:
            with suppress(KeyError):
                if self._config_map[action.dest] != (section, key, type):
                    raise ValueError(
                        'section and key must match for all equivalent dest '
                        'values')
            self._config_map[action.dest] = (section, key, type)
        return action

    def set_defaults_from(self, config):
        """
        Sets defaults for all arguments from their associated configuration
        entries in *config*.
        """
        kwargs = {
            dest:
                config.getboolean(section, key)
                if type is boolean else
                config[section][key]
            for dest, (section, key, type) in self._config_map.items()
            if section in config
            and key in config[section]
        }
        return super().set_defaults(**kwargs)

    def update_config(self, config, namespace):
        """
        Copy values from *namespace* (presumably the result of calling
        something like :meth:`~argparse.ArgumentParser.parse_args`) to
        *config*. Note that namespace values will be converted to :class:`str`
        implicitly.
        """
        for dest, (section, key, type) in self._config_map.items():
            config[section][key] = str(getattr(namespace, dest))

    def of_type(self, type):
        """
        Return a set of (section, key) tuples listing all configuration items
        which were defined as being of the specified *type* (with the *type*
        keyword passed to :meth:`add_argument`.
        """
        return {
            (section, key)
            for section, key, item_type in self._config_map.values()
            if item_type is type
        }


def port(s):
    """
    Convert the string *s* into a port number. The string may either contain
    an integer representation (in which case the conversion is trivial, or
    a port name, in which case ``getservbyname`` will be used to convert it
    to a port number (usually via NSS).
    """
    try:
        return int(s)
    except ValueError:
        try:
            return socket.getservbyname(s)
        except OSError:
            raise ValueError('invalid service name or port number')


def boolean(s):
    """
    Convert the string *s* to a :class:`bool`. A typical set of case
    insensitive strings are accepted: "yes", "y", "true", "t", and "1" are
    converted to :data:`True`, while "no", "n", "false", "f", and "0" convert
    to :data:`False`. Other values will result in :exc:`ValueError`.
    """
    try:
        return {
            'n':     False,
            'no':    False,
            'f':     False,
            'false': False,
            '0':     False,
            'y':     True,
            'yes':   True,
            't':     True,
            'true':  True,
            '1':     True,
        }[str(s).strip().lower()]
    except KeyError:
        raise ValueError(f'invalid boolean value: {s}')


def mac_address(s):
    try:
        return tuple(int(p, base=16) for p in s.split(':', 5))
    except ValueError:
        raise ValueError(f'invalid MAC address {s!r}')


class Board(namedtuple('Board', ('serial', 'image', 'partition', 'mac'))):
    @classmethod
    def from_section(cls, config, section):
        assert section.startswith('board:')
        values = config[section]
        serial = int(section[len('board:'):], base=16)
        image = values['image']
        part = int(values.get('partition', 1))
        try:
            mac = mac_address(values['mac'])
        except KeyError:
            mac = None
        return cls(serial, Path(image), part, mac)

    @classmethod
    def from_string(cls, s):
        serial, image, *extra = s.split(',')
        serial = int(serial, base=16)
        mac = part = None
        if len(extra) > 2:
            raise ValueError(
                f'expected serial,filename,[part],[mac] instead of {s}')
        elif len(extra) > 1:
            part = extra[0]
            mac = extra[1]
        elif len(extra) > 0:
            part = extra[0]
        if part:
            try:
                part = int(part)
            except ValueError:
                raise Value(f'invalid partition number {part!r}')
        else:
            part = 1
        if mac is not None:
            mac = mac_address(mac)
        return cls(serial, Path(image), part, mac)


_SPANS = {
    span: re.compile(fr'(?:(?P<num>[+-]?\d+)\s*{suffix}\b)')
    for span, suffix in [
        ('microseconds', '(micro|u|µ)s(ec(ond)?s?)?'),
        ('milliseconds', '(milli|m)s(ec(ond)?s?)?'),
        ('seconds',      's(ec(ond)?s?)?'),
        ('minutes',      'mi(n(ute)?s?)?'),
        ('hours',        'h((ou)?rs?)?'),
    ]
}
def duration(s):
    """
    Convert the string *s* to a :class:`~datetime.timedelta`. The string must
    consist of white-space and/or comma separated values which are a number
    followed by a suffix indicating duration. For example:

        >>> parse_duration('1s')
        timedelta(seconds=1)
        >>> parse_duration('5 minutes, 30 seconds')
        timedelta(seconds=330)

    The set of possible durations, and their recognized suffixes is as follows:

    * *Microseconds*: microseconds, microsecond, microsec, micros, micro,
      useconds, usecond, usecs, usec, us, µseconds, µsecond, µsecs, µsec, µs

    * *Milliseconds*: milliseconds, millisecond, millisec, millis, milli,
      mseconds, msecond, msecs, msec, ms

    * *Seconds*: seconds, second, secs, sec, s

    * *Minutes*: minutes, minute, mins, min, mi

    * *Hours*: hours, hour, hrs, hr, h

    If conversion fails, :exc:`ValueError` is raised.
    """
    spans = {}
    t = s
    for span, regex in _SPANS.items():
        m = regex.search(t)
        if m:
            spans[span] = spans.get(span, 0) + int(m.group('num'))
            t = (t[:m.start(0)] + t[m.end(0):]).strip(' \t\n,')
            if not t:
                break
    if t:
        raise ValueError(f'invalid duration {s}')
    return timedelta(**spans)


def get_parser(config, **kwargs):
    parser = ConfigArgumentParser(**kwargs)
    parser.add_argument(
        '--version', action='version', version=version('nobody'))

    tftp_section = parser.add_argument_group('tftp', section='tftp')
    tftp_section.add_argument(
        '--listen',
        key='listen', type=str, metavar='ADDR',
        help="the address on which to listen for connections "
        "(default: %(default)s)")
    tftp_section.add_argument(
        '--port',
        key='port', type=port, metavar='PORT',
        help="the port on which to listen for connections "
        "(default: %(default)s)")

    parser.add_argument(
        '--board', dest='boards', type=Board.from_string, action='append',
        metavar='SERIAL,FILENAME[,PART[,MAC]]', default=[
            Board.from_section(config[section])
            for section in config
            if section.startswith('board:')
        ],
        help="can be specified multiple times to define boards which are to "
        "be served boot images over TFTP; if PART is omitted the default is "
        "1; if MAC is omitted the MAC address will not be checked")

    return parser


def get_config():
    config = ConfigParser(
        delimiters=('=',), empty_lines_in_values=False, interpolation=None,
        strict=False)
    with resources.path('nobody', 'default.conf') as default_conf:
        config.read(default_conf)
    valid = {config.default_section: set()}
    for section, keys in config.items():
        for key in keys:
            valid.setdefault(
                'board:*' if section.startswith('board:') else section,
                set()
            ).add(key)
    for section in {s for s in config if s.startswith('board:')}:
        del config[section]

    # Figure out which configuration items represent paths. These will need
    # special handling when loading configuration files as the values will be
    # resolved relative to the containing configuration file
    path_items = get_parser(config).of_type(Path) | {('board:*', 'image')}

    # Attempt to load each of the pre-defined locations for the "main"
    # configuration, validating sections and keys against the default template
    # loaded above
    for path in CONFIG_LOCATIONS:
        path = path.expanduser()
        config.read(path)
        for section, keys in config.items():
            try:
                section = {s for s in valid if fnmatchcase(section, s)}.pop()
            except KeyError:
                raise ValueError(
                    f'{path}: invalid section [{section}]')
            for key in set(keys) - valid[section]:
                raise ValueError(
                    f'{path}: invalid key {key} in [{section}]')
        # Resolve paths relative to the configuration file just loaded
        for glob, key in path_items:
            for section in {s for s in config if fnmatchcase(s, glob)}:
                if key in config[section]:
                    value = Path(config[section][key]).expanduser()
                    if not value.is_absolute():
                        value = (path.parent / value).resolve()
                    config[section][key] = str(value)
    return config
