.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2023-2024 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2023-2024 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

========
Tutorial
========

nobodd is a confusingly named, but simple :abbr:`TFTP (Trivial File Transfer
Protocol)` server intended for net-booting Raspberry Pis directly from OS
images without having to loop-back mount or otherwise re-write those images. In
order to get started you will need the following pre-requisites:

* A Raspberry Pi you wish to netboot. This tutorial will be assuming a Pi 4,
  but the Pi 2B, 3B, 3B+, 4B, and 5 all support netboot. However, all have
  different means of configuring their netboot support, and this tutorial will
  only cover the method for the Pi 4.

* A micro-SD card. This is only required for initial configuration of the Pi 4.
  If your Pi 4 is already configured for netboot, you can skip this
  requirement.

* A server that will serve the OS image to be netbooted. This can be another
  Raspberry Pi, but if you eventually wish to scale to several netbooting
  clients you probably want something with a lot more I/O bandwidth. We will
  assume this server is running Ubuntu 24.04, and you have root authority to
  install new packages.

* Ethernet networking connecting the two machines; netboot will *not* operate
  over WiFi.

* The address details of your ethernet network, specifically the network
  address and mask (e.g. 192.168.1.0/24).


Client Side
============

To configure your Pi 4 for netboot, use `rpi-imager`_ to flash Ubuntu Server
24.04 64-bit to your micro-SD card. Boot your Pi 4 with the micro-SD card and
wait for cloud-init to finish the initial user configuration. Log in with the
default user (username "ubuntu", password "ubuntu", unless you specified
otherwise in rpi-imager, and follow the prompts to set a new password).

Run :command:`sudo rpi-eeprom-config --edit`, and enter your password for
"sudo". You will find yourself in an editor, with the Pi's boot configuration
from the EEPROM, which will most likely look something like the following:

.. code-block:: ini

    [all]
    BOOT_UART=0
    WAKE_ON_GPIO=1
    ENABLE_SELF_UPDATE=1
    BOOT_ORDER=0xf41

The value we are concerned with, is ``BOOT_ORDER``. This is a hexadecimal value
(denoted by the "0x" prefix) in which each hex digit specifies another boot
source in *reverse order*. The digits that may be specified include:

== ========= ================================================================
#  Mode      Description
== ========= ================================================================
1  SD CARD   Boot from the SD card
2  NETWORK   Boot from TFTP over ethernet
4  USB-MSD   Boot from a USB :abbr:`MSD (mass storage device)`
e  STOP      Stop the boot and display an error pattern
f  RESTART   Restart the boot from the first mode
== ========= ================================================================

A `full listing <BOOT_ORDER_>`_ of valid digits can be found in the Raspberry
Pi documentation. The current setting shown above is "0xf41". Remembering that
this is in *reversed* order, we can interpret this as "try the SD card first
(1), then try a USB mass storage device (4), then restart the sequence if
neither worked (f)".

We'd like to try network booting first, so we need to add the value 2 to the
end, giving us: "0xf412". Change the "BOOT_ORDER" value to this, save and exit
the editor.

.. warning::

    You may be tempted to remove values from the boot order to avoid delay
    (e.g. testing for the presence of an SD card). However, you are strongly
    advised to leave the value 1 (SD card booting) somewhere in your boot order
    to permit recovery from an SD card (or future re-configuration).

Upon exiting, the :command:`rpi-eeprom-config` command should prompt you that
you need to reboot in order to flash the new configuration onto the boot
EEPROM. Enter :command:`sudo reboot` to do so, and let the boot complete fully.

Once you are back at a login prompt, log back in with your username and
password, and then run :command:`sudo rpi-eeprom-config` once more to query the
boot configuration and make sure your change has taken effect. It should output
something like:

.. code-block:: ini

    [all]
    BOOT_UART=0
    WAKE_ON_GPIO=1
    ENABLE_SELF_UPDATE=1
    BOOT_ORDER=0xf412

Finally, we need the serial number of your Raspberry Pi. This can be found with
the following command:

.. code-block:: console

    $ grep ^Serial /proc/cpuinfo
    Serial          : 10000000abcd1234

