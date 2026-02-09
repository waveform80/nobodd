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
but some have moved under a directory named :file:`current/`. In particular, for
the purposes of preparing an image with :program:`nobodd-prep`, the
:file:`cmdline.txt` file is now :file:`current/cmdline.txt`.

TODO...
