import io
import socket
import select
import logging
from threading import Thread

import pytest

from nobodd.tools import BufferedTranscoder
from nobodd.tftpd import *


@pytest.fixture()
def localhost():
    return ('127.0.0.1', 54321)


@pytest.fixture(scope='session')
def tftp_root(tmp_path_factory):
    root = tmp_path_factory.mktemp('tftpd')
    return root


@pytest.fixture(scope='session')
def cmdline_txt(tftp_root):
    p = tftp_root / 'cmdline.txt'
    p.write_text('nbdroot=server:image root=/dev/nbd0p2 quiet splash')
    p.chmod(0o444)
    return p


@pytest.fixture(scope='session')
def initrd_img(tftp_root):
    p = tftp_root / 'initrd.img'
    p.write_bytes(b'\x00' * 4096)
    p.chmod(0o444)
    return p


@pytest.fixture(scope='session')
def unreadable(tftp_root):
    p = tftp_root / 'unreadable.txt'
    p.write_text("Nah nah, can't read me!")
    p.chmod(0o222)
    return p


@pytest.fixture(scope='session')
def tftp_server(tftp_root, cmdline_txt, initrd_img, unreadable):
    # NOTE: Because this is a session scoped fixture, tests must ensure they
    # leave the server "clean" of connections after they finish; other tests
    # may rely upon the server having no outstanding connections
    with SimpleTFTPServer(('127.0.0.1', 0), tftp_root) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield server
        server.shutdown()
        thread.join(10)
        assert not thread.is_alive()


def tftp_recv(sock):
    buf, addr = sock.recvfrom(1500)
    return Packet.from_bytes(buf), addr


def test_clientstate_init(localhost, cmdline_txt):
    state = TFTPClientState(localhost, cmdline_txt)
    assert state.address == localhost
    assert state.source.read
    assert state.mode == 'octet'
    assert state.blocks == {}
    assert state.blocks_read == 0
    assert state.block_size == 512
    assert state.timeout > 0
    assert state.started > 0
    assert state.last_recv == state.started
    assert state.last_send is None

    state = TFTPClientState(localhost, cmdline_txt, mode='netascii')
    assert state.address == localhost
    assert isinstance(state.source, BufferedTranscoder)


def test_clientstate_negotiate(localhost, cmdline_txt):
    state = TFTPClientState(localhost, cmdline_txt)
    assert state.negotiate({}) == {}
    assert state.block_size == 512

    state = TFTPClientState(localhost, cmdline_txt)
    assert state.negotiate({'blksize': '1428'}) == {'blksize': 1428}
    assert state.block_size == 1428

    state = TFTPClientState(localhost, cmdline_txt)
    with pytest.raises(BadOptions):
        assert state.negotiate({'blksize': '1'})

    # Negotiate transfer-size with "real" file which we can query with fstat
    state = TFTPClientState(localhost, cmdline_txt)
    assert state.negotiate({'tsize': '0'}) == {
        'tsize': cmdline_txt.stat().st_size}

    # Negotiate with "fake", but still seekable file
    fake_file = io.BytesIO(cmdline_txt.read_bytes())
    class fake_path:
        def open(mode='rb'):
            return fake_file
    state = TFTPClientState(localhost, fake_path)
    assert state.negotiate({'tsize': '0'}) == {
        'tsize': cmdline_txt.stat().st_size}

    # Negotiate with a wrapped file we can't seek; reject option
    state = TFTPClientState(localhost, cmdline_txt, mode='netascii')
    assert state.negotiate({'tsize': '0'}) == {}

    state = TFTPClientState(localhost, cmdline_txt)
    assert state.negotiate({'timeout': '10'}) == {'timeout': '10'}
    assert state.timeout == 10_000_000_000

    state = TFTPClientState(localhost, cmdline_txt)
    assert state.negotiate({
        'utimeout': '500000', 'timeout': '0.5'}) == {'utimeout': '500000'}
    assert state.timeout == 500_000_000

    state = TFTPClientState(localhost, cmdline_txt)
    with pytest.raises(BadOptions):
        assert state.negotiate({'utimeout': '1000'})


