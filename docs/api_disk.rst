==============
nobodd.disk
==============

.. module:: nobodd.disk

The :mod:`nobodd.disk` module contains the :class:`DiskImage` class which is
the primary entry point for handling disk images. Constructed with a filename
(or file-like object which provides a valid :meth:`~io.IOBase.fileno` method),
the class will attempt to determine if `MBR`_ or `GPT`_ style partitioning is
in use. The :attr:`DiskImage.partitions` attribute can then be queried to
enumerate, or access the data of, individual partitions:

.. code-block:: pycon

    >>> from nobodd.disk import DiskImage
    >>> img = DiskImage('test-gpt.img')
    >>> img.partitions.style
    'gpt'
    >>> img.partitions
    <nobodd.disk.DiskPartitionsGPT object at 0x7f6248b99c30>
    >>> len(img.partitions)
    2
    >>> img.partitions[1]
    <DiskPartition size=268435456 label='Microsoft basic data' type=UUID('ebd0a0a2-b9e5-4433-87c0-68b6b72699c7')>
    >>> img.partitions[2]
    <DiskPartition size=801095168 label='Linux filesystem' type=UUID('0fc63daf-8483-4772-8e79-3d69d8477de4')>

Note that partitions are numbered from 1 and that, especially in the case of
`MBR`_, partition numbers may not be contiguous: primary partitions are
numbered 1 through 4, but logical partitions may only exist in one primary
partition, and are numbered from 5. Hence it is entirely valid to have
partitions 1, 5, and 6:

.. code-block:: pycon

    >>> from nobodd.disk import DiskImage
    >>> img = DiskImage('test-ebr.img')
    >>> img.partitions
    <nobodd.disk.DiskPartitionsMBR object at 0x7f74fda8d3f0>
    >>> img.partitions.style
    'mbr'
    >>> len(img.partitions)
    3
    >>> list(img.partitions.keys())
    [1, 5, 6]
    >>> img.partitions[1]
    <DiskPartition size=536870912 label='Partition 1' type=12>
    >>> img.partitions[5]
    <DiskPartition size=536870912 label='Partition 5' type=131>
    >>> img.partitions[6]
    <DiskPartition size=1070596096 label='Partition 6' type=131>

`GPT`_ partition tables may also have non-contiguous numbering, although this
is less common in practice. The :attr:`DiskPartition.data` attribute can be
used to access the content of the partition as a buffer object (see
:class:`memoryview`).

DiskImage
=========

.. autoclass:: DiskImage

DiskPartition
=============

.. autoclass:: DiskPartition

Internal Classes
================

You should not need to use these classes directly; they will be instantiated
automatically when querying the :attr:`DiskImage.partitions` attribute
according to the detected table format.

.. autoclass:: DiskPartitionsGPT

.. autoclass:: DiskPartitionsMBR

.. _MBR: https://en.wikipedia.org/wiki/Master_boot_record
.. _GPT: https://en.wikipedia.org/wiki/GUID_Partition_Table
