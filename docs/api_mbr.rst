.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2023 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2023 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

============
nobodd.mbr
============

.. module:: nobodd.mbr

Defines the data structures used by the `Master Boot Record`_ (MBR)
partitioning style. You should never need these directly; use the
:class:`nobodd.disk.DiskImage` class instead.


Data Structures
===============

.. autoclass:: MBRHeader

.. autoclass:: MBRPartition

.. _Master Boot Record: https://en.wikipedia.org/wiki/Master_boot_record
