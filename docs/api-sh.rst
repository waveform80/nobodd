.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2026 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2026 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

============
nobodd.sh
============

.. module:: nobodd.sh

This module contains the implementation (and entry point) of the
:program:`nobodd-sh` application.


Application functions
=====================

.. autofunction:: main

.. autofunction:: get_parser

.. autofunction:: get_paths

.. autofunction:: same_fs


Command implementations
=======================

.. autofunction:: do_cat

.. autofunction:: do_cp

.. autofunction:: do_help

.. autofunction:: do_ls

.. autofunction:: do_mkdir

.. autofunction:: do_mv

.. autofunction:: do_rm

.. autofunction:: do_rmdir

.. autofunction:: do_touch


Support classes
===============

.. autoclass:: StdPath
