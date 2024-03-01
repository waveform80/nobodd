# nobodd: a boot configuration tool for the Raspberry Pi
#
# Copyright (c) 2024 Dave Jones <dave.jones@canonical.com>
# Copyright (c) 2024 Canonical Ltd.
#
# SPDX-License-Identifier: GPL-3.0

import datetime as dt
from pathlib import Path
from ipaddress import ip_address
from configparser import ConfigParser

import pytest

from nobodd.config import *


@pytest.fixture()
def parser(tmp_path):
    default_conf = tmp_path / 'default.conf'
    default_conf.write_text("""\
[foos]
foo = 0
path = /tmp

[bars]
bar = 3.141
frob = no
path = /tmp
""")
    parser = ConfigArgumentParser(template=default_conf)
    parser.add_argument('--version', action='version', version='0.1')
    top = parser.add_argument('--top', type=str)
    foos = parser.add_argument_group('foos', section='foos')
    foos.add_argument('--foo', key='foo', type=int)
    foos.add_argument('--foo-path', key='path', type=Path)
    bars = parser.add_argument_group('bars', section='bars')
    bars.add_argument('--bar', key='bar', type=float)
    bars.add_argument('--frob', key='frob', action='store_true')
    bars.add_argument('--no-frob', dest='frob', key='frob', action='store_false')
    bars.add_argument('--bar-path', key='path', type=Path)

    return parser


def test_port():
    assert port('5000') == 5000
    assert port('tftp') == 69
    with pytest.raises(ValueError):
        port('supercalifragilisticexpialidocious')


def test_boolean():
    assert boolean('y') is True
    assert boolean('0') is False
    with pytest.raises(ValueError):
        boolean('mu')


def test_size():
    assert size('0') == 0
    assert size('200B') == 200
    assert size('1KB') == 1024
    assert size('2.2GB') == int(2.2 * 2**30)
    with pytest.raises(ValueError):
        size('fooB')


def test_duration():
    assert duration('0s') == dt.timedelta(seconds=0)
    assert duration('1h') == dt.timedelta(hours=1)
    assert duration('5m 30s') == dt.timedelta(minutes=5, seconds=30)
    with pytest.raises(ValueError):
        duration('2 hours later...')


def test_serial():
    assert serial('1234abcd') == 0x1234abcd
    assert serial('  deadbeef ') == 0xdeadbeef
    assert serial('100000001234abcd') == 0x1234abcd
    with pytest.raises(ValueError):
        assert serial('foo')
    with pytest.raises(ValueError):
        assert serial('ffffffffff')


def test_board_from_string():
    assert Board.from_string('1234abcd,ubuntu.img') == (
        0x1234abcd, Path('ubuntu.img'), 1, None)
    assert Board.from_string('100000001234abcd,ubuntu.img,2') == (
        0x1234abcd, Path('ubuntu.img'), 2, None)
    assert Board.from_string('1234abcd,ubuntu.img,2,192.168.0.5') == (
        0x1234abcd, Path('ubuntu.img'), 2, ip_address('192.168.0.5'))
    with pytest.raises(ValueError):
        Board.from_string('a,b,c,d,e')
    with pytest.raises(ValueError):
        Board.from_string('1234abcd,ubuntu.img,foo')


def test_board_from_section():
    assert Board.from_section({
        'board:1234abcd': {
            'image': '/srv/images/ubuntu-22.04.img',
            'partition': '1',
            'ip': '192.168.0.5',
        }
    }, 'board:1234abcd') == (
        0x1234abcd, Path('/srv/images/ubuntu-22.04.img'), 1,
        ip_address('192.168.0.5'))
    assert Board.from_section({
        'board:100000001234abcd': {
            'image': '/srv/images/ubuntu-22.04.img',
        }
    }, 'board:100000001234abcd') == (
        0x1234abcd, Path('/srv/images/ubuntu-22.04.img'), 1, None)
    with pytest.raises(ValueError):
        Board.from_section({}, 'foo')
    with pytest.raises(ValueError):
        Board.from_section({
            'board:100000001234abcd': {
                'image': '/srv/images/ubuntu-22.04.img',
                'partition': 'foo',
            }
        }, 'board:100000001234abcd')


