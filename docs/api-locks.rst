.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2026 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2026 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

=================
nobodd.locks
=================

.. module:: nobodd.locks

This module implements an :abbr:`SREW (Shared Read Exclusive Write)` lock with
re-entrancy and optional non-blocking behaviours. This is used in the
:class:`~nobodd.fs.FatFileSystem` and :class:`~nobodd.path.FatPath`
implementations to safely manage multi-threaded access to the underlying
file-system.


Classes
=======

.. autoclass:: RWLock

.. autoclass:: RWLockState

.. autoclass:: LightSwitch


Support functions
==================

.. autofunction:: remaining
