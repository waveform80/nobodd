.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2024 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2024 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

=================
nobodd.netascii
=================

.. module:: nobodd.netascii

Registers a Python codec to translate strings to the TFTP netascii encoding
(defined in the TELNET `RFC 764`_, under the printer and keyboard section).
This is intended to translate line-endings of text files transparently between
platforms, but only handles ASCII characters.

.. note::

    TFTPd implementations could *probably* ignore this as a historical artefact
    at this point and assume all transfers will be done with "octet" (straight
    byte for byte) encoding, as seems to be common practice. However, netascii
    isn't terribly hard to support, hence the inclusion of this module.

The functions in this module should never need to be accessed directly. Simply
use the 'netascii' encoding as you would any other Python byte-encoding:

.. code-block:: pycon

    >>> import os
    >>> os.linesep
    '\n'
    >>> import nobodd.netascii
    >>> 'foo\nbar\r'.encode('netascii')
    b'foo\r\nbar\r\0'
    >>> b'foo\r\nbar\r\0\r\r'.decode('netascii', errors='replace')
    'foo\nbar\r??'

.. _RFC 764: https://datatracker.ietf.org/doc/html/rfc764


Internal Functions
==================

.. autofunction:: encode

.. autofunction:: decode

.. autoclass:: IncrementalEncoder

.. autoclass:: IncrementalDecoder

.. autoclass:: StreamWriter

.. autoclass:: StreamReader
