=============
nobodd.gpt
=============

.. module:: nobodd.gpt

Defines the data structures used by `GUID Partition Tables`_. You should never
need these directly; use the :class:`nobodd.disk.DiskImage` class instead.


GPTHeader
=========

.. autodata:: GPT_HEADER

.. autoclass:: GPTHeader

GPTPartition
============

.. autodata:: GPT_PARTITION

.. autoclass:: GPTPartition

.. _GUID Partition Tables: https://en.wikipedia.org/wiki/GUID_Partition_Table
