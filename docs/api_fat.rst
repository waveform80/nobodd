=============
nobodd.fat
=============

.. module:: nobodd.fat

Defines the data structures used by the `FAT`_ file system. You should never
need these directly; use the :class:`nobodd.fs.FatFileSystem` class instead.


BIOSParameterBlock
==================

.. autodata:: BIOS_PARAMETER_BLOCK

.. autoclass:: BIOSParameterBlock

ExtendedBIOSParameterBlock
==========================

.. autodata:: EXTENDED_BIOS_PARAMETER_BLOCK

.. autoclass:: ExtendedBIOSParameterBlock

FAT32BIOSParameterBlock
=======================

.. autodata:: FAT32_BIOS_PARAMETER_BLOCK

.. autoclass:: FAT32BIOSParameterBlock

DirectoryEntry
==============

.. autodata:: DIRECTORY_ENTRY

.. autoclass:: DirectoryEntry

LongFilenameEntry
=================

.. autodata:: LONG_FILENAME_ENTRY

.. autoclass:: LongFilenameEntry

.. _FAT: https://en.wikipedia.org/wiki/Design_of_the_FAT_file_system
