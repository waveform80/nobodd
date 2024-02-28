======
nobodd
======

nobodd is a confusingly named, but simple TFTP server intended for net-booting
Raspberry Pis directly from OS images without having to loop-back mount or
otherwise re-write those images. An initial loop-back mount is usually required
to customize the boot-sequence in an OS image (to point it at the correct root
device on the network) but the loop-back mount is not required thereafter.


Usage
=====

If you have an appropriately customized OS image already placed in a file
(``ubuntu.img``), and the serial number of the Pi in question (``1234ABCD``)
then serving it as simple as:

.. code-block:: console

    $ sudo nobodd-tftpd --board 1234ABCD,ubuntu.img

This defaults to read the first partition from the file, and pretends (to TFTP
clients) that the contents of the first partition appears under the
``1234ABCD/`` directory. Hence a TFTP request for ``1234ABCD/cmdline.txt`` will
serve the ``cmdline.txt`` file from the first partition contained in
``ubuntu.img``.

The service either needs to run from root (because the default TFTP port is the
privileged port 69), or can be run as a systemd socket-activated service, in
which case systemd will provide the initial socket and the service can run
without any special privileges.

The mapping of Pi serial numbers to OS image files can also be placed in a
configuration file under ``/etc/nobodd.conf`` (or several fallback locations).


Useful Links
============

* `Source code`_ on GitHub
* `Issues`_ on GitHub
* `Documentation`_ on ReadTheDocs

.. _Source code: https://github.com/waveform80/nobodd
.. _Issues: https://github.com/waveform80/nobodd/issues
.. _Documentation: https://nobodd.readthedocs.io/
