.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2026 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2026 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

=================
nobodd.transfer
=================

.. module:: nobodd.transfer

The module implements the :func:`copy_bytes` function which does the same as
:func:`shutil.copyfileobj` but operates more efficiently (in a similar manner
to :func:`shutil.copyfile` which we can't use because that expects to operate
on the "real" file-system).


Functions
=========

.. autofunction:: copy_bytes
