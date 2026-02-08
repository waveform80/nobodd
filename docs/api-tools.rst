.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2023-2024 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2023-2024 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

===============
nobodd.tools
===============

.. module:: nobodd.tools

This module houses a series of miscellaneous functions which did not fit
particularly well anywhere else and are needed across a variety of modules.
They should never be needed by developers using nobodd as an application or a
library, but are documented in case they are useful.


.. autofunction:: labels

.. autofunction:: formats

.. autofunction:: get_best_family

.. autofunction:: format_address

.. autofunction:: decode_timestamp

.. autofunction:: encode_timestamp

.. autofunction:: any_match

.. autofunction:: exclude

.. autofunction:: open_file

.. autoclass:: BufferedTranscoder

.. autoclass:: FrozenDict
