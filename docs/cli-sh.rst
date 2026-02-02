.. include:: subst.rst

=============
nobodd-sh
=============

Run shell-like commands against the file-system and/or FAT partitions within
file-system image. This is intended for use in scripting the preparation of
images for use with the nobodd-tftpd server.


Synopsis
========

.. code-block:: text

    usage: nobodd-sh [-h] [--version] [-v] [-q]
                     {help,cat,rm,rmdir,mkdir,touch,ls,cp,mv} ...


Options
=======

.. program:: nobodd-sh

.. option:: -h, --help

    Show this help message and exit

.. option:: --version

    Show program's version number and exit

.. option:: -v, --verbose

    Print more output

.. option:: -q, --quiet

    Print no output


Sub-commands
============

The first mandatory passed to :program:`nobodd-sh` is the sub-command to run.
These are all named after the standard POSIX shell utilities they emulate, and
all implement a similar (but much more limited) set of options. Notably,
filenames passed to these utilities will be treated rather differently to their
common shell counterparts:


help
----

With no arguments, displays a list of nobodd-sh help commands. If a command
name is given, displays the description and options for the named command.

.. code-block:: text

    usage: nobodd-sh help [-h] [command]

.. program:: nobodd-sh-help

.. option:: command

    The command to display help for; valid commands are shown in the following
    sections

.. option:: -h, --help

    Show this help message and exit


cat
---

Concatenate content from the given files, writing it to stdout by default. If
"-" is given as a filename, or if no filenames are specified, *stdin* is read.
In order to permit output to a file within an image, ``-o`` is provided to
specify an output other than stdout.

.. code-block:: text

    usage: nobodd-sh cat [-h] [-o filename] [filenames ...]

.. program:: nobodd-sh-cat

.. option:: filenames

    The input files

.. option:: -h, --help

    Show this help message and exit

.. option:: -o filename, --output filename

    The output file (default: stdout)


cp
--

Copy the specified file over the target file, if only one source is given, or
copy the specified files and directories into the target directory, if the
target is a directory.

.. code-block:: text

    usage: nobodd-sh cp [-h] filenames [filenames ...] dest

.. program:: nobodd-sh-cp

.. option:: filenames

    The files or directories to copy

.. option:: dest

    The directory to copy into or the file to replace

.. option:: -h, --help

    Show this help message and exit


ls
--

List information about the files, or the contents of the directories given.
Entries will be sorted alphabetically, unless another ordering is explicitly
specified. By default, hidden files (beginning with ".") are excluded from the
output, unless ``-a`` is provided.

.. code-block:: text

    usage: nobodd-sh ls [-h] [-a] [-l] [--sort SORT] [-U] [-S] [-t] [-X]
                        filenames [filenames ...]

.. program:: nobodd-sh-ls

.. option:: filenames

    The files or directories to list

.. option:: -h, --help

    Show this help message and exit

.. option:: -a, --all

    Do not ignore entries beginning with .

.. option:: -l

    Show details beside listed entries

.. option:: --sort SORT

    Sort on "name" (the default), "size", "time", or "none" to disable sorting

.. option:: -U

    Disable sorting

.. option:: -S

    Sort by file size (largest first)

.. option:: -t

    Sort by modification time (newest first)

.. option:: -X

    Sort by entry extension


mkdir
-----

Creates the directories specified, which must not exist either as directories
or regular files.

.. code-block:: text

    usage: nobodd-sh mkdir [-h] [-p] filenames [filenames ...]

.. program:: nobodd-sh-mkdir

.. option:: filenames

    The directories to create

.. option:: -h, --help

    Show this help message and exit

.. option:: -p, --parents

    Create parent directories as required


mv
--

Move the specified file over the target file, if only one source is given, or
move the specified files and directories into the target directory, if the
target is a directory.

.. code-block:: text

    usage: nobodd-sh mv [-h] filenames [filenames ...] dest

.. program:: nobodd-sh-mv

.. option:: filenames

    The files or directories to copy

.. option:: dest

    The directory to move into or the file to replace

.. option:: -h, --help

    Show this help message and exit

.. warning::

    Unlike regular ``mv`` there is no guarantee of atomic operation,
    particularly with respect to files within images.


rm
--

Removes the files specified. If ``-r`` is given, will recursively remove
directories and their contents as well.

.. code-block:: text

    usage: nobodd-sh rm [-h] [-r] [-f] filenames [filenames ...]

.. program:: nobodd-sh-rm

.. option:: filenames

    The files or directories to remove

.. option:: -h, --help

    Show this help message and exit

.. option:: -r, -R, --recursive

    Remove directories and their contents recursively

.. option:: -f, --force

    Do not error on non-existent arguments and never prompt


rmdir
-----

Removes the directories specified, which must be empty.

.. code-block:: text

    usage: nobodd-sh rmdir [-h] filenames [filenames ...]

.. program:: nobodd-sh-rmdir

.. option:: filenames

    The directories to remove

.. option:: -h, --help

    Show this help message and exit


touch
-----

Update last modified timestamps, creating any files that do not already exist.

.. code-block:: text

    usage: nobodd-sh touch [-h] filenames [filenames ...]

.. program:: nobodd-sh-touch

.. option:: filenames

    The files to create or modify the timestamps of

.. option:: -h, --help

    Show this help message and exit


Usage
=====

Filenames will be parsed as regular filenames unless they contain ":/" or
":*N*/" where *N* is a partition number. If so, the portion before ":" is
treated as an image file, the *N* (if specified) as the partition within that
image (the first auto-detected FAT partition is used if *N* is not
specified), and the portion from "/" onwards as an absolute path within that
partition. As such the application may be used to copy (or move) files to /
from / within FAT file-systems within images.

