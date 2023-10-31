============
nobodd.path
============

.. module:: nobodd.path

Defines the :class:`FatPath` class, a Path-like class for interacting with
directories and sub-directories in a :class:`~nobodd.fs.FatFileSystem`
instance. You should never need to construct this class directly; instead it
should be derived from the :attr:`~nobodd.fs.FatFileSystem.root` attribute
which is itself a :class:`FatPath` instance.

.. code-block:: pycon

    >>> from nobodd.disk import DiskImage
    >>> from nobodd.fs import FatFileSystem
    >>> img = DiskImage('test.img')
    >>> fs = FatFileSystem(img.partitions[1].data)
    >>> for p in fs.root.iterdir():
    ...     print(repr(p))
    ...
    FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/foo')
    FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/bar.txt')
    FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/setup.cfg')
    FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/baz')
    FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/adir')
    FatPath(<FatFileSystem label='TEST' fat_type='fat16'>, '/BDIR')


FatPath
=======

.. autoclass:: FatPath

Internal Functions
==================

.. autofunction:: get_filename_entry

.. autofunction:: get_timestamp

.. autofunction:: get_cluster
