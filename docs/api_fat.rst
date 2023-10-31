=============
nobodd.fat
=============

.. module:: nobodd.fat

Defines the data structures used by the `FAT`_ file system. You should never
need these directly; use the :class:`nobodd.fs.FatFileSystem` class instead.


Data Structures
===============

.. autoclass:: BIOSParameterBlock

.. autoclass:: ExtendedBIOSParameterBlock

.. autoclass:: FAT32BIOSParameterBlock

.. autoclass:: DirectoryEntry

.. autoclass:: LongFilenameEntry

.. _FAT: https://en.wikipedia.org/wiki/Design_of_the_FAT_file_system
