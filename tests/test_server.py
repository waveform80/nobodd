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

        def run(self):
            try:
                self.exit_code = main(self.argv)
            except Exception as e:
                self.exception = e

        def wait_for_ready(self, capsys):
            start = time()
            while time() - start < 10:
                capture = capsys.readouterr()
                if 'Ready' in capture.err:
                    return
                sleep(0.1)
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
    assert capture.out.strip() == '0.1'

    with pytest.raises(SystemExit) as err:
        main(['--help'])
    assert err.value.code == 0
    capture = capsys.readouterr()
    assert capture.out.startswith('usage:')


def test_ctrl_c(main_thread, capsys):
    main_thread.argv = ['--listen', '127.0.0.1', '--port', '54321']
    with main_thread:
        os.kill(os.getpid(), signal.SIGINT)
    capture = capsys.readouterr()
    assert capture.err.strip().endswith('Interrupted')
    assert main_thread.exception is None
    assert main_thread.exit_code == 2


def test_sigterm(main_thread, capsys):
    main_thread.argv = ['--listen', '127.0.0.1', '--port', '54321']
    with main_thread:
        os.kill(os.getpid(), signal.SIGTERM)
    capture = capsys.readouterr()
    assert capture.err.strip().endswith('Terminated')
    assert main_thread.exception is None
    assert main_thread.exit_code == 0


def test_error_exit_no_debug(main_thread, capsys, monkeypatch):
    with (
        mock.patch('nobodd.server.get_parser') as get_parser,
        monkeypatch.context() as m,
    ):
        m.delenv('DEBUG', raising=False)
        get_parser.side_effect = RuntimeError('trouble is bad')

        main_thread.argv = ['--listen', '127.0.0.1', '--port', '54321']
        with main_thread:
            pass
        capture = capsys.readouterr()
        assert 'trouble is bad' in capture.err
        assert main_thread.exception is None
        assert main_thread.exit_code == 1


def test_error_exit_with_debug(main_thread, monkeypatch):
    with (
        mock.patch('nobodd.server.get_parser') as get_parser,
        monkeypatch.context() as m,
    ):
        m.setenv('DEBUG', '1')
        get_parser.side_effect = RuntimeError('trouble is bad')

        main_thread.argv = ['--listen', '127.0.0.1', '--port', '54321']
        with main_thread:
            pass
        assert isinstance(main_thread.exception, RuntimeError)


def test_error_exit_with_pdb(main_thread, capsys, monkeypatch):
    with (
        mock.patch('nobodd.server.get_parser') as get_parser,
        mock.patch('pdb.post_mortem') as post_mortem,
        monkeypatch.context() as m,
    ):
        m.setenv('DEBUG', '2')
        get_parser.side_effect = RuntimeError('trouble is bad')

        main_thread.argv = ['--listen', '127.0.0.1', '--port', '54321']
        with main_thread:
            pass
        assert post_mortem.called


def test_regular_operation(fat16_disk, main_thread, capsys):
    with (
        disk.DiskImage(fat16_disk) as img,
        fs.FatFileSystem(img.partitions[1].data) as boot,
    ):
        expected = (boot.root / 'random').read_bytes()

    main_thread.argv = [
        '--listen', '127.0.0.1', '--port', '54321',
        '--board', f'1234abcd,{fat16_disk}',
    ]
    with main_thread:
        main_thread.wait_for_ready(capsys)

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            # Start a valid transfer from client...
            client.settimeout(10)
            client.sendto(
                bytes(tftp.RRQPacket('1234abcd/random', 'octet')),
                ('127.0.0.1', 54321))
            received = []
            for block, offset in enumerate(range(0, len(expected), 512), start=1):
                buf, addr = client.recvfrom(1500)
                pkt = tftp.Packet.from_bytes(buf)
                assert isinstance(pkt, tftp.DATAPacket)
                assert pkt.block == block
                received.append(pkt.data)
                client.sendto(bytes(tftp.ACKPacket(pkt.block)), addr)
            # Because random is a precise multiple of the block size, there should
            # be one final (empty) DATA packet
            buf, addr = client.recvfrom(1500)
            pkt = tftp.Packet.from_bytes(buf)
            assert isinstance(pkt, tftp.DATAPacket)
            assert pkt.block == block + 1
            assert pkt.data == b''
            client.sendto(bytes(tftp.ACKPacket(pkt.block)), addr)
        assert b''.join(received) == expected


def test_bad_requests(fat16_disk, main_thread, capsys):
    main_thread.argv = [
        '--listen', '127.0.0.1', '--port', '54321',
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
                ('127.0.0.1', 54321))
            buf, addr = client.recvfrom(1500)
            pkt = tftp.Packet.from_bytes(buf)
            assert isinstance(pkt, tftp.ERRORPacket)
            assert pkt.error == tftp.Error.NOT_FOUND

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            # Request something that won't even parse
            client.settimeout(10)
            client.sendto(
                bytes(tftp.RRQPacket('.', 'octet')),
                ('127.0.0.1', 54321))
            buf, addr = client.recvfrom(1500)
            pkt = tftp.Packet.from_bytes(buf)
            assert isinstance(pkt, tftp.ERRORPacket)
            assert pkt.error == tftp.Error.NOT_FOUND

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            # Request something else invalid (a directory)
            client.settimeout(10)
            client.sendto(
                bytes(tftp.RRQPacket('1234abcd/a.dir', 'octet')),
                ('127.0.0.1', 54321))
            buf, addr = client.recvfrom(1500)
            pkt = tftp.Packet.from_bytes(buf)
            assert isinstance(pkt, tftp.ERRORPacket)
            assert pkt.error == tftp.Error.UNDEFINED

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            # Request something from an unconfigured prefix
            client.settimeout(10)
            client.sendto(
                bytes(tftp.RRQPacket('deadbeef/random', 'octet')),
                ('127.0.0.1', 54321))
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
                ('127.0.0.1', 54321))
            buf, addr = client.recvfrom(1500)
            pkt = tftp.Packet.from_bytes(buf)
            assert isinstance(pkt, tftp.ERRORPacket)
            assert pkt.error == tftp.Error.NOT_AUTH
