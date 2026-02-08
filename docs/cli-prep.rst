.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2024-2026 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2024-2026 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

.. include:: subst.rst

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
                       [-C PATH] [-R PATH] image


Options
=======

.. program:: nobodd-prep

.. option:: image

    The target image to customize

.. option:: -h, --help

    Show the help message and exit

.. option:: --version

    Show program's version number and exit

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

.. option:: -R PATH, --remove PATH

    Delete the specified file or directory within the boot partition. This may
    be given multiple times to specify multiple items to delete

.. option:: --serial HEX

    Defines the serial number of the Raspberry Pi that will be served this
    image. When this option is given, a board configuration compatible with
    :program:`nobodd-tftpd` may be output with :option:`--tftpd-conf`

.. option:: --tftpd-conf FILE

    If specified, write a board configuration compatible with
    :program:`nobodd-tftpd` to the specified file; requires :option:`--serial`
    to be given. If "-" is given, output is written to stdout.

.. option:: --nbd-conf FILE

    If specified, write a share configuration compatible with
    :manpage:`nbd-server(1)` to the specified file. If "-" is given, output is
    written to stdout.


Usage
=====

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
    $ fdisk -l ubuntu-24.04-server.img
    Disk ubuntu-24.04-server.img: 3.47 GiB, 3727687680 bytes, 7280640 sectors
    Units: sectors of 1 * 512 = 512 bytes
    Sector size (logical/physical): 512 bytes / 512 bytes
    I/O size (minimum/optimal): 512 bytes / 512 bytes
    Disklabel type: dos
    Disk identifier: 0x1634ec00

    Device                   Boot   Start     End Sectors  Size Id Type
    ubuntu-24.04-server.img1 *       2048 1050623 1048576  512M  c W95 FAT32 (LBA)
    ubuntu-24.04-server.img2      1050624 7247259 6196636    3G 83 Linux
    $ mkdir mnt
    $ sudo mount -o loop,offset=$((2048*512)),sizelimit=$((1048576*512)) ubuntu-24.04-server.img mnt/
    [sudo] Password:
    $ cat mnt/cmdline.txt
    console=serial0,115200 multipath=off dwc_otg.lpm_enable=0 console=tty1 root=LABEL=writable rootfstype=ext4 rootwait fixrtc
    $ sudo umount mnt/
    $ nobodd-prep --size 16GB ubuntu-24.04-server.img
    $ ls -l ubuntu-24.04-server.img --nbd-host myserver --nbd-name ubuntu
    -rw-rw-r-- 1 dave dave 17179869184 Feb 27 13:11 ubuntu-24.04-server.img
    $ sudo mount -o loop,offset=$((2048*512)),sizelimit=$((1048576*512)) ubuntu-24.04-server.img mnt/
    [sudo] Password:
    $ cat mnt/cmdline.txt
    ip=dhcp nbdroot=myserver/ubuntu root=/dev/nbd0p2 console=serial0,115200 multipath=off dwc_otg.lpm_enable=0 console=tty1 rootfstype=ext4 rootwait fixrtc
    $ sudo umount mnt/

Note, the only reason we are listing partitions and mounting the boot partition
above is to demonstrate the change to the kernel command line in
:file:`cmdline.txt`. Ordinarily, usage of :program:`nobodd-prep` is as simple
as:

.. code-block:: console

    $ unxz ubuntu-24.04-server.img.xz
    $ nobodd-prep --size 16GB ubuntu-24.04-server.img

Typically :program:`nobodd-prep` will detect the boot and root partitions of
the image automatically. The boot partition is defined as the first partition
that has a FAT `partition type`_ (on `MBR-partitioned`_ images), or `Basic
Data`_ or `EFI System`_ partition type (on `GPT-partitioned`_ images), which
contains a valid FAT file-system (the script tries to determine the FAT-type of
the contained file-system, and only counts those partitions on which it can
determine a valid FAT-type).

The root partition is the exact opposite; it is defined as the first partition
that *doesn't* have a FAT `partition type`_ (on `MBR-partitioned`_ images), or
`Basic Data`_ or `EFI System`_ partition type (on `GPT-partitioned`_ images),
which contains something *other than* a valid FAT file-system (again, the
script tries to determine the FAT-type of the contained file-system, and only
counts those partitions on which it *cannot* determine a valid FAT-type).

