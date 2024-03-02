.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2024 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2024 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

.. include:: subst.rst

=============
nobodd-tftpd
=============

A read-only TFTP server capable of reading FAT boot partitions from within
image files or devices. Intended to be paired with a block-device service (e.g.
NBD) for netbooting Raspberry Pis.


Synopsis
========

.. code-block:: text

    usage: nobodd-tftpd [-h] [--version] [--listen ADDR] [--port PORT]
                        [--board SERIAL,FILENAME[,PART[,IP]]]


Options
=======

.. program:: nobodd-tftpd

.. option:: -h, --help

    show the help message and exit

.. option:: --version

    show program's version number and exit

.. option:: --board SERIAL,FILENAME[,PART[,IP]]

    can be specified multiple times to define boards which are to be served
    boot images over TFTP; if PART is omitted the default is 1; if IP is
    omitted the IP address will not be checked

.. option:: --listen ADDR

    the address on which to listen for connections (default: "::" for all
    addresses)

.. option:: --port PORT

    the port on which to listen for connections (default: "tftp" which is port
    69)


Configuration
=============

:program:`nobodd-tftpd` can be configured via the command line, or from several
configuration files. These are structured as INI-style files with bracketed
``[sections]`` containing ``key=value`` lines, and optionally #-prefixed
comments. The configuration files which are read, and the order they are
consulted is as follows:

1. :file:`/etc/nobodd/nobodd.conf`

2. :file:`/usr/local/etc/nobodd/nobodd.conf`

3. :file:`$XDG_CONFIG_HOME/nobodd/nobodd.conf` (where ``$XDG_CONFIG_HOME``
   defaults to :file:`~/.config` if unset)

Later files override settings from files earlier in this order.

The configuration file may contain a ``[tftp]`` section which may contain the
following values:

listen
    This is equivalent to the :option:`--listen` parameter and specifies the
    address(es) on which the server will listen for incoming TFTP connections.

port
    This is equivalent to the :option:`--port` parameter and specifies the UDP
    port on which the server will listen for incoming TFTP connections. Please
    note that only the *initial* TFTP packet will arrive on this port. Each
    "connection" is allocated its own `ephemeral port`_ on the server and all
    subsequent packets will use this ephemeral port.

includedir
    If this is specified, it provides the name of a directory which will be
    scanned for files matching the pattern :file:`*.conf`. Any files found
    matching will be read as additional configuration files, in sorted filename
    order.

For example:

.. code-block:: ini

    [tftp]
    listen = 192.168.0.0/16
    port = tftp
    includedir = /etc/nobodd/conf.d

For each image the TFTP server is expected to serve to a Raspberry Pi, a
``[board:SERIAL]`` section should be defined. Here, "SERIAL" should be replaced
by the serial number of the Raspberry Pi. The serial number can be found in the
output of ``cat /proc/cpuinfo`` at runtime. For example:

.. code-block:: console

    $ grep ^Serial /proc/cpuinfo
    Serial          : 100000001234abcd

If the serial number starts with 10000000 (as in the example above), exclude
the initial one and all leading zeros. So the above Pi has a serial number of
1234abcd (in hexidecimal). Within the section the following values are valid:

image
    Specifies the full path to the operating system image to serve to the
    specified Pi, presumably prepared with :program:`nobodd-prep`.

partition
    Optionally specifies the number of the boot partition. If this is not
    specified it defaults to 1.

ip
    Optionally limits serving any files from this image unless the IP address
    of the client matches. If this is not specified, any IP address may
    retrieve files from this share.

For example:

.. code-block:: ini

    [board:1234abcd]
    image = /srv/images/ubuntu-24.04-server.img
    partition = 1
    ip = 192.168.0.5

In practice, what this means is that requests from a client with the IP address
"192.168.0.5", for files under the path "1234abcd/", will be served from the
FAT file-system on partition 1 of the image stored at
:file:`/srv/images/ubuntu-24.04-server.img`.

Such definitions can be produced by :program:`nobodd-prep` when it is provided
with the :option:`nobodd-prep --serial` option.

Boards may also be defined on the command-line with the :option:`--board`
option. These definitions will augment (and override, where the serial number
is identical) those definitions provided by the configuration files.


Systemd/Inetd Usage
===================

The server may inherit its listening socket from a managing process. In the
case of :manpage:`inetd(8)` where the listening socket is traditionally passed
as stdin (fd 0), pass "stdin" as the value of :option:`--listen` (or the
``listen`` option within the ``[tftp]`` section of the configuration file).

In the case of :manpage:`systemd(1)`, where the listening socket(s) are passed
via the environment, specify "systemd" as the value of :option:`--listen` (or
the ``listen`` option within the ``[tftp]`` section of the configuration file)
and the service will expect to find a single socket passed in
:envvar:`LISTEN_FDS`. This will happen implicitly if the service is declared as
socket-activated. However, the service must *not* use ``Accept=yes`` as the
TFTP protocol is connection-less. The example units provided in the source code
demonstrate using socket-activation with the server.

In both cases, the service manager sets the port that the service will listen
on, so the :option:`--port` option (and the ``port`` option in the ``[tftp]``
section of the configuration file) is silently ignored.


See Also
========

.. only:: not man

    :doc:`cli_prep`, :manpage:`nbd-server(1)`

.. only:: man

    :manpage:`nobodd-prep(1)`, :manpage:`nbd-server(1)`


Bugs
====

|bug-link|


.. _ephemeral port: https://en.wikipedia.org/wiki/Ephemeral_port