def test_clientstate_transfer(localhost, initrd_img):
    # Simulate transmission of a large(ish) 10MB initrd.img; first block
    state = TFTPClientState(localhost, initrd_img)
    assert len(state.blocks) == 0
    assert state.blocks_read == 0
    assert state.transferred == 0
    assert not state.finished
    assert state.get_block(1) == b'\x00' * state.block_size
    assert len(state.blocks) == 1
    assert state.blocks_read == 1
    assert state.transferred == 0 # not acknowledged yet
    assert not state.finished

    # Re-transmit first block
    assert state.get_block(1) == b'\x00' * state.block_size
    assert len(state.blocks) == 1
    assert state.blocks_read == 1
    assert state.transferred == 0
    assert not state.finished

    # First block acknowledged; check we ignore already ACK'd blocks
    state.ack(1)
    assert len(state.blocks) == 0
    assert state.blocks_read == 1
    assert state.transferred == state.block_size
    with pytest.raises(AlreadyAcknowledged):
        state.get_block(1)
    assert state.transferred == state.block_size
    assert not state.finished

    # Invalid future request
    with pytest.raises(ValueError):
        state.get_block(3)

    # Transfer the rest of the file; ensure sub-block-size last block is
    # required even when it's empty (because file-size is an exact multiple of
    # block size) and that TransferDone is raised correctly
    last_block = (
        initrd_img.stat().st_size + (state.block_size - 1)) // state.block_size
    for block in range(2, last_block + 1):
        assert state.get_block(block) == b'\x00' * state.block_size
        state.ack(block)
        assert state.transferred == state.block_size * block
    assert state.get_block(last_block + 1) == b''
    state.ack(last_block + 1)
    with pytest.raises(TransferDone):
        state.get_block(last_block + 2)
    assert state.finished


def test_tftp_rrq_transfer(tftp_server, caplog):
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client,
        caplog.at_level(logging.INFO)
    ):
        assert not tftp_server.subs._alive

        client.sendto(
            bytes(RRQPacket('cmdline.txt', 'octet')), tftp_server.server_address)
        buf, addr = client.recvfrom(1500)
        pkt = Packet.from_bytes(buf)
        assert isinstance(pkt, DATAPacket)
        assert pkt.block == 1
        assert pkt.data == b'nbdroot=server:image root=/dev/nbd0p2 quiet splash'
        # Responses come from the same address, but *not* the same port as the
        # initial request (an ephemeral port is allocated per transfer)
        assert addr[0] == tftp_server.server_address[0]
        assert addr[1] != tftp_server.server_address[1]
        assert tftp_server.subs._alive

        # Be nice and ACK the DATA packet
        client.sendto(bytes(ACKPacket(pkt.block)), addr)

        assert caplog.record_tuples == [
            ('tftpd', logging.INFO,
             f'127.0.0.1:{client.getsockname()[1]} - RRQ (octet) cmdline.txt'),
        ]


def test_tftp_rrq_transfer_repeat_ack(tftp_server, caplog):
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client,
        caplog.at_level(logging.INFO)
    ):
        client.sendto(
            bytes(RRQPacket('initrd.img', 'octet')), tftp_server.server_address)
        for block, offset in enumerate(range(0, 4096, 512), start=1):
            buf, addr = client.recvfrom(1500)
            pkt = Packet.from_bytes(buf)
            assert isinstance(pkt, DATAPacket)
            assert pkt.block == block
            assert pkt.data == b'\0' * 512
            # ACK the received packet
            client.sendto(bytes(ACKPacket(pkt.block)), addr)
            # ACK the first DATA packet repeatedly after we've received the
            # first block; this should be ignored and should not cause repeated
            # transfers (after later packets are ACKed)
            if block > 1:
                client.sendto(bytes(ACKPacket(1)), addr)

        assert caplog.record_tuples == [
            ('tftpd', logging.INFO,
             f'127.0.0.1:{client.getsockname()[1]} - RRQ (octet) initrd.img'),
        ]


