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

.. warning::

    At the time of writing, the implementation is strictly *not thread-safe*.
    Attempting to write to the file-system from multiple threads (whether in
    separate instances or not) is likely to result in corruption. Attempting to
    write to the file-system from one thread, while reading from another will
    result in undefined behaviour including incorrect reads.


FatFileSystem
=============

.. autoclass:: FatFileSystem

FatFile
=======

.. autoclass:: FatFile


Internal Classes and Functions
==============================

You should never need to interact with these classes directly; they exist to
enumerate the FAT and different types of root directory under FAT-12, FAT-16,
and FAT-32, and sub-directories (which are common across FAT types).

.. autoclass:: FatTable

.. autoclass:: Fat12Table

.. autoclass:: Fat16Table

.. autoclass:: Fat32Table

.. autoclass:: FatClusters

.. autoclass:: FatDirectory
   :private-members:

.. autoclass:: FatRoot

.. autoclass:: FatSubDirectory

.. autoclass:: Fat12Root

.. autoclass:: Fat16Root

.. autoclass:: Fat32Root

.. autofunction:: fat_type

.. autofunction:: fat_type_from_count
