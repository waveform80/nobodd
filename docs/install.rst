.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2023-2024 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2023-2024 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

============
Installation
============

nobodd is distributed in several formats. The following sections detail
installation on a variety of platforms.


Ubuntu PPA
==========

For Ubuntu, it may be simplest to install from the `author's PPA`_ as follows:

.. code-block:: console

    $ sudo add-apt-repository ppa:waveform/nobodd
    $ sudo apt install nobodd

If you wish to remove nobodd:

.. code-block:: console

    $ sudo apt remove nobodd

The deb-packaging includes a full man-page, and systemd service definitions.


Other Platforms
===============

If your platform is *not* covered by one of the sections above, nobodd is
available from PyPI and can therefore be installed with the Python setuptools
"pip" tool:

.. code-block:: console

    $ pip install nobodd

On some platforms you may need to use a Python 3 specific alias of pip:

.. code-block:: console

    $ pip3 install nobodd

If you do not have either of these tools available, please install the Python
`setuptools`_ package first.

You can upgrade nobodd via pip:

.. code-block:: console

    $ pip install --upgrade nobodd

And removal can be performed as follows:

.. code-block:: console

    $ pip uninstall nobodd


.. _author's PPA: https://launchpad.net/~waveform/+archive/ubuntu/nobodd
.. _setuptools: https://pypi.python.org/pypi/setuptools/