def test_tftp_rrq_transfer_future_ack(tftp_server, caplog):
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client,
        caplog.at_level(logging.INFO)
    ):
        client.sendto(
            bytes(RRQPacket('initrd.img', 'octet')), tftp_server.server_address)
        buf, addr = client.recvfrom(1500)
        pkt = Packet.from_bytes(buf)
        assert isinstance(pkt, DATAPacket)
        assert pkt.block == 1
        assert pkt.data == b'\0' * 512

        # ACK a packet we haven't seen yet; this should return an ERROR packet
        # and terminate the transfer
        client.sendto(bytes(ACKPacket(2)), addr)
        buf, addr = client.recvfrom(1500)
        pkt = Packet.from_bytes(buf)
        assert isinstance(pkt, ERRORPacket)
        assert pkt.error == Error.UNDEFINED

        assert caplog.record_tuples == [
            ('tftpd', logging.INFO,
             f'127.0.0.1:{client.getsockname()[1]} - RRQ (octet) initrd.img'),
        ]


def test_tftp_rrq_transfer_resend(tftp_server, caplog):
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client,
        caplog.at_level(logging.INFO)
    ):
        client.sendto(
            bytes(RRQPacket('cmdline.txt', 'octet')), tftp_server.server_address)
        buf, addr = client.recvfrom(1500)
        pkt = Packet.from_bytes(buf)
        assert isinstance(pkt, DATAPacket)
        assert pkt.block == 1
        assert pkt.data == b'nbdroot=server:image root=/dev/nbd0p2 quiet splash'

        # Don't ACK the packet and await the resend after timeout
        buf, addr = client.recvfrom(1500)
        pkt = Packet.from_bytes(buf)
        assert isinstance(pkt, DATAPacket)
        assert pkt.block == 1
        assert pkt.data == b'nbdroot=server:image root=/dev/nbd0p2 quiet splash'

        # Now we can ACK the packet
        client.sendto(bytes(ACKPacket(pkt.block)), addr)

        assert caplog.record_tuples == [
            ('tftpd', logging.INFO,
             f'127.0.0.1:{client.getsockname()[1]} - RRQ (octet) cmdline.txt'),
        ]


def test_tftp_rrq_transfer_with_options(tftp_server, caplog):
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client,
        caplog.at_level(logging.INFO)
    ):
        client.sendto(
            bytes(RRQPacket('cmdline.txt', 'octet', {'blksize': '128'})),
            tftp_server.server_address)
        buf, addr = client.recvfrom(1500)
        pkt = Packet.from_bytes(buf)
        assert isinstance(pkt, OACKPacket)
        assert pkt.options == {'blksize': '128'}
        # Responses come from the same address, but *not* the same port as the
        # initial request (an ephemeral port is allocated per transfer)
        assert addr[0] == tftp_server.server_address[0]
        assert addr[1] != tftp_server.server_address[1]

        client.sendto(bytes(ACKPacket(0)), addr)
        buf, addr = client.recvfrom(1500)
        pkt = Packet.from_bytes(buf)
        assert isinstance(pkt, DATAPacket)
        assert pkt.block == 1
        assert pkt.data == b'nbdroot=server:image root=/dev/nbd0p2 quiet splash'

        # Be nice and ACK the DATA packet
        client.sendto(bytes(ACKPacket(pkt.block)), addr)

        assert caplog.record_tuples == [
            ('tftpd', logging.INFO,
             f'127.0.0.1:{client.getsockname()[1]} - RRQ (octet) cmdline.txt'),
        ]


