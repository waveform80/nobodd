# nobodd: a boot configuration tool for the Raspberry Pi
#
# Copyright (c) 2026 Dave Jones <dave.jones@canonical.com>
# Copyright (c) 2026 Canonical Ltd.
#
# SPDX-License-Identifier: GPL-3.0

"""
Utility routines for efficiently copying bytes from one file-like object to
another (including seekable and non-seekable objects, such as sockets).
"""


COPY_BUFSIZE = 64 * 1024
def copy_bytes(source, target, *, byterange=None):
    """
    Copy *byterange* bytes (a :class:`range` object), or all bytes (if
    *byterange* is :data:`None`, the default) from *source* to *target*.

    The *target* must implement a ``write`` method, and the *source* must at
    the very least implement a ``read`` method, but preferably a ``readinto``
    method (which will permit a single static buffer to be used during the
    transfer). If *byterange* is not :data:`None`, the *source* must
    additionally implemented ``seek``. No attempt is made to seek the *target*;
    bytes are simply written to it at its current position.
    """
    if byterange is not None:
        if byterange.step != 1:
            raise ValueError('step in byterange must be 1')
        source.seek(byterange.start)
        length = len(byterange)
    else:
        length = None
    if length is not None and length < COPY_BUFSIZE:
        # Fast path for trivially short copies
        target.write(source.read(length))
        return
    # Cache methods to avoid repeated lookup, and to discover if we can
    # pre-allocate the transfer buffer
    write = target.write
    try:
        readinto = source.readinto
    except AttributeError:
        _copy_read_write(source.read, write, length)
    else:
        _copy_readinto_write(readinto, write, length)

def _copy_read_write(read, write, length):
    if length is None:
        while True:
            buf = read(COPY_BUFSIZE)
            if not buf:
                break
            write(buf)
    else:
        while length > 0:
            buf = read(min(COPY_BUFSIZE, length))
            length -= len(buf)
            write(buf)

def _copy_readinto_write(readinto, write, length):
    with memoryview(bytearray(COPY_BUFSIZE)) as buf:
        if length is None:
            while True:
                n = readinto(buf)
                if not n:
                    break
                with buf[:n] as read_buf:
                    write(read_buf)
        else:
            while length > 0:
                with buf[:min(COPY_BUFSIZE, length)] as read_buf:
                    n = readinto(read_buf)
                with buf[:n] as read_buf:
                    write(read_buf)
                length -= n
