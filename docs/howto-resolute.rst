===========================
How to netboot Ubuntu 26.04
===========================

The Ubuntu 26.04 (resolute) images are compatible with NBD out of the box, but
have a slightly different layout in their boot partition which requires some
changes to how :program:`nobodd-prep` is called.


Boot assets under current/
==========================

Ubuntu 26.04 (resolute) has a new layout on the boot partition, implementing
`A/B boot`_. Many of the boot files remain in the root of the boot partition,
but some have moved under a directory named :file:`current/`. In particular,
for the purposes of preparing an image with :program:`nobodd-prep`, the
:file:`cmdline.txt` file is now :file:`current/cmdline.txt`.

Thus, when preparing an image for use (as in the :doc:`tutorial`), you also
need to specify the :option:`nobodd-prep --cmdline` parameter, like so:

.. code-block:: console

    $ nobodd-prep --nbd-name ubuntu-noble --serial 10000000abcd1234 \
    > --tftpd-conf tftpd-noble.conf --nbd-conf nbd-noble.conf \
    > --cmdline current/cmdline.txt \
    > ubuntu-26.04-preinstalled-server-arm64+raspi.img

.. warning::

    Please note this section has been written in anticipation of resolute's
    forthcoming release and thus may be wildly inaccurate! In fact, at the time
    of writing, the current daily images aren't booting successfully with nbd.

.. _A/B boot: https://waldorf.waveform.org.uk/2025/pull-yourself-up-by-your-bootstraps.html