There may be images for which these simplistic definitions do not work. For
example, images derived from a `NOOBS/PINN`_ install may well have several boot
partitions for different installed OS'. In this case the boot or root partition
(or both) may be specified manually on the command line:

.. code-block:: console

    $ fdisk -l pinn-test.img
    Disk pinn-test.img: 29.72 GiB, 31914983424 bytes, 62333952 sectors
    Units: sectors of 1 * 512 = 512 bytes
    Sector size (logical/physical): 512 bytes / 512 bytes
    I/O size (minimum/optimal): 512 bytes / 512 bytes
    Disklabel type: dos
    Disk identifier: 0x2e779525

    Device          Boot    Start      End  Sectors  Size Id Type
    pinn-test.img1           8192   137215   129024   63M  e W95 FAT16 (LBA)
    pinn-test.img2         137216 62333951 62196736 29.7G  5 Extended
    pinn-test.img5         139264   204797    65534   32M 83 Linux
    pinn-test.img6         204800   464895   260096  127M  c W95 FAT32 (LBA)
    pinn-test.img7         466944  4661247  4194304    2G 83 Linux
    pinn-test.img8        4669440  5193727   524288  256M 83 Linux
    pinn-test.img9        5201920 34480125 29278206   14G 83 Linux
    pinn-test.img10      34480128 34998271   518144  253M  c W95 FAT32 (LBA)
    pinn-test.img11      35004416 62333951 27329536   13G 83 Linux
    $ nobodd-prep --boot-partition 10 --root-partition 11 pinn-test.img

:program:`nobodd-prep` also includes several facilities for customizing the
boot partition beyond re-writing the kernel's :file:`cmdline.txt`.
Specifically, the :option:`--remove` and :option:`--copy` options.

The :option:`--remove` option can be given multiple times, and tells
:program:`nobodd-prep` to remove the specified files or directories from the
boot partition. The :option:`--copy` option can also be given multiple times,
and tells :program:`nobodd-prep` to copy the specified files or directories
into the root of the boot partition. In both cases, directories that are
specified are removed or copied recursively.

The :option:`--copy` option is particularly useful for overwriting the
`cloud-init`_ seeds on the boot partition of Ubuntu Server images, in case you
want to provide an initial network configuration, user setup, or list of
packages to install on first boot:

.. code-block:: console

    $ cat user-data
    chpasswd:
      expire: true
      users:
      - name: ubuntu
        password: raspberry
        type: text

    ssh_pwauth: false

    package_update: true
    package_upgrade: true
    packages:
    - avahi-daemon
    $ nobodd-prep --copy user-data ubuntu-24.04-server.img

There is no need to :option:`--remove` files you wish to :option:`--copy`; the
latter option will overwrite where necessary. The exception to this is copying
directories; if you are copying a directory that already exists in the boot
partition, the new content will be merged with the existing content. Files
under the directory that share a name will be overwritten, files that do not
will be left in place. If you wish to replace the directory wholesale, specify
it with :option:`--remove` as well.

The ordering of options on the command line does *not* affect the order of
operations in the utility. The order of operations in :program:`nobodd-prep` is
strictly as follows:

1. Detect partitions, if necessary

2. Re-size the image, if necessary

3. Remove all items on the boot partition specified by :option:`--remove`

4. Copy all items specified by :option:`--copy` into the boot partition

5. Re-write the ``root=`` option in the :file:`cmdline.txt` file

This ordering is deliberate, firstly to ensure directories can be replaced (as
noted above), and secondly to ensure :file:`cmdline.txt` can be customized by
:option:`--copy` prior to the customization performed by the utility.


See Also
========

.. only:: not man

    :doc:`cli-sh`, :doc:`cli-server`, :manpage:`nbd-server(1)`

.. only:: man

    :manpage:`nobodd-sh(1)`, :manpage:`nobodd-tftpd(1)`, :manpage:`nbd-server(1)`


Bugs
====

|bug-link|


.. _partition type: https://en.wikipedia.org/wiki/Partition_type
.. _MBR-partitioned: https://en.wikipedia.org/wiki/Master_boot_record
.. _GPT-partitioned: https://en.wikipedia.org/wiki/GUID_Partition_Table
.. _Basic Data: https://en.wikipedia.org/wiki/Microsoft_basic_data_partition
.. _EFI System: https://en.wikipedia.org/wiki/EFI_system_partition
.. _NOOBS/PINN: https://github.com/procount/pinn
.. _cloud-init: https://cloudinit.readthedocs.io/en/latest/
