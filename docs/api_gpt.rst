=============
nobodd.gpt
=============

.. module:: nobodd.gpt

Defines the data structures used by `GUID Partition Tables`_. You should never
need these directly; use the :class:`nobodd.disk.DiskImage` class instead.


Data Structures
===============

.. autoclass:: GPTHeader

.. autoclass:: GPTPartition

.. _GUID Partition Tables: https://en.wikipedia.org/wiki/GUID_Partition_Table