def test_tftp_rrq_transfer_resend_and_die(tftp_server, caplog):
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client,
        caplog.at_level(logging.INFO)
    ):
        client.sendto(
            bytes(RRQPacket('cmdline.txt', 'octet', {'utimeout': '100000'})),
            tftp_server.server_address)
        buf, addr = client.recvfrom(1500)
        pkt = Packet.from_bytes(buf)
        assert isinstance(pkt, OACKPacket)
        assert pkt.options == {'utimeout': '100000'}
        client.sendto(bytes(ACKPacket(0)), addr)

        for i in range(4):
            # We should receive at least 4 retries before the server finally
            # gives up
            buf, addr = client.recvfrom(1500)
            pkt = Packet.from_bytes(buf)
            assert isinstance(pkt, DATAPacket)
            assert pkt.block == 1
            assert pkt.data == b'nbdroot=server:image root=/dev/nbd0p2 quiet splash'

        # No need to ACK the packet; the server's given up by this point
        assert caplog.record_tuples == [
            ('tftpd', logging.INFO,
             f'127.0.0.1:{client.getsockname()[1]} - RRQ (octet) cmdline.txt'),
            ('tftpd', logging.INFO,
             f'127.0.0.1:{client.getsockname()[1]} - timed out to 127.0.0.1:{addr[1]}'),
        ]


def test_tftp_rrq_transfer_bad_options(tftp_server, caplog):
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client,
        caplog.at_level(logging.INFO)
    ):
        client.sendto(
            bytes(RRQPacket('cmdline.txt', 'octet', {'blksize': '1'})),
            tftp_server.server_address)
        buf, addr = client.recvfrom(1500)
        pkt = Packet.from_bytes(buf)
        assert isinstance(pkt, ERRORPacket)
        assert pkt.error == Error.INVALID_OPT

        assert caplog.record_tuples == [
            ('tftpd', logging.INFO,
             f'127.0.0.1:{client.getsockname()[1]} - RRQ (octet) cmdline.txt'),
            ('tftpd', logging.INFO,
             f'127.0.0.1:{client.getsockname()[1]} - ERROR - bad options; silly block size'),
        ]


def test_tftp_rrq_transfer_bad_filename(tftp_server, caplog):
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client,
        caplog.at_level(logging.INFO)
    ):
        client.sendto(
            bytes(RRQPacket('foo.txt', 'octet')), tftp_server.server_address)
        buf, addr = client.recvfrom(1500)
        pkt = Packet.from_bytes(buf)
        assert isinstance(pkt, ERRORPacket)
        assert pkt.error == Error.NOT_FOUND

        assert caplog.record_tuples == [
            ('tftpd', logging.INFO,
             f'127.0.0.1:{client.getsockname()[1]} - RRQ (octet) foo.txt'),
            ('tftpd', logging.INFO,
             f'127.0.0.1:{client.getsockname()[1]} - ERROR - not found'),
        ]


def test_tftp_rrq_transfer_permission_error(tftp_server, caplog):
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client,
        caplog.at_level(logging.INFO)
    ):
        client.sendto(
            bytes(RRQPacket('unreadable.txt', 'octet')), tftp_server.server_address)
        buf, addr = client.recvfrom(1500)
        pkt = Packet.from_bytes(buf)
        assert isinstance(pkt, ERRORPacket)
        assert pkt.error == Error.NOT_AUTH

        assert caplog.record_tuples == [
            ('tftpd', logging.INFO,
             f'127.0.0.1:{client.getsockname()[1]} - RRQ (octet) unreadable.txt'),
            ('tftpd', logging.INFO,
             f'127.0.0.1:{client.getsockname()[1]} - ERROR - permission denied'),
        ]


def test_tftp_wrq_transfer(tftp_server, caplog):
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client,
        caplog.at_level(logging.INFO)
    ):
        client.sendto(
            bytes(WRQPacket('cmdline.txt', 'octet')), tftp_server.server_address)
        buf, addr = client.recvfrom(1500)
        pkt = Packet.from_bytes(buf)
        assert isinstance(pkt, ERRORPacket)
        assert pkt.error == Error.UNDEFINED
        assert pkt.message == (
            "Unsupported operation, 'SimpleTFTPHandler' object has no "
            "attribute 'do_WRQ'")

        assert caplog.record_tuples == [
            ('tftpd', logging.WARNING,
             f'127.0.0.1:{client.getsockname()[1]} - ERROR - unsupported operation; '
             "'SimpleTFTPHandler' object has no attribute 'do_WRQ'"),
        ]


