import io

import pytest

from nobodd.tools import BufferedTranscoder
from nobodd.tftpd import *


@pytest.fixture()
def localhost():
    return ('127.0.0.1', 54321)


@pytest.fixture()
def cmdline_txt(tmp_path):
    p = tmp_path / 'cmdline.txt'
    p.write_text('nbdroot=server:image root=/dev/nbd0p2 quiet splash')
    return p


@pytest.fixture()
def initrd_img(tmp_path):
    p = tmp_path / 'initrd.img'
    p.write_bytes(b'\x00' * 10485760)
    return p


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
