# nobodd: a boot configuration tool for the Raspberry Pi
#
# Copyright (c) 2024 Dave Jones <dave.jones@canonical.com>
# Copyright (c) 2024 Canonical Ltd.
#
# SPDX-License-Identifier: GPL-3.0

import os
import sys
import socket
from time import time, sleep
from threading import Thread
from unittest import mock

import pytest

from nobodd import disk, fs, tftp
from nobodd.server import *


@pytest.fixture()
def main_thread():
    class MainThread(Thread):
        def __init__(self):
            super().__init__()
            self.exit_code = None
            self.exception = None
            self.argv = []
            self.address = None

        def run(self):
            class MyBootServer(BootServer):
                def __init__(slf, server_address, boards):
                    super().__init__(server_address, boards)
                    if self.address is None:
                        self.address = slf.server_address

            try:
                with mock.patch('nobodd.server.BootServer', MyBootServer):
                    self.exit_code = main(self.argv)
            except Exception as e:
                self.exception = e

        def wait_for_ready(self, capsys):
            start = time()
            while time() - start < 10:
                capture = capsys.readouterr()
                if 'Ready' in capture.err:
                    return
                self.join(0.1)
                if not self.is_alive():
                    assert False, 'service died before becoming ready'
            assert False, 'service did not become ready'

        def __enter__(self):
            self.start()

        def __exit__(self, *exc):
            self.join(timeout=1)
            if self.is_alive():
                exit_write.send(b'TERM')
            self.join(timeout=1)

    thread = MainThread()
    yield thread
    thread.join(timeout=10)
    assert not thread.is_alive()


def test_help(capsys):
    with pytest.raises(SystemExit) as err:
        main(['--version'])
    assert err.value.code == 0
    capture = capsys.readouterr()
    assert capture.out.strip() == '0.3'

    with pytest.raises(SystemExit) as err:
        main(['--help'])
    assert err.value.code == 0
    capture = capsys.readouterr()
    assert capture.out.startswith('usage:')


def test_ctrl_c(main_thread, capsys):
    main_thread.argv = [
        '--listen', '127.0.0.1', '--port', '0',
        '--board', f'1234abcd,foo.img',
    ]
    with main_thread:
        os.kill(os.getpid(), signal.SIGINT)
    capture = capsys.readouterr()
    assert capture.err.strip().endswith('Interrupted')
    assert main_thread.exception is None
    assert main_thread.exit_code == 2


def test_sigterm(main_thread, capsys):
    main_thread.argv = [
        '--listen', '127.0.0.1', '--port', '0',
        '--board', f'1234abcd,foo.img',
    ]
    with main_thread:
        os.kill(os.getpid(), signal.SIGTERM)
    capture = capsys.readouterr()
    assert capture.err.strip().endswith('Terminated')
    assert main_thread.exception is None
    assert main_thread.exit_code == 0


def test_sighup(main_thread, capsys):
    main_thread.argv = [
        '--listen', '127.0.0.1', '--port', '0',
        '--board', f'1234abcd,foo.img',
    ]
    with main_thread:
        os.kill(os.getpid(), signal.SIGHUP)
        os.kill(os.getpid(), signal.SIGTERM)
    capture = capsys.readouterr()
    assert 'Reloading configuration' in capture.err.strip()
    assert capture.err.strip().endswith('Terminated')
    assert main_thread.exception is None
    assert main_thread.exit_code == 0


def test_error_exit_no_debug(main_thread, capsys, monkeypatch):
    with \
        mock.patch('nobodd.server.get_parser') as get_parser, \
        monkeypatch.context() as m:

        m.delenv('DEBUG', raising=False)
        get_parser.side_effect = RuntimeError('trouble is bad')

        main_thread.argv = ['--listen', '127.0.0.1', '--port', '0']
        with main_thread:
            pass
        capture = capsys.readouterr()
        assert 'trouble is bad' in capture.err
        assert main_thread.exception is None
        assert main_thread.exit_code == 1


