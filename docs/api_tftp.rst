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


Packets
=======

.. autoclass:: Packet

.. autoclass:: RRQPacket

.. autoclass:: DATAPacket

.. autoclass:: ACKPacket

.. autoclass:: ERRORPacket

.. autoclass:: OACKPacket

.. _Trivial File Transfer Protocol: https://en.wikipedia.org/wiki/Trivial_File_Transfer_Protocol