def test_tftp_client_error1(tftp_server, caplog):
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client,
        caplog.at_level(logging.INFO)
    ):
        client.sendto(
            bytes(ERRORPacket(Error.UNDEFINED)), tftp_server.server_address)
        # If client sends an error on the main connection, it's simply ignored
        assert select.select([client], [], [], 0.1) == ([], [], [])

        # To the extent it's not even logging, because this is a valid way to
        # terminate a connection
        assert caplog.record_tuples == []


def test_tftp_client_error2(tftp_server, caplog):
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client,
        caplog.at_level(logging.INFO)
    ):
        client.sendto(
            bytes(RRQPacket('initrd.img', 'octet')), tftp_server.server_address)
        buf, addr = client.recvfrom(1500)
        pkt = Packet.from_bytes(buf)
        assert isinstance(pkt, DATAPacket)
        assert pkt.block == 1
        assert pkt.data == b'\0' * 512

        # If client sends an error on the ephemeral connection, it simply
        # terminates the transfer immediately
        client.sendto(bytes(ERRORPacket(Error.UNDEFINED)), addr)

        assert caplog.record_tuples == [
            ('tftpd', logging.INFO,
             f'127.0.0.1:{client.getsockname()[1]} - RRQ (octet) initrd.img'),
        ]


def test_tftp_bad_request(tftp_server, caplog):
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client,
        caplog.at_level(logging.INFO)
    ):
        client.sendto(b'\x00\x08\x00\x00\x00', tftp_server.server_address)
        buf, addr = client.recvfrom(1500)
        pkt = Packet.from_bytes(buf)
        assert isinstance(pkt, ERRORPacket)
        assert pkt.error == Error.UNDEFINED
        assert pkt.message == 'Invalid request, invalid packet opcode 8'

        assert caplog.record_tuples == [
            ('tftpd', logging.WARNING,
             f'127.0.0.1:{client.getsockname()[1]} - ERROR - invalid request; '
             f'invalid packet opcode 8'),
        ]


def test_tftp_bad_client(tftp_server, caplog):
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client1,
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client2,
        caplog.at_level(logging.INFO)
    ):
        # Start a valid transfer from client1...
        client1.sendto(
            bytes(RRQPacket('cmdline.txt', 'octet', {'blksize': '128'})),
            tftp_server.server_address)
        buf, addr = client1.recvfrom(1500)
        pkt = Packet.from_bytes(buf)
        assert isinstance(pkt, OACKPacket)
        assert pkt.options == {'blksize': '128'}
        assert addr[0] == tftp_server.server_address[0]
        assert addr[1] != tftp_server.server_address[1]

        # Now have client2 hijack the ephemeral port of client1 and try to
        # talk to the server with an otherwise valid response. This should be
        # ignored by the server...
        client2.sendto(bytes(ACKPacket(0)), addr)
        # ...client1 should be able to talk, however
        client1.sendto(bytes(ACKPacket(0)), addr)
        assert select.select(
            [client1, client2], [], [], 0.1) == ([client1], [], [])

        buf, addr = client1.recvfrom(1500)
        pkt = Packet.from_bytes(buf)
        assert isinstance(pkt, DATAPacket)
        assert pkt.block == 1

        # Be nice and ACK the DATA packet from client1
        client1.sendto(bytes(ACKPacket(pkt.block)), addr)

        assert caplog.record_tuples == [
            ('tftpd', logging.INFO,
             f'127.0.0.1:{client1.getsockname()[1]} - RRQ (octet) cmdline.txt'),
            ('tftpd', logging.WARNING,
             f'127.0.0.1:{client2.getsockname()[1]} - IGNORE - bad client '
             f'for 127.0.0.1:{addr[1]}'),
        ]
