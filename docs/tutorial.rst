========
Tutorial
========

nobodd is a confusingly named, but simple TFTP server intended for net-booting
Raspberry Pis directly from OS images without having to loop-back mount or
otherwise re-write those images. An initial loop-back mount is usually required
to customize the boot-sequence in an OS image (to point it at the correct root
device on the network) but the loop-back mount is not required thereafter.

The following tutorial assumes you have:

* A freshly installed Ubuntu 22.04 (jammy) server on which you have root
  authority, and which has at least 20GB of available storage

* A Raspberry Pi model 4 or 5

* A micro-SD card at least 8GB in size

* Ethernet networking connecting the two machines (specifically, netboot will
  *not* operate over wifi)


Raspberry Pi
============


Ubuntu Server
=============

First, on the Ubuntu server, install ``nbd-server`` and ``dnsmasq``:

.. code-block:: console

    # apt install nbd-server dnsmasq

Next, configure ``dnsmasq`` to proxy TFTP boot requests on the network. Adjust
the ``192.168.255.255`` network mask for your local LAN configuration:

.. code-block:: console

    # echo "dhcp-range=192.168.255.255,proxy" >> /etc/dnsmasq.conf
    # systemctl restart dnsmasq.service

Next, configure ``nbd-server`` to serve your local network. Again, adjust the
network mask for your local LAN configuration, but note this time it is in IPv6
notation (add any relevant IPv6 networks here too):

.. code-block:: console

    # cat << EOF > /etc/nbd-server/config
    [generic]
        user = nbd
        group = nbd
        includedir = /etc/nbd-server/conf.d
        allowlist = true
    EOF
    # cat << EOF > /etc/nbd-server/allow
    ::ffff:127.0.0.0/104
    ::ffff:192.168.0.0/112
    fe80::/64
    EOF

Now we add an entry to serve the OS image we're going to create next:

.. code-block:: console

    cat << EOF > /etc/

First you will need an OS image. Here, we download the Ubuntu 23.10 (mantic)
server image for the Raspberry Pi, unpack it, loop-back mount it and customize
the kernel command line to point at our NBD server:

.. code-block:: console

    $ wget http://cdimage.ubuntu.com/releases/mantic/release/ubuntu-23.10-preinstalled-server-arm64+raspi.img.xz
    $ unxz ubuntu-23.10-preinstalled-server-arm64+raspi.img.xz
    $ sudo losetup --find --show --partscan ubuntu-23.10-preinstalled-server-arm64+raspi.img
    /dev/loop66
    $ mkdir boot
    $ sudo mount /dev/loop66p1 boot/
    $ # TODO fiddle with cmdline.txt
    $ sudo umount boot/
    $ sudo losetup -d /dev/loop66

Now we expand the image to the size of storage we want to present to the
Raspberry Pi (in this case we're emulating a 16GB SD card):

.. code-block:: console

    $ fallocate -L 16G ubuntu-23.10-preinstalled-server-arm64+raspi.img


First Boot
==========


Troubleshooting
===============