Note this number down somewhere safe as we'll need it for the server
configuration later. The Raspberry Pi side of the configuration is now
complete, and we can move on to configuring our netboot server.


Server Side
===========

As mentioned in the pre-requisites, we will assume the server is running Ubuntu
24.04, and that you are logged in with a user that has root authority (via
"sudo"). Firstly, install the packages which will provide our `TFTP`_, `NBD`_,
and `DHCP`_ proxy servers, along with some tooling to customize images:

.. code-block:: console

    $ sudo apt install nobodd-tftpd nobodd-prep nbd-server xz-utils dnsmasq

The first thing to do is configure :manpage:`dnsmasq(8)` as a DHCP proxy
server. Find the interface name of your server's primary ethernet interface
(the one that will talk to the same network as the Raspberry Pi) within the
output of the :command:`ip addr show up` command. It will probably look
something like "enp2s0f0":

.. code-block:: console
    :emphasize-lines: 8,10

    $ ip addr show
    1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
        link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
        inet 127.0.0.1/8 scope host lo
           valid_lft forever preferred_lft forever
        inet6 ::1/128 scope host
            valid_lft forever preferred_lft forever
    2: enp2s0f0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP group default qlen 1000
        link/ether 0a:0b:0c:0d:0e:0f brd ff:ff:ff:ff:ff:ff
        inet 192.168.1.4/16 brd 192.168.1.255 scope global enp2s0f0
           valid_lft forever preferred_lft forever
        inet6 fd00:abcd:1234::4/128 scope global noprefixroute
           valid_lft forever preferred_lft 53017sec
        inet6 fe80::beef:face:d00d:1234/64 scope link
            valid_lft forever preferred_lft forever
    3: enp1s0f1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq master br0 state UP group default qlen 1000
        link/ether 1a:0b:0c:0d:0e:0f brd ff:ff:ff:ff:ff:ff
    4: br0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default qlen 1000
        link/ether 02:6c:fc:6f:56:5c brd ff:ff:ff:ff:ff:ff
        inet6 fe80::60d9:48ff:fee3:c955/64 scope link
           valid_lft forever preferred_lft forever
    ...

Add the following configuration lines to :file:`/etc/dnsmasq.conf` adjusting
the ethernet interface name, and the network mask on the highlighted lines to
your particular setup:

.. code-block:: text
    :emphasize-lines: 2,7

    # Only listen on the primary ethernet interface
    interface=enp2s0f0
    bind-interfaces

    # Perform DHCP proxying on the network, and advertise our
    # PXE-ish boot service
    dhcp-range=192.168.1.255,proxy
    pxe-service=0,"Raspberry Pi Boot"

Re-load the dnsmasq configuration:

.. code-block:: console

    $ sudo systemctl reload dnsmasq.service

Next, we need to obtain an image to boot on our Raspberry Pi. We'll be using
the Ubuntu 24.04 Server for Raspberry Pi image as this is configured for NBD
boot out of the box. We will place this image under a :file:`/srv/images`
directory and unpack it so we can manipulate it:

.. code-block:: console

    $ sudo mkdir /srv/images
    $ sudo chown ubuntu:ubuntu /srv/images
    $ cd /srv/images
    $ wget http://cdimage.ubuntu.com/releases/24.04/release/ubuntu-24.04-preinstalled-server-arm64+raspi.img.xz
     ...
    $ wget http://cdimage.ubuntu.com/releases/24.04/release/SHA256SUMS
     ...
    $ sha256sum --check --ignore-missing SHA256SUMS
    $ rm SHA256SUMS
    $ unxz ubuntu-24.04-preinstalled-server-arm64+raspi.img.xz

We'll use the :program:`nobodd-prep` command to adjust the image so that the
kernel will try and find its root on our NBD server. At the same time, we'll
have the utility generate the appropriate configurations for
:manpage:`nbd-server(1)` and :program:`nobodd-tftpd`.

:program:`nobodd-prep` needs to know several things in order to operate, but
tries to use sensible defaults where it can:

* The filename of the image to customize; we'll simply provide this on the
  command line.

