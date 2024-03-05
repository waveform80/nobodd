======
nobodd
======

nobodd is a confusingly named, but simple TFTP server intended for net-booting
Raspberry Pis directly from OS images without having to loop-back mount those
images. Even customization of an image for booting on a particular board is
handled without loop devices or mounts (making it possible to operate
completely unprivileged), via a read/write FAT implementation within the
``nobodd-prep`` tool.


Usage
=====

If you have an appropriately customized OS image already placed in a file
(``ubuntu.img``), and the serial number of the Pi in question (``1234ABCD``)
then serving it as simple as:

.. code-block:: console

    $ sudo nobodd-tftpd --board 1234ABCD,ubuntu.img

This defaults to reading the first partition from the file, and pretends (to
TFTP clients) that the contents of the first partition appears under the
``1234ABCD/`` directory. Hence a TFTP request for ``1234ABCD/cmdline.txt`` will
serve the ``cmdline.txt`` file from the first partition contained in
``ubuntu.img``.

The service either needs to run from root (because the default TFTP port is the
privileged port 69), or can be run as a **systemd** or **inetd**
socket-activated service, in which case the service manager will provide the
initial socket and the service can run without any special privileges.

The mapping of Pi serial numbers to OS image files can also be placed in a
configuration file under ``/etc/nobodd/conf.d``. A tool, ``nobodd-prep``, is
provided to both customize images for boot and generate basic configuration
files for ``nobodd-tftpd`` and ``nbd-server``.


Useful Links
============

* `Source code`_ on GitHub
* `Issues`_ on GitHub
* `Documentation`_ on ReadTheDocs

.. _Source code: https://github.com/waveform80/nobodd
.. _Issues: https://github.com/waveform80/nobodd/issues
.. _Documentation: https://nobodd.readthedocs.io/
