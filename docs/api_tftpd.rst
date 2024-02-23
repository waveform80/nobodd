.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2023 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2023 Canonical Ltd.
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
