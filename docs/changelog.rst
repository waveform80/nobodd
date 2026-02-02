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


Release 0.5 (2026-02-??)
========================

* Added :attr:`~nobodd.fs.FatFileSystem.damaged` and
  :attr:`~nobodd.fs.FatFileSystem.dirty` properties to the
  :class:`~nobodd.fs.FatFileSystem` class (`#2`_)
* Added ``tz`` (timezone) parameter to the constructor of the
  :class:`~nobodd.fs.FatFileSystem` class (`#5`_)
* Added shared-read, exclusive-write lock covering all operations (low and
  high level) in the :class:`~nobodd.fs.FatFileSystem`,
  :class:`~nobodd.path.FatPath`, and associated classes (operation should now
  be thread-safe)
* Added :program:`nobodd-sh` command line application for manipulation of FAT
  partitions within images (`#9`_)
* Changed packging definitions from :file:`setup.cfg` to :file:`pyproject.toml`

.. _#2: https://github.com/waveform80/nobodd/issues/2
.. _#5: https://github.com/waveform80/nobodd/issues/5
.. _#9: https://github.com/waveform80/nobodd/issues/9


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