For example:

* ``foo.txt`` will be interpreted as an ordinary file in the file-system

* ``foo.img:/foo.txt`` will be interpreted as the file ``foo.txt`` in the root
  of the first FAT partition found within the disk image ``foo.img``

* ``foo.img:10/foo.txt`` will be interpreted as the file ``foo.txt`` in the
  root of the 10th partition found in the disk image ``foo.img``

Please be aware that nobodd-sh does *not* perform file-locking [#broken]_.
Therefore it is *possible*, but definitely not advisable, to open the same
partition in the same image in two parallel nobodd-sh processes. This is
extremely likely to lead to corruption of the FAT file-system if both processes
are writing to the partition. Even if one process is read-only and the other
read-write, this is still not safe, as the reading process may read the wrong
data, depending on what the writing process does.


Examples
========

Query the current kernel command line in an image.

.. code-block:: console

    $ nobodd-sh cat ~/images/ubuntu-26.04.img:1/current/cmdline.txt
    console=serial0,115200 multipath=off dwc_otg.lpm_enable=0 console=tty1 root=LABEL=writable rootfstype=ext4 panic=10 rootwait fixrtc

Copy the kernel command line to the local file-system, editing it with sed, and
moving it back into the image:

.. code-block:: console

    $ nobodd-sh cp ~/images/ubuntu-26.04.img:1/current/cmdline.txt ./
    $ sed -i -e 's/panic=10/panic=5/' cmdline.txt
    $ nobodd-sh mv cmdline.txt ~/images/ubuntu-26.04.img:1/current/

Doing the same with the ``cat -o`` option with a pipe from sed:

.. code-block:: console

    $ nobodd-sh cp ~/images/ubuntu-26.04.img:1/current/cmdline.txt ./
    $ sed -i -e 's/panic=10/panic=5/' cmdline.txt | \
      nobodd-sh cat -o ~/images/ubuntu-26.04.img:1/current/cmdline.txt

Checking the content of the current bootloader assets in the image:

.. code-block:: console

    $ nobodd-sh ls -l ~/images/ubuntu-26.04.img:/current/
    -r--r--r--  1 root root    32503 Oct 23 13:41 bcm2710-rpi-2-b.dtb
    -r--r--r--  1 root root    35330 Oct 23 13:41 bcm2710-rpi-3-b-plus.dtb
    -r--r--r--  1 root root    34695 Oct 23 13:41 bcm2710-rpi-3-b.dtb
    -r--r--r--  1 root root    33684 Oct 23 13:41 bcm2710-rpi-cm0.dtb
    -r--r--r--  1 root root    32266 Oct 23 13:41 bcm2710-rpi-cm3.dtb
    -r--r--r--  1 root root    33672 Oct 23 13:41 bcm2710-rpi-zero-2-w.dtb
    -r--r--r--  1 root root    33672 Oct 23 13:41 bcm2710-rpi-zero-2.dtb
    -r--r--r--  1 root root    56289 Oct 23 13:41 bcm2711-rpi-4-b.dtb
    -r--r--r--  1 root root    56293 Oct 23 13:41 bcm2711-rpi-400.dtb
    -r--r--r--  1 root root    39913 Oct 23 13:41 bcm2711-rpi-cm4-io.dtb
    -r--r--r--  1 root root    56810 Oct 23 13:41 bcm2711-rpi-cm4.dtb
    -r--r--r--  1 root root    53510 Oct 23 13:41 bcm2711-rpi-cm4s.dtb
    -r--r--r--  1 root root    78638 Oct 23 13:41 bcm2712-d-rpi-5-b.dtb
    -r--r--r--  1 root root    78642 Oct 23 13:41 bcm2712-rpi-5-b.dtb
    -r--r--r--  1 root root    78598 Oct 23 13:41 bcm2712-rpi-500.dtb
    -r--r--r--  1 root root    79591 Oct 23 13:41 bcm2712-rpi-cm5-cm4io.dtb
    -r--r--r--  1 root root    79657 Oct 23 13:41 bcm2712-rpi-cm5-cm5io.dtb
    -r--r--r--  1 root root    79632 Oct 23 13:41 bcm2712-rpi-cm5l-cm4io.dtb
    -r--r--r--  1 root root    79698 Oct 23 13:41 bcm2712-rpi-cm5l-cm5io.dtb
    -r--r--r--  1 root root    78646 Oct 23 13:41 bcm2712d0-rpi-5-b.dtb
    -r--r--r--  1 root root      132 Oct 23 13:41 cmdline.txt
    -r--r--r--  1 root root 78601311 Oct 23 13:41 initrd.img
    dr-xr-xr-x  2 root root        0 Jan  1  1970 overlays
    -r--r--r--  1 root root        5 Oct 23 13:41 state
    -r--r--r--  1 root root 13783000 Oct 23 13:41 vmlinuz


See Also
========

.. only:: not man

    :doc:`cli-prep`, :doc:`cli-server`, :manpage:`nbd-server(1)`

.. only:: man

    :manpage:`nobodd-prep(1)`, :manpage:`nobodd-tftpd(1)`, :manpage:`nbd-server(1)`

Bugs
====

|bug-link|


.. [#broken] For all the reasons that one should generally avoid file-locking
   on Linux; see `On the Brokenness of File Locking
   <https://0pointer.de/blog/projects/locking.html>`_ for more
