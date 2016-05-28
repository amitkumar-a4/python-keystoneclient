# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.


import six

import oslo_i18n as i18n
from oslo_utils import encodeutils


_translators = i18n.TranslatorFactory(domain='heat')

# The primary translation function using the well-known name "_"
_ = _translators.primary

# Translators for log levels.
#
# The abbreviated names are meant to reflect the usual use of a short
# name like '_'. The "L" is for "log" and the other letter comes from
# the level.
_LI = _translators.log_info
_LW = _translators.log_warning
_LE = _translators.log_error
_LC = _translators.log_critical


def repr_wraper(klass):
    """A decorator that defines __repr__ method under Python 2.

    Under Python 2 it will encode repr return value to str type.
    Under Python 3 it does nothing.
    """
    if six.PY2:
        if '__repr__' not in klass.__dict__:
            raise ValueError("@repr_wraper cannot be applied "
                             "to %s because it doesn't define __repr__()." %
                             klass.__name__)
        klass._repr = klass.__repr__
        klass.__repr__ = lambda self: encodeutils.safe_encode(self._repr())
    return klass
