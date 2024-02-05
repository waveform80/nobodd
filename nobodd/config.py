import os
import re
import socket
import datetime as dt
from pathlib import Path
from decimal import Decimal
from contextlib import suppress
from fnmatch import fnmatchcase
from collections import namedtuple
from configparser import ConfigParser
from argparse import ArgumentParser, SUPPRESS
from ipaddress import ip_address
from copy import deepcopy


# The locations to attempt to read the configuration from
XDG_CONFIG_HOME = Path(os.environ.get('XDG_CONFIG_HOME', '~/.config'))
CONFIG_LOCATIONS = (
    Path('/etc/nobodd/config'),
    Path('/usr/local/etc/nobodd/config'),
    Path(XDG_CONFIG_HOME / 'nobodd.conf'),
    Path('~/.nobodd.conf'),
)


class ConfigArgumentParser(ArgumentParser):
    """
    A variant of :class:`~argparse.ArgumentParser` that links arguments to
    specified keys in a :class:`~configparser.ConfigParser` instance.

    Typical usage is to construct an instance of :class:`ConfigArgumentParser`,
    define the parameters and parameter groups on it, associating them with
    configuration section and key names as appropriate, then call
    :meth:`read_configs` to parse a set of configuration files. These will be
    checked against the (optional) *template* configuration passed to the
    initializer, which defines the set of valid sections and keys expected.

    The resulting :class:`~configparser.ConfigParser` forms the "base"
    configuration, prior to argument parsing. This can be optionally
    manipulated, before passing it to :meth:`set_defaults_from` to set the
    argument defaults. At this point,
    :meth:`~argparse.ArgumentParser.parse_args` may be called to parse the
    command line arguments, knowing that defaults in the help will be drawn
    from the "base" configuration.

    The resulting :class:`~argparse.Namespace` object is the application's
    runtime configuration. For example::

        >>> from pathlib import Path
        >>> from nobodd.config import *
        >>> parser = ConfigArgumentParser()
        >>> tftp = parser.add_argument_group('tftp', section='tftp')
        >>> tftp.add_argument('--listen', type=str, key='listen',
        ... help="the address on which to listen for connections "
        ... "(default: %(default)s)")
        >>> Path('defaults.conf').write_text('''
        ... [tftp]
        ... listen = 127.0.0.1
        ... ''')
        >>> defaults = parser.read_configs(['defaults.conf'])
        >>> parser.set_defaults_from(defaults)
        >>> parser.get_default('listen')
        '127.0.0.1'
        >>> config = parser.parse_args(['--listen', '0.0.0.0'])
        >>> config.listen
        '0.0.0.0'

    Note that, after the call to :meth:`set_defaults_from`, the parser's idea
    of the defaults has been drawn from the file-based configuration (and thus
    will be reflected in printed ``--help``), but this is still overridden by
    the arguments passed to the command line.
    """
    def __init__(self, *args, template=None, **kwargs):
        super().__init__(*args, **kwargs)
        if template is not None:
            self._template = self._get_config_parser()
            self._template.read(template)
        else:
            self._template = None
        self._config_map = {}

    def _get_config_parser(self):
        """
        Generate and return a new :class:`~configparser.ConfigParser` with
        appropriate configuration (interpolation, delimiters, etc.) for the
        desired parsing behaviour.
        """
        return ConfigParser(
            delimiters=('=',), empty_lines_in_values=False,
            interpolation=None, strict=False)

    def add_argument(self, *args, section=None, key=None, **kwargs):
        """
        Adds *section* and *key* parameters. These link the new argument to the
        specified configuration entry.

        The default for the argument can be specified directly as usual, or can
        be read from the configuration (see :meth:`read_configs` and
        :meth:`set_defaults_from`). When arguments are parsed, the value
        assigned to this argument will be copied to the associated
        configuration entry.
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

    def read_configs(self, paths):
        """
        Constructs a :class:`~configparser.ConfigParser` instance, and reads
        the configuration files specified by *paths*, a list of
        :class:`~pathlib.Path`-like objects, into it.

        The method will check the configuration for valid section and key
        names, raising :exc:`ValueError` on invalid items. It will also resolve
        any configuration values that have the type :class:`~pathlib.Path`
        relative to the path of the configuration file in which they were
        defined.

        The return value is the configuration parser instance.
        """
        # NOTE: We cheat in several places here to deal with the board:*
        # sections in the default.conf. If you use this class elsewhere, adjust
        # these accordingly
        if self._template is None:
            config = self._get_config_parser()
        else:
            config = deepcopy(self._template)
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
        # special handling when loading configuration files as the values will
        # be resolved relative to the containing configuration file
        path_items = self.of_type(Path)
        path_items |= {('board:*', 'image')}

        # Attempt to load each of the specified locations; these are done
        # strictly in order to permit the customary hierarchy of configuration
        # files (/lib, /etc, ~) to override each other
        to_read = [Path(p) for p in paths]
        while to_read:
            path = to_read.pop(0).expanduser()
            config.read(path)
            # If a template was provided upon construction, validate sections
            # and keys against those in the template
            if self._template is not None:
                for section, keys in config.items():
                    try:
                        section = {
                            s for s in valid if fnmatchcase(section, s)}.pop()
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
        Copy values from *namespace* (an :class:`argparse.Namespace`,
        presumably the result of calling something like
        :meth:`~argparse.ArgumentParser.parse_args`) to *config*, a
        :class:`~configparser.ConfigParser`. Note that namespace values will be
        converted to :class:`str` implicitly.
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


def size(s):
    """
    Convert the string *s*, which must contain a number followed by an optional
    suffix (MB for mega-bytes, GB, for giga-bytes, etc.), and return the
    absolute integer value (scale the number in the string by the suffix
    given).
    """
    for power, suffix in enumerate(['KB', 'MB', 'GB', 'TB'], start=1):
        if s.endswith(suffix):
            n = Decimal(s[:-len(suffix)])
            result = int(n * 2 ** (10 * power))
            break
    else:
        if s.endswith('B'):
            result = int(s[:-1])
        else:
            # No recognized suffix; attempt straight conversion
            result = int(s)
    return result


class Board(namedtuple('Board', ('serial', 'image', 'partition', 'ip'))):
    """
    Represents a known board, recording its *serial* number, the *image*
    (filename) that the board should boot, the *partition* number within the
    *image* that contains the boot partition, and the IP address (if any) that
    the board should have.
    """

    @classmethod
    def from_section(cls, config, section):
        """
        Construct a new :class:`Board` from the specified *section* of the
        *config* (a mapping, e.g. a :class:`~configparser.ConfigParser`
        section).
        """
        assert section.startswith('board:')
        values = config[section]
        serial = int(section[len('board:'):], base=16)
        image = values['image']
        part = int(values.get('partition', 1))
        try:
            ip = ip_address(values['ip'])
        except KeyError:
            ip = None
        return cls(serial, Path(image), part, ip)

    @classmethod
    def from_string(cls, s):
        """
        Construct a new :class:`Board` from the string *s* which is expected to
        be a comma-separated list of serial number, filename, partition number,
        and IP address. The last two parts (partition number and IP address)
        are optional and default to 1 and :data:`None` respectively.
        """
        serial, image, *extra = s.split(',')
        serial = int(serial, base=16)
        ip = part = None
        if len(extra) > 2:
            raise ValueError(
                f'expected serial,filename,[part],[ip] instead of {s}')
        elif len(extra) > 1:
            part = extra[0]
            ip = extra[1]
        elif len(extra) > 0:
            part = extra[0]
        if part:
            try:
                part = int(part)
            except ValueError:
                raise ValueError(f'invalid partition number {part!r}')
        else:
            part = 1
        if ip is not None:
            ip = ip_address(ip)
        return cls(serial, Path(image), part, ip)


_SPANS = {
    span: re.compile(fr'(?:(?P<num>[+-]?\d+)\s*{suffix}\b)')
    for span, suffix in [
        ('microseconds', '(micro|u|µ)s(ec(ond)?s?)?'),
        ('milliseconds', '(milli|m)s(ec(ond)?s?)?'),
        ('seconds',      's(ec(ond)?s?)?'),
        ('minutes',      'm(i(n(ute)?s?)?)?'),
        ('hours',        'h((ou)?rs?)?'),
    ]
}
def duration(s):
    """
    Convert the string *s* to a :class:`~datetime.timedelta`. The string must
    consist of white-space and/or comma separated values which are a number
    followed by a suffix indicating duration. For example:

        >>> duration('1s')
        timedelta(seconds=1)
        >>> duration('5 minutes, 30 seconds')
        timedelta(seconds=330)

    The set of possible durations, and their recognized suffixes is as follows:

    * *Microseconds*: microseconds, microsecond, microsec, micros, micro,
      useconds, usecond, usecs, usec, us, µseconds, µsecond, µsecs, µsec, µs

    * *Milliseconds*: milliseconds, millisecond, millisec, millis, milli,
      mseconds, msecond, msecs, msec, ms

    * *Seconds*: seconds, second, secs, sec, s

    * *Minutes*: minutes, minute, mins, min, mi, m

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
    return dt.timedelta(**spans)
