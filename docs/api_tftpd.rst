.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2023-2024 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2023-2024 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

=============
nobodd.tftpd
=============

.. module:: nobodd.tftpd

Defines several classes for the purposes of constructing TFTP servers. The most
useful are :class:`TFTPBaseHandler` and :class:`TFTPBaseServer` which are
abstract base classes for the construction of a TFTP server with an arbitrary
source of files (these are used by nobodd's :mod:`~nobodd.main` module). In
addition, :class:`TFTPSimplerHandler` and :class:`TFTPSimplerServer` are
provided as a trivial example implementation of a straight-forward TFTP file
server.

For example, to start a TFTP server which will serve files from the current
directory on (unprivileged) port 1069:

.. code-block:: pycon

    >>> from nobodd.tftpd import SimpleTFTPServer
    >>> server = SimpleTFTPServer(('0.0.0.0', 1069), '.')
    >>> server.serve_forever()


Handler Classes
===============

.. autoclass:: TFTPBaseHandler

.. autoclass:: SimpleTFTPHandler


Server Classes
==============

.. autoclass:: TFTPBaseServer

.. autoclass:: SimpleTFTPServer


Command Line Use
================

Just as :mod:`http.server` can be invoked from the command line as a standalone
server using the interpreter's :option:`-m` option, so :mod:`nobodd.tftpd` can
too. To serve the current directory as a TFTP server::

    python -m nobodd.tftpd

The server listens to port 6969 by default. This is not the registered port 69
of TFTP, but as that port requires root privileges by default on UNIX
platforms, a safer default was selected (the security provenance of this code
is largely unknown, and certainly untested at higher privilege levels). The
default port can be overridden by passed the desired port number as an
argument::

    python -m nobodd.tftpd 1069

By default, the server binds to all interfaces. The option ``-b/--bind``
specifies an address to which it should bind instead. Both IPv4 and IPv6
addresses are supported. For example, the following command causes the server
to bind to localhost only::

    python -m nobodd.tftpd --bind 127.0.0.1

By default, the server uses the current directory. The option
``-d/--directory`` specifies a directory from which it should serve files
instead. For example::

    python -m nobodd.tftpd --directory /tmp/


Internal Classes and Exceptions
===============================

The following classes and exceptions are entirely for internal use and should
never be needed (directly) by applications.

.. autoclass:: TFTPClientState

.. autoclass:: TFTPHandler

.. autoclass:: TFTPSubHandler

.. autoclass:: TFTPSubServer

.. autoclass:: TFTPSubServers

.. autoexception:: TransferDone

.. autoexception:: AlreadyAcknowledged

.. autoexception:: BadOptions
