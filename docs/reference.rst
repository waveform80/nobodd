.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2023-2026 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2023-2026 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

=========
Reference
=========

The following sections provide reference material to the command line utilities
provided in nobodd, and the Python-based API.


Command line
============

The following chapters document the command line utilities included in nobodd:

.. toctree::
    :maxdepth: 1

    cli-prep
    cli-server
    cli-sh


API reference
=============

In addition to being a service and command-line tool, nobodd can also be used
as an API from Python to access disk images, determining their partitioning
style, enumerating the available partitions, and manipulating FAT file-systems
(either from within a disk image, or just standalone). It can also be used as
the basis of a generic TFTP service.

The following sections list the modules by their topic.


Disk images
-----------

The :class:`nobodd.disk.DiskImage` class is the primary entry-point for dealing
with disk images.

.. toctree::
    :maxdepth: 1

    api-disk
    api-gpt
    api-mbr


FAT filesystem
--------------

The :class:`nobodd.fs.FatFileSystem` class is the primary entry-point for
handling FAT file-systems.

.. toctree::
    :maxdepth: 1

    api-fs
    api-fat
    api-path


TFTP service
------------

The :class:`nobodd.tftpd.TFTPBaseServer` and
:class:`nobodd.tftpd.TFTPBaseHandler` are two classes which may be customized
to produce a TFTP server. Two example classes are included,
:class:`nobodd.tftpd.SimpleTFTPServer` and
:class:`nobodd.tftpd.SimpleTFTPHandler` which serve files directly from a
specified path.

.. toctree::
    :maxdepth: 1

    api-tftpd
    api-tftp
    api-netascii


Command line applications
-------------------------

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

    api-server
    api-prep
    api-sh


Support modules
---------------

The :mod:`nobodd.tools` module contains a variety of utility functions that
either cross boundaries in the system or are entirely generic. Meanwhile,
:mod:`nobodd.locks` provides an SREW (shared-read, exclusive-write) lock
implementation with re-entrancy.

.. toctree::
    :maxdepth: 1

    api-tools
    api-locks
    api-config
    api-systemd
    api-transfer