def test_error_exit_with_debug(main_thread, monkeypatch):
    with \
        mock.patch('nobodd.server.get_parser') as get_parser, \
        monkeypatch.context() as m:

        m.setenv('DEBUG', '1')
        get_parser.side_effect = RuntimeError('trouble is bad')

        main_thread.argv = ['--listen', '127.0.0.1', '--port', '0']
        with main_thread:
            pass
        assert isinstance(main_thread.exception, RuntimeError)


def test_error_exit_with_pdb(main_thread, capsys, monkeypatch):
    with \
        mock.patch('nobodd.server.get_parser') as get_parser, \
        mock.patch('pdb.post_mortem') as post_mortem, \
        monkeypatch.context() as m:

        m.setenv('DEBUG', '2')
        get_parser.side_effect = RuntimeError('trouble is bad')

        main_thread.argv = ['--listen', '127.0.0.1', '--port', '0']
        with main_thread:
            pass
        assert post_mortem.called


def test_regular_operation(fat16_disk, main_thread, capsys, monkeypatch):
    with \
        disk.DiskImage(fat16_disk) as img, \
        fs.FatFileSystem(img.partitions[1].data) as boot:

        expected = (boot.root / 'random').read_bytes()

    with monkeypatch.context() as m:
        m.delenv('DEBUG', raising=False)
        main_thread.argv = [
            '--listen', '127.0.0.1', '--port', '0',
            '--board', f'1234abcd,{fat16_disk}',
        ]
        with main_thread:
            main_thread.wait_for_ready(capsys)

            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                # Start a valid transfer from client...
                client.settimeout(10)
                client.sendto(
                    bytes(tftp.RRQPacket('1234abcd/random', 'octet')),
                    main_thread.address)
                received = []
                for block, offset in enumerate(range(0, len(expected), 512), start=1):
                    buf, addr = client.recvfrom(1500)
                    pkt = tftp.Packet.from_bytes(buf)
                    assert isinstance(pkt, tftp.DATAPacket)
                    assert pkt.block == block
                    received.append(pkt.data)
                    client.sendto(bytes(tftp.ACKPacket(pkt.block)), addr)
                # Because random is a precise multiple of the block size, there
                # should be one final (empty) DATA packet
                buf, addr = client.recvfrom(1500)
                pkt = tftp.Packet.from_bytes(buf)
                assert isinstance(pkt, tftp.DATAPacket)
                assert pkt.block == block + 1
                assert pkt.data == b''
                client.sendto(bytes(tftp.ACKPacket(pkt.block)), addr)
            assert b''.join(received) == expected


def test_bad_fd_type_stdin(main_thread, capsys, tmp_path, monkeypatch):
    with (tmp_path / 'foo').open('wb') as f:
        with mock.patch('nobodd.server.sys.stdin', f), monkeypatch.context() as m:
            m.delenv('DEBUG', raising=False)
            main_thread.argv = [
                '--listen', 'stdin',
                '--board', '1234abcd,foo.img',
            ]
            with main_thread:
                pass
            capture = capsys.readouterr()
            assert f'inherited fd {f.fileno()} is not a socket' in capture.err
            assert main_thread.exit_code == 1