* The size we want to expand the image to; this will be size of the "disk" (or
  "SD card") that the Raspberry Pi sees. The default is 16GB, which is fine for
  our purposes here.

* The number of the boot partition within the image; the default is the first
  FAT partition, which is fine in this case.

* The name of the file containing the kernel command line on the boot
  partition; the default is :file:`cmdline.txt` which is correct for the
  Ubuntu images.

* The number of the root partition within the image; the default is the first
  non-FAT partition, which is also fine here.

* The host-name of the server; the default is the output of :command:`hostname
  --fqdn` but this can be specified manually with :option:`nobodd-prep
  --nbd-host`.

* The name of the NBD share; the default is the stem of the image filename (the
  filename without its extensions) which in this case would be
  :file:`ubuntu-24.04-preinstalled-server-arm64+raspi`. That's a bit of a
  mouthful so we'll override it with :option:`nobodd-prep --nbd-name`.

* The serial number of the Raspberry Pi; there is no default for this, so we'll
  provide it with :option:`nobodd-prep --serial`.

* The path to write the two configuration files we want to produce; we'll
  specify these manually with :option:`nobodd-prep --tftpd-conf` and
  :option:`nobodd-prep --nbd-conf`

Putting all this together we run:

.. code-block:: console

    $ nobodd-prep --nbd-name ubuntu-noble --serial 10000000abcd1234 \
    > --tftpd-conf tftpd-noble.conf --nbd-conf nbd-noble.conf \
    > ubuntu-24.04-preinstalled-server-arm64+raspi.img

Now we need to move the generated configuration files to their correct
locations and ensure they're owned by root (so unprivileged users cannot modify
them), ensure the modified image is owned by the "nbd" user (so the NBD service
can read and write to it), and reload the configuration in the relevant
services:

.. code-block:: console

    $ sudo chown nbd:nbd ubuntu-24.04-preinstalled-server-arm64+raspi.img
    $ sudo chown root:root tftpd-noble.conf nbd-noble.conf
    $ sudo mv tftpd-noble.conf /etc/nobodd/conf.d/
    $ sudo mv nbd-noble.conf /etc/nbd-server/conf.d/
    $ sudo systemctl reload nobodd-tftpd.service
    $ sudo systemctl reload nbd-server.service


Testing and Troubleshooting
===========================

At this point your configuration should be ready to test. Ensure there is no SD
card in the slot, and power it on. After a short delay you should see the
"rainbow" boot screen appear. This will be followed by an uncharacteristically
long delay on that screen. The reason is that your Pi is transferring the
initramfs over TFTP which is not an efficient protocol absent certain
extensions, which the Pi's bootloader doesn't implement. However, eventually
you should be greeted by the typical Linux kernel log scrolling by, and reach a
typical booted state the same as you would with a freshly flashed SD card.

If you hit any snags here, the following things are worth checking:

* Pay attention to any errors shown on the Pi's bootloader screen. In
  particular, you should be able to see the Pi obtaining an IP address via DHCP
  and various TFTP request attempts.

* Run ``journalctl -f --unit nobodd-tftpd.service`` on your server to follow
  the TFTP log output. Again, if things are working, you should be seeing
  several TFTP requests here. If you see nothing, double check the network mask
  is specified correctly in the :manpage:`dnsmasq(8)` configuration, and that
  any firewall on your server is permitting inbound traffic to port 69 (the
  default TFTP port).

* You *will* see numerous "Early terminate" TFTP errors in the journal output.
  This is normal, and appears to be how the Pi's bootloader operates (at a
  guess it's attempting to determine the size of a file with the ``tsize``
  extension, terminating the transfer, allocating RAM for the file, then
  starting the transfer again).

.. _TFTP: https://en.wikipedia.org/wiki/Trivial_File_Transfer_Protocol
.. _NBD: https://en.wikipedia.org/wiki/Network_block_device
.. _DHCP: https://en.wikipedia.org/wiki/Dynamic_Host_Configuration_Protocol
.. _rpi-imager: https://www.raspberrypi.com/software/
.. _BOOT_ORDER: https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#BOOT_ORDER
