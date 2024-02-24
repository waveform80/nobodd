.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2024 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2024 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

=============
nobodd-prep
=============

Customizes an OS image to prepare it for netbooting via TFTP. Specifically,
this expands the image to a specified size (the assumption being the image is a
copy of a minimally sized template image), then updates the kernel command line
on the boot partition to point to an NBD server.


Synopsis
========

.. code-block:: text

    usage: nobodd-prep [-h] [--version] [-s SIZE] [--nbd-host HOST]
                       [--nbd-name NAME] [--cmdline NAME]
                       [--boot-partition NUM] [--root-partition NUM]
                       [-C PATH] [-D PATH] image


Options
=======

.. program:: nobodd-prep

.. option:: image

    The target image to customize

.. option:: -h, --help

    show the help message and exit

.. option:: --version

    show program's version number and exit

.. option:: -s SIZE, --size SIZE

    The size to expand the image to; default: 16GB

.. option:: --nbd-host HOST

    The hostname of the nbd server to connect to for the root device; defaults
    to the local machine's FQDN

.. option:: --nbd-name NAME

    The name of the nbd share to use as the root device; defaults to the stem
    of the *image* name

.. option:: --cmdline NAME

    The name of the file containing the kernel command line on the boot
    partition; default: :file:`cmdline.txt`

.. option:: --boot-partition NUM

    Which partition is the boot partition within the image; default is the
    first FAT partition (identified by partition type) found in the image

.. option:: --root-partition NUM

    Which partition is the root partition within the image default is the first
    non-FAT partition (identified by partition type) found in the image

.. option:: -C PATH, --copy PATH

    Copy the specified file or directory into the boot partition. This may be
    given multiple times to specify multiple items to copy

.. option:: -D PATH, --delete PATH

    Delete the specified file or directory within the boot partition. This may
    be given multiple times to specify multiple items to delete


Examples
========

Typically :program:`nobodd-prep` is called with a base OS image. For example,
if :file:`ubuntu-24.04-server.img.xz` is the Ubuntu 24.04 Server for Raspberry
image, we would decompress it (we can only work on uncompressed images), use
the tool to expand it to a reasonable disk size (e.g. 16GB like an SD card),
and customize the kernel command line to look for the rootfs on our NBD server:

.. code-block:: console

    $ ls -l ubuntu-24.04-server.img.xz
    -rw-rw-r-- 1 dave dave 1189280360 Oct 12 00:44 ubuntu-24.04-server.img.xz
    $ unxz ubuntu-24.04-server.img.xz
    $ ls -l ubuntu-24.04-server.img
    -rw-rw-r-- 1 dave dave 3727687680 Oct 12 00:44 ubuntu-24.04-server.img
    $ nobodd-prep --size 16GB ubuntu-24.04-server.img
