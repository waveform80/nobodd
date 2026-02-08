.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2024-2026 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2024-2026 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

=============
nobodd.prep
=============

.. module:: nobodd.prep

This module contains the implementation (and entry point) of the
:program:`nobodd-prep` application.


Application functions
=====================

.. autofunction:: main

.. autofunction:: get_parser

.. autofunction:: prepare_image

.. autofunction:: remove_items

.. autofunction:: copy_items

.. autofunction:: rewrite_cmdline

.. autofunction:: detect_partitions
