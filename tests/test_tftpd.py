import io
import socket
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
    p.write_bytes(b'\x00' * 10485760)
    p.chmod(0o444)
    return p


@pytest.fixture(scope='session')
def tftp_server(tftp_root, cmdline_txt, initrd_img):
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


def test_tftp_rrq_transfer(tftp_server):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        assert not tftp_server.subs._alive

        tx_pkt1 = RRQPacket('cmdline.txt', 'octet')
        client.sendto(bytes(tx_pkt1), tftp_server.server_address)
        buf, tx_addr1 = client.recvfrom(1500)
        rx_pkt1 = Packet.from_bytes(buf)
        assert isinstance(rx_pkt1, DATAPacket)
        assert rx_pkt1.block == 1
        assert rx_pkt1.data == b'nbdroot=server:image root=/dev/nbd0p2 quiet splash'
        # Responses come from the same address, but *not* the same port as the
        # initial request (an ephemeral port is allocated per transfer)
        assert tx_addr1[0] == tftp_server.server_address[0]
        assert tx_addr1[1] != tftp_server.server_address[1]
        assert tftp_server.subs._alive

        # Be nice and ACK the DATA packet
        tx_pkt2 = ACKPacket(rx_pkt1.block)
        client.sendto(bytes(tx_pkt2), tx_addr1)


def test_tftp_rrq_transfer_with_options(tftp_server):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        tx_pkt1 = RRQPacket('cmdline.txt', 'octet', {'blksize': '128'})
        client.sendto(bytes(tx_pkt1), tftp_server.server_address)
        buf, tx_addr1 = client.recvfrom(1500)
        rx_pkt1 = Packet.from_bytes(buf)
        assert isinstance(rx_pkt1, OACKPacket)
        assert rx_pkt1.options == {'blksize': '128'}
        # Responses come from the same address, but *not* the same port as the
        # initial request (an ephemeral port is allocated per transfer)
        assert tx_addr1[0] == tftp_server.server_address[0]
        assert tx_addr1[1] != tftp_server.server_address[1]

        tx_pkt2 = ACKPacket(0)
        client.sendto(bytes(tx_pkt2), tx_addr1)
        buf, tx_addr2 = client.recvfrom(1500)
        rx_pkt2 = Packet.from_bytes(buf)
        assert isinstance(rx_pkt2, DATAPacket)
        assert rx_pkt2.block == 1
        assert rx_pkt2.data == b'nbdroot=server:image root=/dev/nbd0p2 quiet splash'
        assert tx_addr1 == tx_addr2

        # Be nice and ACK the DATA packet
        tx_pkt3 = ACKPacket(rx_pkt2.block)
        client.sendto(bytes(tx_pkt3), tx_addr2)


def test_tftp_rrq_transfer_bad_options(tftp_server):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        tx_pkt1 = RRQPacket('cmdline.txt', 'octet', {'blksize': '1'})
        client.sendto(bytes(tx_pkt1), tftp_server.server_address)
        buf, tx_addr1 = client.recvfrom(1500)
        rx_pkt1 = Packet.from_bytes(buf)
        assert isinstance(rx_pkt1, ERRORPacket)
        assert rx_pkt1.error == Error.INVALID_OPT


def test_tftp_rrq_transfer_bad_filename(tftp_server):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        tx_pkt1 = RRQPacket('foo.txt', 'octet')
        client.sendto(bytes(tx_pkt1), tftp_server.server_address)
        buf, tx_addr1 = client.recvfrom(1500)
        rx_pkt1 = Packet.from_bytes(buf)
        assert isinstance(rx_pkt1, ERRORPacket)
        assert rx_pkt1.error == Error.NOT_FOUND


def test_tftp_wrq_transfer(tftp_server):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        tx_pkt = WRQPacket('cmdline.txt', 'octet')
        client.sendto(bytes(tx_pkt), tftp_server.server_address)
        buf, tx_addr = client.recvfrom(1500)
        rx_pkt = Packet.from_bytes(buf)
        assert isinstance(rx_pkt, ERRORPacket)
        assert rx_pkt.error == Error.UNDEFINED
        assert rx_pkt.message == (
            "Unsupported operation, 'SimpleTFTPHandler' object has no "
            "attribute 'do_WRQ'")


def test_tftp_bad_request(tftp_server):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        tx_pkt = WRQPacket('cmdline.txt', 'octet')
        client.sendto(b'\x00\x08\x00\x00\x00', tftp_server.server_address)
        buf, tx_addr = client.recvfrom(1500)
        rx_pkt = Packet.from_bytes(buf)
        assert isinstance(rx_pkt, ERRORPacket)
        assert rx_pkt.error == Error.UNDEFINED
        assert rx_pkt.message == 'Invalid request, invalid packet opcode 8'