def test_configargparse_basics(parser):
    config = ConfigParser(interpolation=None)
    config.read_dict({
        'foos': {'foo': '10'},
        'bars': {'bar': '10.1', 'frob': 'yes'}
    })
    parser.set_defaults_from(config)

    ns = parser.parse_args([])
    assert ns.top is None
    assert ns.foo == 10
    assert ns.bar == 10.1
    assert ns.frob is True

    ns = parser.parse_args(['--no-frob', '--bar', '3.141'])
    assert ns.top is None
    assert ns.foo == 10
    assert ns.bar == 3.141
    assert ns.frob is False


def test_configargparse_bad_init():
    parser = ConfigArgumentParser()
    with pytest.raises(ValueError):
        parser.add_argument('--top', type=str, section='foo')
    with pytest.raises(ValueError):
        frobs = parser.add_argument_group('frobs', section='frobs')
        frobs.add_argument('--frob', key='frob', action='store_true')
        frobs.add_argument('--no-frob', dest='frob', key='no-frob',
                            action='store_false')


def test_configargparse_update_config(parser):
    config = ConfigParser(interpolation=None)
    config.read_dict({
        'foos': {'foo': '10'},
        'bars': {'bar': '10.1', 'frob': 'yes'}
    })
    parser.set_defaults_from(config)

    ns = parser.parse_args(['--no-frob', '--bar', '3.141'])
    parser.update_config(config, ns)
    assert config['foos']['foo'] == '10'
    assert config['bars']['bar'] == '3.141'
    assert config['bars']['frob'] == 'False'


def test_configargparse_of_type(parser):
    assert parser.of_type(int) == {('foos', 'foo')}
    assert parser.of_type(boolean) == {('bars', 'frob')}


def test_configargparse_read_configs(parser, tmp_path):
    user_conf = tmp_path / 'user.conf'
    user_conf.write_text("""\
[foos]
foo = 10

[bars]
bar = 6.282
frob = no
""")
    config = parser.read_configs([user_conf])
    assert config['foos']['foo'] == '10'
    assert config['bars']['bar'] == '6.282'
    assert config['bars']['frob'] == 'no'
    parser.set_defaults_from(config)
    assert parser.get_default('foo') == '10'
    assert parser.get_default('bar') == '6.282'


def test_configargparse_bad_configs(parser, tmp_path):
    # Bad section title
    bad_conf1 = tmp_path / 'bad1.conf'
    bad_conf1.write_text("""\
[bazs]
foo = 10
""")
    with pytest.raises(ValueError):
        parser.read_configs([bad_conf1])

    # Good section, good key, but in wrong section
    bad_conf2 = tmp_path / 'bad1.conf'
    bad_conf2.write_text("""\
[foos]
bar = 10
""")
    with pytest.raises(ValueError):
        parser.read_configs([bad_conf2])


def test_configargparse_resolves_paths(parser, tmp_path):
    user_conf = tmp_path / 'user.conf'
    user_conf.write_text("""\
[foos]
foo = 10
path = somefile
""")
    config = parser.read_configs([user_conf])
    assert config['foos']['path'] == str(tmp_path / 'somefile')


def test_configargparse_no_template(tmp_path):
    parser = ConfigArgumentParser()
    parser.add_argument('--version', action='version', version='0.1')
    top = parser.add_argument('--top', type=str)
    foos = parser.add_argument_group('foos', section='foos')
    foos.add_argument('--foo', key='foo', type=int)
    bars = parser.add_argument_group('bars', section='bars')
    bars.add_argument('--bar', key='bar', type=float)
    bars.add_argument('--frob', key='frob', action='store_true')
    bars.add_argument('--no-frob', dest='frob', key='frob', action='store_false')

    user_conf = tmp_path / 'user.conf'
    user_conf.write_text("""\
[foos]
foo = 10

[bars]
bar = 6.282
frob = no
""")
    # Doesn't complain about validity of sections despite there being no
    # template
    config = parser.read_configs([user_conf])
    assert config['foos']['foo'] == '10'
    assert config['bars']['bar'] == '6.282'
    assert config['bars']['frob'] == 'no'