def test_listen_stdin(fat16_disk, main_thread, capsys, monkeypatch):
    with \
        disk.DiskImage(fat16_disk) as img, \
        fs.FatFileSystem(img.partitions[1].data) as boot:

        expected = (boot.root / 'random').read_bytes()

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(('127.0.0.1', 0))
        with monkeypatch.context() as m, \
                mock.patch('nobodd.server.sys.stdin', sock.dup()):
            m.delenv('DEBUG', raising=False)
            main_thread.argv = [
                '--listen', 'stdin',
                '--board', f'1234abcd,{fat16_disk}',
            ]
            main_thread.address = sock.getsockname()
            with main_thread:
                main_thread.wait_for_ready(capsys)

                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                    # Start a valid transfer from client...
                    client.settimeout(10)
                    client.sendto(
                        bytes(tftp.RRQPacket('1234abcd/random', 'octet')),
                        main_thread.address)
                    received = []
                    for block, offset in enumerate(
                        range(0, len(expected), 512), start=1
                    ):
                        buf, addr = client.recvfrom(1500)
                        pkt = tftp.Packet.from_bytes(buf)
                        assert isinstance(pkt, tftp.DATAPacket)
                        assert pkt.block == block
                        received.append(pkt.data)
                        client.sendto(bytes(tftp.ACKPacket(pkt.block)), addr)
                    # Because random is a precise multiple of the block size,
                    # there should be one final (empty) DATA packet
                    buf, addr = client.recvfrom(1500)
                    pkt = tftp.Packet.from_bytes(buf)
                    assert isinstance(pkt, tftp.DATAPacket)
                    assert pkt.block == block + 1
                    assert pkt.data == b''
                    client.sendto(bytes(tftp.ACKPacket(pkt.block)), addr)
                assert b''.join(received) == expected


def test_bad_listen_systemd(main_thread, capsys, monkeypatch):
    with monkeypatch.context() as m:
        m.delenv('DEBUG', raising=False)
        m.setenv('LISTEN_PID', str(os.getpid()))
        m.setenv('LISTEN_FDS', '2')
        main_thread.argv = [
            '--listen', 'systemd',
            '--board', '1234abcd,foo.img',
        ]
        with main_thread:
            pass
        capture = capsys.readouterr()
        assert f'Expected 1 fd from systemd but got 2' in capture.err
        assert main_thread.exit_code == 1


def test_bad_sock_type_systemd(main_thread, capsys, monkeypatch):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as systemd_sock:
        systemd_sock.bind(('127.0.0.1', 0))
        service_sock = systemd_sock.dup()
        with monkeypatch.context() as m, \
                mock.patch('nobodd.systemd.Systemd.LISTEN_FDS_START',
                           service_sock.fileno()):
            m.delenv('DEBUG', raising=False)
            m.setenv('LISTEN_PID', str(os.getpid()))
            m.setenv('LISTEN_FDS', '1')
            main_thread.argv = [
                '--listen', 'systemd',
                '--board', '1234abcd,foo.img',
            ]
            with main_thread:
                pass
            capture = capsys.readouterr()
            assert f'inherited fd {service_sock.fileno()} is not a datagram socket' in capture.err
            assert main_thread.exit_code == 1


def test_bad_addr_family_systemd(main_thread, capsys, monkeypatch):
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as systemd_sock:
        service_sock = systemd_sock.dup()
        with monkeypatch.context() as m, \
                mock.patch('nobodd.systemd.Systemd.LISTEN_FDS_START',
                           service_sock.fileno()):
            m.delenv('DEBUG', raising=False)
            m.setenv('LISTEN_PID', str(os.getpid()))
            m.setenv('LISTEN_FDS', '1')
            main_thread.argv = [
                '--listen', 'systemd',
                '--board', '1234abcd,foo.img',
            ]
            with main_thread:
                pass
            capture = capsys.readouterr()
            assert f'inherited fd {service_sock.fileno()} is not an INET or INET6 socket' in capture.err
            assert main_thread.exit_code == 1


