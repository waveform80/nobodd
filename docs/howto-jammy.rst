.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2024 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2024 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0


.. Once ubuntu-image works reliably, this should be re-written to just
.. "generate your custom Ubuntu image, manually seeding nbd-client and
.. modules-extra with this handy yaml!"

===========================
How to netboot Ubuntu 22.04
===========================

The Ubuntu 22.04 (jammy) images are not compatible with NBD boot out of the box
as they lack the ``nbd-client`` package in their seed. However, you can modify
the image to make it compatible.


On the Pi
=========

Fire up `rpi-imager`_ and flash Ubuntu 22.04.4 server onto an SD card, then
boot that SD card on your Pi (the model does not matter provided it can boot
the image).

.. warning::

    Do *not* be tempted to upgrade packages at this point. Specifically, the
    kernel package must *not* be upgraded yet.

Install the ``linux-modules-extra-raspi`` package for the currently running
kernel version, and the ``nbd-client`` package.

.. code-block:: console

    $ sudo apt install linux-modules-extra-$(uname -r) nbd-client

On Ubuntu versions prior to 24.04, the ``nbd`` kernel module was moved out of
the default ``linux-modules-raspi`` package for efficiency. We specifically
need the version matching the running kernel version because installing this
package will regenerate the initramfs (``initrd.img``). We'll be copying that
regenerated file into the image we're going to netboot and it *must* match the
kernel version in that image. This is why it was important not to upgrade any
packages after the first boot.

We also need to install the NBD client package to add the ``nbd-client``
executable to the initramfs, along with some scripts to call it if the kernel
command line specifies an NBD device as root:

We copy the regenerated ``initrd.img`` to the server, and shut down the Pi.
Adjust the ``ubuntu@server`` reference below to fit your user on your server.

.. code-block:: console

    $ scp -q /boot/firmware/initrd.img ubuntu@server:
    $ sudo poweroff


On the Server
=============

Download the same OS image to your server, verify its content, unpack it, and
rename it to something more reasonable.

.. code-block:: console

    $ wget http://cdimage.ubuntu.com/releases/22.04.4/release/ubuntu-22.04.4-preinstalled-server-arm64+raspi.img.xz
     ...
    $ wget http://cdimage.ubuntu.com/releases/22.04.4/release/SHA256SUMS
     ...
    $ sha256sum --check --ignore-missing SHA256SUMS
    ubuntu-22.04.4-preinstalled-server-arm64+raspi.img.xz: OK
    $ rm SHA256SUMS
    $ mv ubuntu-22.04.4-preinstalled-server-arm64+raspi.img jammy.img

Next we need to create a cloud-init configuration which will perform the same
steps we performed earlier on the first boot of our fresh image, namely to
install ``nbd-client`` and ``linux-modules-extra-raspi``, alongside the usual
user configuration.

.. code-block:: console

    $ cat << EOF > user-data
    #cloud-config

    chpasswd:
      expire: true
      users:
      - name: ubuntu
        password: ubuntu
        type: text

    ssh_pwauth: false

    package_update: true
    packages:
    - nbd-client
    - linux-modules-extra-raspi
    EOF

See the `cloud-init documentation`_, a `this series of blog posts
<waldorf-cloud-init_>`_ for more ideas on what can be done with the
:file:`user-data` file.


Preparing the Image
===================

When preparing our image with :program:`nobodd-prep` we must remember to copy
in our ``user-data`` and ``initrd.img`` files, overwriting the ones on the boot
partition.

.. code-block:: console

    $ nobodd-prep --size 16GB --copy initrd.img --copy user-data jammy.img

At this point you should have a variant of the Ubuntu 22.04 image that is
capable of being netbooted over NBD.

.. _rpi-imager: https://www.raspberrypi.com/software/
.. _cloud-init documentation: https://cloudinit.readthedocs.io/
.. _waldorf-cloud-init: https://waldorf.waveform.org.uk/tag/cloud-init.html
