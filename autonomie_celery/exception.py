# -*- coding: utf-8 -*-
# * Authors:
#       * TJEBBES Gaston <g.t@majerti.fr>
#       * Arezki Feth <f.a@majerti.fr>;
#       * Miotte Julien <j.m@majerti.fr>;
"""
Custom exceptions
"""

class MissingMandatoryArgument(Exception):
    """
    Raised when a mandatory argument is missing
    """
    pass


class InstanceNotFound(Exception):
    """
    Raised when no instance could be found
    """
    pass


class MultipleInstanceFound(Exception):
    """
    Raised when no instance could be found
    """
    pass
