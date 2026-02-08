.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2023-2026 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2023-2026 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

================
nobodd.config
================

.. module:: nobodd.config

This module contains the classes and functions used to configure the main
nobodd application. These are not likely to be of much use to other
applications, but are documented here just in case.


ConfigArgumentParser
====================

.. autoclass:: ConfigArgumentParser


Board
=====

.. autoclass:: Board


Conversion functions
====================

.. autofunction:: port

.. autofunction:: boolean

.. autofunction:: size

.. autofunction:: serial

.. autofunction:: duration
