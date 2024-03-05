.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2023-2024 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2023-2024 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

==============
nobodd.server
==============

.. module:: nobodd.server

This module contains the server and handler classes which make up the main
:program:`nobodd-tftpd` application, as well as the entry point for the
application itself.


Handler Classes
===============

.. autoclass:: BootHandler


Server Classes
==============

.. autoclass:: BootServer


Application Functions
=====================

.. autofunction:: main

.. autofunction:: request_loop

.. autofunction:: get_parser


Exceptions
==========

.. autoexception:: ReloadRequest

.. autoexception:: TerminateRequest
