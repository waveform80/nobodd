.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2024 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2024 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

=================
Netboot on the Pi
=================

In order to understand nobodd, it is useful to understand the netboot procedure
on the Raspberry Pi in general. At a high level, it consists of three phases
which we'll cover in the following sections.


DHCP
====

The first phase is quite simply a fairly typical `DHCP` phase, in which the
bootloader attempts to obtain an IPv4 address from the local :abbr:`DHCP
(Dynamic Host Configuration Protocol)` server. On the Pi 4 (and later models),
the address obtained can be seen on the boot diagnostics screen. Near the top
the line starting with "net:" indicates the current network status. Initially
this will read::

    net: down ip: 0.0.0.0 sn: 0.0.0.0 gw: 0.0.0.0

Shortly before attempting netboot, this line should change to something like
the following::

    net: up ip: 192.168.1.137 sn: 255.255.255.0 gw: 192.168.1.1

This indicates that the Pi has obtained the address "192.168.1.137" on a class
D subnet ("192.168.1.0/24" in `CIDR`_ form), and knows the local network
gateway is at "192.168.1.1".

The bootloader also inspects certain DHCP options to locate the `TFTP`_ server
for the next phase. Specifically:

* DHCP option 66 (TFTP server) can specify the address directly

* If DHCP option 43 (vendor options) specifies PXE string "Raspberry Pi Boot"
  [#pxe_id]_ then option 54 (server identifier) will be used

* On the Pi 4 (and later), the EEPROM can override both of these with the
  `TFTP_IP`_ option

With the network configured, and the TFTP server address obtained, we move onto
the TFTP phase...


TFTP
====

.. TODO Updated bootcode.bin on earlier models? Test on the 2+3

The bootloader's `TFTP`_ client first attempts to locate the :file:`config.txt`
file that will configure the bootloader throughout the rest of the procedure.
By default, it looks for this in a directory named after the Pi's serial
number. On the Pi 4 and later models, the EEPROM configuration can override
this behaviour with the `TFTP_PREFIX`_ option, but we will only cover the
default behaviour here.

All subsequent files will be requested from within this serial number directory
prefix [#no-prefix]_. Hence, when we say the bootloader requests
:file:`SERIAL/vmlinuz`, we mean it requests the file :file:`vmlinuz` from
within the virtual directory named after the Pi's serial number
[#long-serial]_.

Once :file:`SERIAL/config.txt` is loaded, the bootloader parses it to discover
the name of the tertiary bootloader to load [#pi5-eeprom]_, and requests
:file:`SERIAL/start.elf` or :file:`SERIAL/start4.elf` (depending on the model)
and the corresponding fix-up file (:file:`SERIAL/fixup.dat` or
:file:`SERIAL/fixup4.dat` respectively).

The bootloader now executes the tertiary "start.elf" bootloader which
re-requests :file:`SERIAL/config.txt`. This is re-parsed [#sections]_ and the
name of the base device-tree, kernel, kernel command line, (optional)
initramfs, and any (optional) device-tree overlays are determined. These are
then requested over TFTP, placed in RAM, and finally the bootloader hands over
control to the kernel.


TFTP Extensions
---------------

A brief aside on the subject of :abbr:`TFTP (Trivial File Transfer Protocol)`
extensions (as defined in :rfc:`2347`). The basic TFTP protocol is extremely
simple (as the name would suggest) and also rather inefficient, being limited
to 512-byte blocks, in-order, synchronously (each block must be acknowledged
before another can be sent), with no retry mechanism. Various extensions have
been proposed to the protocol over the years, including those in :rfc:`2347`,
:rfc:`2348`, and :rfc:`7440`.

The Pi bootloader implements *some* of these extensions. Specifically, it uses
the "blocksize" extension (:rfc:`2347`) to negotiate a larger size of block to
transfer, and the "tsize" extension (:rfc:`2348`) to attempt to determine the
size of a transfer prior to it beginning.

However, its use of "tsize" is slightly unusual in that, when it finds the
server supports it, it frequently starts a transfer with "tsize=0" (requesting
the size of the file), but when the server responds with, for example,
"tsize=1234" in the OACK packet (indicating the file to be transferred is 1234
bytes large), the bootloader then terminates the transfer and restarts it. My
best guess is that it allocates the RAM for the transfer after the termination,
then restarts it (though why it does this is a bit of a mystery as it could
allocate the space and continue the transfer, since the OACK packet doesn't
contain any of the file data itself).

Sadly, the "windowsize" extension (:rfc:`7440`) is not yet implemented which
means the Pi's netboot, up to the kernel, is quite slow compared to other
methods.


Kernel
======

The kernel is now running with the configured command line, and (optionally)
the address of an initial ramdisk (initramfs) as the root file-system. The
initramfs is expected to contain the relevant kernel modules, and client
binaries to talk to whatever network server will provide the root file-system.

Traditionally on the Raspberry Pi, this has meant `NFS`_. However, it may also
be `NBD`_ (as served by :manpage:`nbd-server(1)`) or `iSCSI`_ (as served by
:manpage:`iscsid(8)`). Typically, the ``init`` process loaded from the kernel's
initramfs will dissect the kernel's command line to determine the location of
the root file-system, and mount it using the appropriate utilities.

In the case of :manpage:`nbd-server(1)` the following items in the kernel
command line are crucial:

* ``ip=dhcp`` tells the kernel that it should request an IP address via DHCP
  (the Pi's bootloader cannot pass network state to the kernel, so this must be
  re-done)

* ``nbdroot=HOST/SHARE`` tells the kernel that it should open "SHARE" on the
  NBD server at HOST. This will form the block device ``/dev/nbd0``

* ``root=/dev/nbd0p2`` tells the kernel that the root file-system is on the
  second partition of the block device


.. _DHCP: https://en.wikipedia.org/wiki/Dynamic_Host_Configuration_Protocol
.. _CIDR: https://en.wikipedia.org/wiki/Classless_Inter-Domain_Routing
.. _TFTP: https://en.wikipedia.org/wiki/Trivial_File_Transfer_Protocol
.. _TFTP_IP: https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#TFTP_IP
.. _TFTP_PREFIX: https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#TFTP_IP
.. _NFS: https://en.wikipedia.org/wiki/Network_File_System
.. _NBD: https://en.wikipedia.org/wiki/Network_block_device
.. _iSCSI: https://en.wikipedia.org/wiki/ISCSI

.. [#pxe_id] In early versions of the Raspberry Pi bootloader, the string
   needed to include three trailing spaces, i.e. ``"Raspberry Pi Boot   "``.
   Later versions of the bootloader perform a sub-string match.

.. [#no-prefix] If "config.txt" is not found in the serial-number directory,
   the bootloader will attempt to load "config.txt" with no directory prefix.
   If this succeeds, all subsequent requests will have no serial-number
   directory prefix.

.. [#long-serial] Some Pi serial numbers begin "10000000". This prefix is
   ignored for the purposes of constructing the serial-number directory prefix.
   For example, if the serial number is "10000000abcd1234", the
   :file:`config.txt` file would be requested as :file:`abcd1234/config.txt`.

.. [#pi5-eeprom] This does not happen on the Pi 5, which always loads the
   tertiary bootloader from its (larger) EEPROM. On all prior models, the
   tertiary bootloader (start*.elf) loads from the boot medium.

.. [#sections] The tertiary bootloader operates on all ``[sections]`` in the
   :file:`config.txt`. The secondary bootloader (:file:`bootcode.bin`) only
   operates on some of these and doesn't comprehend the full syntax that the
   tertiary bootloader does (for instance, the secondary bootloader won't
   handle includes).
