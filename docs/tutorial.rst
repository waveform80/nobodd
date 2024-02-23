.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2023-2024 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2023-2024 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

========
Tutorial
========

nobodd is a confusingly named, but simple TFTP server intended for net-booting
Raspberry Pis directly from OS images without having to loop-back mount or
otherwise re-write those images. An initial loop-back mount is usually required
to customize the boot-sequence in an OS image (to point it at the correct root
device on the network) but the loop-back mount is not required thereafter.

The following tutorial assumes you have:

* A freshly installed Ubuntu 22.04 server on which you have root authority, and
  which has at least 20GB of available storage

  - In the rest of the tutorial, the server's hostname will be ``server``;
    adjust according to your setup

  - Likewise, your unprivileged user (with ``sudo`` access to root) will be
    ``ubuntu``; adjust references to this and ``~ubuntu`` according to your
    setup

* A Raspberry Pi model 3B, 3B+, 4B, 400, or 5

* A micro-SD card at least 16GB in size

* Ethernet networking connecting the two machines (netboot will *not* operate
  over wifi)


Raspberry Pi
============

Configure the Raspberry Pi for networking boot. The 3B+ is capable of network
boot out of the box, but the 3B, 4B, 400, and 5 all require configuration.
Follow `the instructions <netboot-your-pi_>`_ on the official documentation to
activate network boot on your device.


OS Images
=========

You will need to obtain an OS image that is compatible with :abbr:`NBD (Network
Block Device)` boot. Specifically, this is an image which has an initramfs that
will load the ``nbd`` kernel module and set up ``nbd-client`` pointing at a
specified server when the kernel command line indicates the root is an NBD
device. Ubuntu 24.04 (noble) is *intended* to be compatible out of the box when
it is released in 2024, but for now you should follow these instructions to
construct one.

Fire up `rpi-imager`_ and flash Ubuntu 22.04 server onto the SD card, then boot
that SD card on your chosen Pi.

.. warning::

    Do *not* be tempted to upgrade packages at this point. Specifically, the
    kernel package must *not* be upgraded yet.

Install the ``linux-modules-extra-raspi`` package for the currently running
kernel version. On Ubuntu versions prior to 24.04, the ``nbd`` kernel module
was moved out of the default ``linux-modules-raspi`` package for efficiency. We
specifically need the version matching the running kernel version because
installing this package will regenerate the initramfs (``initrd.img``). We'll
be copying that regenerated file into the image we're going to netboot and it
*must* match the kernel version in that image. This is why it was important not
to upgrade any packages after the first boot.

We also need to install the NBD client package. This will add the
``nbd-client`` executable to the initramfs, along with some scripts to call it
if the kernel command line specifies an NBD device as root:

.. code:: console

    $ sudo apt install linux-modules-extra-$(uname -r) nbd-client

We need to gather one piece of information about the client Pi for use later on
the server: its serial number. We'll store this in a file and copy it and the
``initrd.img`` to the server. Finally, we'll shut down the Pi and move to the
server side of things. Adjust the ``ubuntu`` and ``server`` references when
copying files with ``scp`` below:

.. code:: console

    $ grep Serial /proc/cpuinfo > pi-ident.txt
    $ cat pi-ident.txt
    Serial          : 1000000089025d75
    $ scp -q pi-ident.txt ubuntu@server:
    $ scp -q /boot/firmware/initrd.img ubuntu@server:
    $ sudo poweroff

Download the same OS image to the server, verify its content, unpack it, and
rename it to something more reasonable:

.. code:: console

    $ wget http://cdimage.ubuntu.com/releases/22.04.3/release/ubuntu-22.04.3-preinstalled-server-arm64+raspi.img.xz
     ...
    $ wget http://cdimage.ubuntu.com/releases/22.04.3/release/SHA256SUMS
     ...
    $ sha256sum --check --ignore-missing SHA256SUMS
    ubuntu-22.04.3-preinstalled-server-arm64+raspi.img.xz: OK
    $ rm SHA256SUMS
    $ mv ubuntu-22.04.3-preinstalled-server-arm64+raspi.img jammy-template.img

Create a loop-device for the image, scanning for partitions. Mount the boot
partition and replace the ``initrd.img`` file with the one generated from our
Raspberry Pi. Finally, customize the cloud-init seed to install the same
packages we installed on the Raspberry Pi:

.. code:: console

    $ sudo losetup --find --show --partscan jammy-template.img
    /dev/loop66
    $ mkdir boot
    $ sudo mount /dev/loop66p1 boot/
    $ sudo cp initrd.img boot/
    $ cat << EOF | sudo tee -a boot/user-data
    package_update: true
    packages:
    - avahi-daemon
    - nbd-client
    - linux-modules-extra-raspi
    EOF
    $ sudo umount boot/
    $ sudo losetup -d /dev/loop66

Finally, move our template image somewhere more useful:

.. code:: console

    $ sudo mkdir -p /srv/images
    $ sudo mv jammy-template.img /srv/images/


Ubuntu Server
=============

On the server, install ``nbd-server``, ``dnsmasq``, and ``nobodd``:

.. code:: console

    $ sudo add-apt-repository ppa:waveform/nobodd
    $ sudo apt install nbd-server dnsmasq nobodd

