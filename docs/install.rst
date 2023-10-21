============
Installation
============

nobody is distributed in several formats. The following sections detail
installation on a variety of platforms.


Ubuntu PPA
==========

For Ubuntu, it may be simplest to install from the `author's PPA`_ as follows:

.. code-block:: console

    $ sudo add-apt-repository ppa:waveform/nobody
    $ sudo apt install nobody

If you wish to remove nobody:

.. code-block:: console

    $ sudo apt remove nobody

The deb-packaging includes a full man-page, and systemd service definitions.


Other Platforms
===============

If your platform is *not* covered by one of the sections above, nobody is
available from PyPI and can therefore be installed with the Python setuptools
"pip" tool:

.. code-block:: console

    $ pip install nobody

On some platforms you may need to use a Python 3 specific alias of pip:

.. code-block:: console

    $ pip3 install nobody

If you do not have either of these tools available, please install the Python
`setuptools`_ package first.

You can upgrade nobody via pip:

.. code-block:: console

    $ pip install --upgrade nobody

And removal can be performed as follows:

.. code-block:: console

    $ pip uninstall nobody


.. _author's PPA: https://launchpad.net/~waveform/+archive/ubuntu/nobody
.. _setuptools: https://pypi.python.org/pypi/setuptools/
