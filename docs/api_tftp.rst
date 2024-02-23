.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2023-2024 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2023-2024 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

==============
nobodd.tftp
==============

.. module:: nobodd.tftp

Defines the data structures used by the `Trivial File Transfer Protocol`_
(TFTP). You should never need these directly; use the classes in
:mod:`nobodd.tftpd` to construct a TFTP server instead.


Enumerations
============

.. autoclass:: OpCode

.. autoclass:: Error


Constants
=========

.. data:: TFTP_BLKSIZE
.. data:: TFTP_MIN_BLKSIZE
.. data:: TFTP_DEF_BLKSIZE
.. data:: TFTP_MAX_BLKSIZE

    Constants defining the ``blksize`` TFTP option; the name of the option, its
    minimum, default, and maximum values.

.. data:: TFTP_TIMEOUT
.. data:: TFTP_UTIMEOUT
.. data:: TFTP_MIN_TIMEOUT_NS
.. data:: TFTP_DEF_TIMEOUT_NS
.. data:: TFTP_MAX_TIMEOUT_NS

    Constants defining the ``timeout`` and ``utimeout`` TFTP options; the name
    of the options, the minimum, default, and maximum values, in units of
    nano-seconds.

.. data:: TFTP_BINARY
.. data:: TFTP_NETASCII
.. data:: TFTP_MODES

    Constants defining the available transfer modes.

.. data:: TFTP_TSIZE

    Constant defining the name of the ``tsize`` TFTP option.

.. data:: TFTP_OPTIONS

    Constant defining the TFTP options available for negotiation.


Packets
=======

.. autoclass:: Packet

.. autoclass:: RRQPacket

.. autoclass:: WRQPacket

.. autoclass:: DATAPacket

.. autoclass:: ACKPacket

.. autoclass:: ERRORPacket

.. autoclass:: OACKPacket

.. _Trivial File Transfer Protocol: https://en.wikipedia.org/wiki/Trivial_File_Transfer_Protocol
