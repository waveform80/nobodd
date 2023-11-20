===============
nobodd.fs
===============

.. module:: nobodd.fs

The :mod:`nobodd.fs` module contains the :class:`FatFileSystem` class which is
the primary entry point for reading FAT file-systems. Constructed with a buffer
object representing a memory mapping of the file-system, the class will
determine whether the format is FAT12, FAT16, or FAT32. The
:attr:`~FatFileSystem.root` attribute provides a Path-like object representing
the root directory of the file-system.

.. code-block:: pycon

    >>> from nobodd.disk import DiskImage
    >>> from nobodd.fs import FatFileSystem
    >>> img = DiskImage('test-gpt.img')
    >>> fs = FatFileSystem(img.partitions[1].data)
    >>> fs.fat_type
    'fat16'
    >>> fs.root
    FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/')


FatFileSystem
=============

.. autoclass:: FatFileSystem

FatFile
=======

.. autoclass:: FatFile


Internal Classes and Functions
==============================

You should never need to interact with these classes directly; they exist to
enumerate the different types of root directory under FAT-12, FAT-16, and
FAT-32, and sub-directories (which are common across FAT types).

.. autoclass:: FatDirectory

.. autoclass:: FatSubDirectory

.. autoclass:: Fat16Root

.. class:: Fat32Root

    This is a trivial alias of :class:`FatSubDirectory` because, in FAT-32, the
    root directory is represented by the same structure as a regular
    sub-directory.

.. class:: Fat12Root

    This is a trivial alias of :class:`Fat16Root` because FAT-12 uses the same
    structure as FAT-16 for the root directory.

.. autofunction:: fat_type

.. autofunction:: fat_type_from_count
