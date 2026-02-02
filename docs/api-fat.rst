.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2023-2024 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2023-2024 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

=============
nobodd.fat
=============

.. module:: nobodd.fat

Defines the data structures used by the `FAT`_ file system. You should never
need these directly; use the :class:`nobodd.fs.FatFileSystem` class instead.

.. _FAT: https://en.wikipedia.org/wiki/Design_of_the_FAT_file_system


Data structures
===============

.. autoclass:: BIOSParameterBlock

.. autoclass:: ExtendedBIOSParameterBlock

.. autoclass:: FAT32BIOSParameterBlock

.. autoclass:: FAT32InfoSector

.. autoclass:: DirectoryEntry

.. autoclass:: LongFilenameEntry


Support functions
=================

These utility functions help decode certain fields within the aforementioned
structure, or check that tentative contents are valid.

.. autofunction:: lfn_checksum

.. autofunction:: lfn_valid
