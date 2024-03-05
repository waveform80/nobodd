.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2024 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2024 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

=================
Systemd Examples
=================

The example units and configuration file in this directory configure
nobodd-tftpd to be run as a socket-activated service by systemd. They are
suggested for use by distribution packagers.

The configuration specifies ``listen=systemd``, and the
:file:`nobodd-tftpd.service` unit has a corresponding
:file:`nobodd-tftpd.socket` unit to define the UDP socket on port 69. This
method is chosen rather than forcing the config via ``--listen systemd`` on the
command line to permit the system administrator to disable the socket and
easily re-configure the server to use its own socket via the configuration file
rather than having to override the service file.
