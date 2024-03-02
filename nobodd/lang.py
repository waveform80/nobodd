# nobodd: a boot configuration tool for the Raspberry Pi
#
# Copyright (c) 2024 Dave Jones <dave.jones@canonical.com>
# Copyright (c) 2024 Canonical Ltd.
#
# SPDX-License-Identifier: GPL-3.0

import locale
import gettext


_ = gettext.gettext

def init():
    try:
        locale.setlocale(locale.LC_ALL, '')
    except locale.Error:
        locale.setlocale(locale.LC_ALL, 'C')

    gettext.textdomain(__package__)
