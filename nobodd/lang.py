import locale
import gettext


_ = gettext.gettext

def init():
    try:
        locale.setlocale(locale.LC_ALL, '')
    except locale.Error:
        locale.setlocale(locale.LC_ALL, 'C')

    gettext.textdomain(__package__)