def test_listen_systemd(fat16_disk, main_thread, capsys, monkeypatch):
    with \
        disk.DiskImage(fat16_disk) as img, \
        fs.FatFileSystem(img.partitions[1].data) as boot:

        expected = (boot.root / 'random').read_bytes()

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(('127.0.0.1', 0))
        with monkeypatch.context() as m, \
                mock.patch('nobodd.systemd.Systemd.LISTEN_FDS_START',
                           os.dup(sock.fileno())):
            m.delenv('DEBUG', raising=False)
            m.setenv('LISTEN_PID', str(os.getpid()))
            m.setenv('LISTEN_FDS', '1')
            main_thread.argv = [
                '--listen', 'systemd',
                '--board', f'1234abcd,{fat16_disk}',
            ]
            main_thread.address = sock.getsockname()
            with main_thread:
                main_thread.wait_for_ready(capsys)

                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                    # Start a valid transfer from client...
                    client.settimeout(10)
                    client.sendto(
                        bytes(tftp.RRQPacket('1234abcd/random', 'octet')),
                        main_thread.address)
                    received = []
                    for block, offset in enumerate(
                        range(0, len(expected), 512), start=1
                    ):
                        buf, addr = client.recvfrom(1500)
                        pkt = tftp.Packet.from_bytes(buf)
                        assert isinstance(pkt, tftp.DATAPacket)
                        assert pkt.block == block
                        received.append(pkt.data)
                        client.sendto(bytes(tftp.ACKPacket(pkt.block)), addr)
                    # Because random is a precise multiple of the block size,
                    # there should be one final (empty) DATA packet
                    buf, addr = client.recvfrom(1500)
                    pkt = tftp.Packet.from_bytes(buf)
                    assert isinstance(pkt, tftp.DATAPacket)
                    assert pkt.block == block + 1
                    assert pkt.data == b''
                    client.sendto(bytes(tftp.ACKPacket(pkt.block)), addr)
                assert b''.join(received) == expected
        assert sock.getsockname()


def test_bad_requests(fat16_disk, main_thread, capsys):
    main_thread.argv = [
        '--listen', '127.0.0.1', '--port', '0',
        '--board', f'1234abcd,{fat16_disk}',
        '--board', f'5678abcd,{fat16_disk},1,127.0.0.2',
    ]
    with main_thread:
        main_thread.wait_for_ready(capsys)

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            # Request something that doesn't exist in the image
            client.settimeout(10)
            client.sendto(
                bytes(tftp.RRQPacket('1234abcd/invalid', 'octet')),
                main_thread.address)
            buf, addr = client.recvfrom(1500)
            pkt = tftp.Packet.from_bytes(buf)
            assert isinstance(pkt, tftp.ERRORPacket)
            assert pkt.error == tftp.Error.NOT_FOUND

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            # Request something that won't even parse
            client.settimeout(10)
            client.sendto(
                bytes(tftp.RRQPacket('.', 'octet')),
                main_thread.address)
            buf, addr = client.recvfrom(1500)
            pkt = tftp.Packet.from_bytes(buf)
            assert isinstance(pkt, tftp.ERRORPacket)
            assert pkt.error == tftp.Error.NOT_FOUND

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            # Request something else invalid (a directory)
            client.settimeout(10)
            client.sendto(
                bytes(tftp.RRQPacket('1234abcd/a.dir', 'octet')),
                main_thread.address)
            buf, addr = client.recvfrom(1500)
            pkt = tftp.Packet.from_bytes(buf)
            assert isinstance(pkt, tftp.ERRORPacket)
            assert pkt.error == tftp.Error.UNDEFINED

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            # Request something from an unconfigured prefix
            client.settimeout(10)
            client.sendto(
                bytes(tftp.RRQPacket('deadbeef/random', 'octet')),
                main_thread.address)
            buf, addr = client.recvfrom(1500)
            pkt = tftp.Packet.from_bytes(buf)
            assert isinstance(pkt, tftp.ERRORPacket)
            assert pkt.error == tftp.Error.NOT_FOUND

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            # Request something from the wrong address (127.0.0.1, not
            # 127.0.0.2)
            client.settimeout(10)
            client.sendto(
                bytes(tftp.RRQPacket('5678abcd/random', 'octet')),
                main_thread.address)
            buf, addr = client.recvfrom(1500)
            pkt = tftp.Packet.from_bytes(buf)
            assert isinstance(pkt, tftp.ERRORPacket)
            assert pkt.error == tftp.Error.NOT_AUTH
