===========================
How to netboot Ubuntu 24.04
===========================

The Ubuntu 24.04 (noble) images are not compatible with NBD boot out of the box
due to some hilarious bureaucracy. However, thanks to changes in the image
build procedure before 24.04's release, it's not particularly difficult to
generate your own Ubuntu 24.04 image, complete with nbd-client pre-installed.


Pre-requisites
==============

You will need to perform the following on a Raspberry Pi (or another machine
with the arm64 architecture; image generation is not supported across
architectures). You will need access to the root user on the image build system
(building images requires the ability to mount file-systems).

Image generation requires quite a bit of space (at least double the
uncompressed final image size), and involves a lot of I/O so a Raspberry Pi 5
with NVMe storage is ideal. The final Ubuntu Server 24.04 image is roughly 4GB
in size, so you'll need at least 8GB of space available (preferably quite a bit
more). If you want to work on the Ubuntu Desktop image, this is roughly 9GB in
size (so you'll need at least 18GB of space available), but this guide will
only cover the server image.

Install the ubuntu-image snap, with classic confinement.

.. code-block:: console

    $ sudo snap install ubuntu-image --classic

Clone the image definition repository, and switch to the noble (24.04) branch.

.. code-block:: console

    $ git clone https://git.launchpad.net/ubuntu-images
    $ cd ubuntu-images
    $ git checkout noble


Modifications
=============

The definition for Ubuntu for Raspberry Pi images is a relatively simple
`YAML`_ based format.

ubuntu-server-pi-arm64.yaml
    The Ubuntu Server for Raspberry Pi defintion

ubuntu-pi-arm64.yaml
    The Ubuntu Desktop for Raspberry Pi definition.

Open the :file:`ubuntu-server-pi-arm64.yaml` file in your favourite text
editor, and insert the highlighted lines below at the location shown:

.. code-block:: yaml
    :highlight-lines: 36-37

    name: ubuntu-server-raspi-arm64
    display-name: Ubuntu Server Raspberry Pi arm64
    revision: 2
    architecture: arm64
    series: noble
    class: preinstalled
    kernel: linux-image-raspi
    gadget:
      url: "https://git.launchpad.net/snap-pi"
      branch: "classic"
      type: "git"
    rootfs:
      archive: ubuntu
      components:
        - main
        - restricted
        - universe
        - multiverse
      mirror: "http://ports.ubuntu.com/ubuntu-ports/"
      sources-list-deb822: true
      pocket: updates
      seed:
        urls:
          - "git://git.launchpad.net/~ubuntu-core-dev/ubuntu-seeds/+git/"
        branch: noble
        names:
          - server
          - server-raspi
          - raspi-common
          - minimal
          - standard
          - cloud-image
          - supported-raspi-common
    customization:
      extra-snaps:
        - name: snapd
      extra-packages:
        - name: nbd-client
      fstab:
        - label: "writable"
          mountpoint: "/"
          filesystem-type: "ext4"
          dump: false
          fsck-order: 1
        - label: "system-boot"
          mountpoint: "/boot/firmware"
          filesystem-type: "vfat"
          mount-options: "defaults"
          dump: false
          fsck-order: 1
    artifacts:
      img:
        - name: ubuntu-24.04-preinstalled-server-arm64+raspi.img
      manifest:
        name: ubuntu-24.04-preinstalled-server-arm64+raspi.manifest

.. note::

    If you wish to perform this procedure on the desktop image definition, the
    same lines need adding.


Build
=====

After saving the modified YAML, exit your editor and run the build process:

.. code-block:: console

    $ mkdir build
    $ sudo ubuntu-image classic -v --output-dir build/ ubuntu-server-pi-arm64.yaml

After some time, you should wind up with a couple of files under the "build"
directory:

build/ubuntu-24.04-preinstalled-server-arm64+raspi.img
    This is the uncompressed image which you use directly with your NBD setup

build/ubuntu-24.04-preinstalled-server-arm64+raspi.manifest
    This is the manifest file containing a list of every package (and package
    version) included in the image
