.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2023-2024 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2023-2024 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

==================
Changelog
==================

.. currentmodule:: nobodd


Release 0.4 (2024-03-07)
========================

* Use absolute paths for output of nbd-server and tftpd server configurations
* Include missing ``#cloud-config`` header in the tutorial


Release 0.3 (2024-03-06)
========================

* Fix configuration reload when inheriting the TFTP socket from a service
  manager (`#8`_)

.. _#8: https://github.com/waveform80/nobodd/issues/8


Prototype 0.2 (unreleased)
==========================

* Add inheritance of the TFTP socket (`#3`_)

.. _#3: https://github.com/waveform80/nobodd/issues/3


Prototype 0.1 (unreleased)
==========================

* Initial tag