Configure ``dnsmasq`` to proxy TFTP boot requests on the network. You will need
to adjust the ``192.168.255.255`` network mask for your local LAN
configuration if it differs, and the ``eth0`` reference for your local Ethernet
port.

.. code:: console

    $ sudo -i
    # cat << EOF >> /etc/dnsmasq.conf
    interface=eth0
    bind-interfaces
    dhcp-range=192.168.255.255,proxy
    pxe-service=0,"Raspberry Pi Boot"
    EOF
    # systemctl restart dnsmasq.service


Instance Setup
==============

Set up some variables; one for the serial number of the netbooting Raspberry
Pi, another for the filename containing its "disk". You may note that the disk
has a different filename; don't worry, we'll create this in the next step:

.. code:: console

    # cat ~ubuntu/pi-ident.txt
    Serial          : 1000000089025d75
    # piserial=$(sed -e '1s/^Serial.*\([0-9a-f]\{8\}\)$/\1/' ~ubuntu/pi-ident.txt)
    # echo $piserial
    89025d75
    # image=/srv/images/jammy.img
    # echo $image
    /srv/images/jammy.img

Copy your template OS image to the "disk" file for the netbooting Raspberry Pi,
then add configuration for ``nbd-server`` and ``nobodd`` pointing to it:

.. code:: console

    # cd /srv/images
    # ls
    jammy-template.img
    # cp jammy-template.img $image
    # chown nbd:nbd $image
    # cat << EOF > /etc/nbd-server.d/jammy.conf
    [jammy]
    exportname = $image
    EOF
    # cat << EOF >> /etc/nobodd.conf
    [board:$piserial]
    image = $image
    EOF

Finally, customize the image to set the size of its disk, and tell its
initramfs which NBD share to connect to. The output of ``losetup`` below is
*very* likely to differ on your system; adjust references to ``/dev/loop67``
(and its partitions) accordingly:

.. code-block:: console
    :emphasize-lines: 11,24-26

    # fallocate -l 8G $image
    # losetup --find --show --partscan $image
    /dev/loop67
    # mkdir -p /mnt/boot
    # mount /dev/loop67p1 /mnt/boot
    # cat /mnt/boot/cmdline.txt | tr ' ' '\n' > /tmp/cmdline.txt
    # cat /tmp/cmdline.txt
    console=serial0,115200
    dwc_otg.lpm_enable=0
    console=tty1
    root=LABEL=writable
    rootfstype=ext4
    rootwait
    fixrtc
    quiet
    splash
    # sed -i -e '/^root=/ s@=.*$@=/dev/nbd0p2@' /tmp/cmdline.txt
    # sed -i -e '/^root=/ i ip=dhcp' /tmp/cmdline.txt
    # sed -i -e '/^root=/ i nbdroot=server/jammy' /tmp/cmdline.txt
    # cat /tmp/cmdline.txt
    console=serial0,115200
    dwc_otg.lpm_enable=0
    console=tty1
    ip=dhcp
    nbdroot=server/jammy
    root=/dev/nbd0p2
    rootfstype=ext4
    rootwait
    fixrtc
    quiet
    splash
    # paste -s -d ' ' /tmp/cmdline.txt > /mnt/boot/cmdline.txt
    # rm /tmp/cmdline.txt
    # umount /mnt/boot
    # losetup -d /dev/loop67

Naturally, the instance set up can (and should) be automated. This is
anticipated for future releases. Finally, we tell both ``nbd-server`` and
``nobodd`` to reload their configurations:

.. code:: console

    # systemctl reload nobodd.service
    # /etc/init.d/nbd-server reload


Troubleshooting
===============

At this point, you should be ready to try netbooting your Pi. Ensure there is
no SD card in the slot, and power it on. After a short delay you should see the
"rainbow" boot screen appear. This will be followed by a *long* delay on that
screen. The reason is that your Pi is transferring the initramfs over TFTP
which is not an efficient protocol without certain extensions, which the Pi’s
bootloader doesn’t implement. However, eventually you should be greeted by the
typical Linux kernel log scrolling by and reach a typical booted state the same
as you would with an SD card.

If you hit any snags here, the following things are worth checking:

* Pay attention to any errors shown on the Pi's bootloader screen (only
  available on the Pi 4 and 5). In particular, you should be able to see the Pi
  obtaining an IP address via DHCP and various TFTP request attempts.

* Run ``journalctl -f --unit nobodd.service`` on your server to follow the
  nobodd log output. Again, if things are working, you should be seeing
  several TFTP requests here. If you see nothing, double check the network mask
  is specified correctly in the ``dnsmasq`` configuration, and that any
  firewall on the server is permitting inbound traffic to port 69 (the TFTP
  port).

* You *will* see numerous "Early terminate" TFTP errors in the nobodd log
  output. This is normal, and appears to be how the Pi's bootloader operates
  (my guess would be it's attempting to determine the size of a file with the
  ``tsize`` extension, terminating the transfer, allocating RAM for the file,
  then starting the transfer again).

* If cloud-init's final phase running ``apt update`` and ``apt install
  avahi-daemon linux-modules-extra-raspi nbd-client`` fails (which it appears
  to randomly on some set ups), just login and run them manually.


.. _netboot-your-pi: https://www.raspberrypi.com/documentation/computers/remote-access.html#network-boot-your-raspberry-pi
.. _rpi-imager: https://www.raspberrypi.com/software/
