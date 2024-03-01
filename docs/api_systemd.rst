===============
nobodd.systemd
===============

.. module:: nobodd.systemd

This module contains a singleton class intended for communication with the
:manpage:`systemd(1)` service manager. It includes facilities for running a
service as ``Type=notify`` where the service can actively communicate to
systemd that it is ready to handle requests, is reloading its configuration, is
shutting down, or that it needs more time to handle certain operations.

It also includes methods to ping the systemd watchdog, and to retrieve
file-descriptors stored on behalf of the service (or provided as part of
socket-activation).

Systemd Class
=============

.. autoclass:: Systemd

.. autofunction:: get_systemd
