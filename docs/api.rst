=============
API Reference
=============

In additional to being a service, nobody can also be used as an API from Python
to access disk images, determining their partitioning style, enumerating the
available partitions, and reading FAT file-systems (either from within a disk
image, or just standalone). It can also be used as the basis of a generic TFTP
service.

The following sections list the modules by their topic.

Disk Images
===========

The :class:`nobody.disk.DiskImage` class is the primary entry-point for dealing
with disk images.

.. toctree::
    :maxdepth: 1

    api_disk
    api_gpt
    api_mbr


FAT Filesystem
==============

The :class:`nobody.fs.FatFileSystem` class is the primary entry-point for
handling FAT file-systems.

.. toctree::
    :maxdepth: 1

    api_fs
    api_fat
    api_path


TFTP Service
============

The :class:`nobody.tftpd.TFTPBaseServer` and
:class:`nobody.tftpd.TFTPBaseHandler` are two classes which may be customized
to produce a TFTP server. Two example classes are included,
:class:`~nobody.tftpd.SimpleTFTPServer` and
:class:`~nobody.tftp.SimpleTFTPHandler` which serve files directly from a
specified path.

.. toctree::
    :maxdepth: 1

    api_tftpd
    api_tftp


Command line application
========================

The :mod:`nobody.main` module contains the primary classes,
:class:`~nobody.main.BootServer` and :class:`~nobody.main.BootHandler` which
define a TFTP server that reads files from FAT file-systems contained in OS
images.

The other modules, :mod:`nobody.config` and :mod:`nobody.tools` provide
configuration parsing and miscellaneous utilities respectively.

.. toctree::
    :maxdepth: 1

    api_main
    api_config
    api_tools
