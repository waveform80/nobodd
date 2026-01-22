.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2023-2024 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2023-2024 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

=============
API Reference
=============

In additional to being a service, nobodd can also be used as an API from Python
to access disk images, determining their partitioning style, enumerating the
available partitions, and manipulating FAT file-systems (either from within a
disk image, or just standalone). It can also be used as the basis of a generic
TFTP service.

The following sections list the modules by their topic.

Disk Images
===========

The :class:`nobodd.disk.DiskImage` class is the primary entry-point for dealing
with disk images.

.. toctree::
    :maxdepth: 1

    api_disk
    api_gpt
    api_mbr


FAT Filesystem
==============

The :class:`nobodd.fs.FatFileSystem` class is the primary entry-point for
handling FAT file-systems.

.. toctree::
    :maxdepth: 1

    api_fs
    api_fat
    api_path


TFTP Service
============

The :class:`nobodd.tftpd.TFTPBaseServer` and
:class:`nobodd.tftpd.TFTPBaseHandler` are two classes which may be customized
to produce a TFTP server. Two example classes are included,
:class:`nobodd.tftpd.SimpleTFTPServer` and
:class:`nobodd.tftpd.SimpleTFTPHandler` which serve files directly from a
specified path.

.. toctree::
    :maxdepth: 1

    api_tftpd
    api_tftp
    api_netascii


Command line applications
=========================

The :mod:`nobodd.server` module contains the primary classes,
:class:`~nobodd.server.BootServer` and :class:`~nobodd.server.BootHandler`
which define a TFTP server (:program:`nobodd-tftpd`) that reads files from FAT
file-systems contained in OS images. The :mod:`nobodd.prep` module contains the
implementation of the :program:`nobodd-prep` command, which customizes images
prior to first net boot.

The :mod:`nobodd.config` module provides configuration parsing facilities to
these applications.

.. toctree::
    :maxdepth: 1

    api_server
    api_prep
    api_config
    api_systemd


Miscellaneous
=============

The :mod:`nobodd.tools` module contains a variety of utility functions that
either cross boundaries in the system or are entirely generic. Meanwhile,
:mod:`nobodd.locks` provides an SREW (shared-read, exclusive-write) lock
implementation with re-entrancy.

.. toctree::
    :maxdepth: 1

    api_tools
    api_locks
