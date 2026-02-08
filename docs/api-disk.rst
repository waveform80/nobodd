.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2023-2026 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2023-2026 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

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
    >>> img = DiskImage('gpt_disk.img')
    >>> img
    <DiskImage file=<_io.BufferedReader name='gpt_disk.img'> style='gpt' signature=UUID('733b49a8-6918-4e44-8d3d-47ed9b481335')>
    >>> img.style
    'gpt'
    >>> len(img.partitions)
    4
    >>> img.partitions
    DiskPartitionsGPT({
    1: <DiskPartition size=8388608 label='big-part' type=UUID('ebd0a0a2-b9e5-4433-87c0-68b6b72699c7')>,
    2: <DiskPartition size=204800 label='little-part1' type=UUID('ebd0a0a2-b9e5-4433-87c0-68b6b72699c7')>,
    5: <DiskPartition size=4194304 label='medium-part' type=UUID('ebd0a0a2-b9e5-4433-87c0-68b6b72699c7')>,
    6: <DiskPartition size=204800 label='little-part2' type=UUID('ebd0a0a2-b9e5-4433-87c0-68b6b72699c7')>,
    })

Note that partitions are numbered from 1 and that, especially in the case of
`MBR`_, partition numbers may not be contiguous: primary partitions are
numbered 1 through 4, but logical partitions may only exist in one primary
partition, and are numbered from 5. Hence it is entirely valid to have
partitions 1, 5, and 6:

.. code-block:: pycon

    >>> from nobodd.disk import DiskImage
    >>> img = DiskImage('test-ebr.img')
    >>> img.style
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
is less common in practice.

It is also worth noting that partitions need not be contiguous on disk (it is
valid for gaps to be present, and this is commonly the case where partitions
are aligned on various boundaries). Furthermore, partitions may not be
physically laid out on disk in the same order as their numbering suggests. That
is, partition 2 may have a lower starting sector than partition 1, and so on.

The :attr:`DiskPartition.data` attribute can be used to access the content of
the partition as a buffer object (see :class:`memoryview`).


DiskImage
=========

.. autoclass:: DiskImage


DiskPartition
=============

.. autoclass:: DiskPartition


Support classes
================

You should not need to use these classes directly; they will be instantiated
automatically when querying the :attr:`DiskImage.partitions` attribute
according to the detected table format.

.. autoclass:: DiskPartitionsGPT

.. autoclass:: DiskPartitionsMBR

.. _MBR: https://en.wikipedia.org/wiki/Master_boot_record
.. _GPT: https://en.wikipedia.org/wiki/GUID_Partition_Table
