# -*- coding: utf-8 -*-
# * Authors:
#       * TJEBBES Gaston <g.t@majerti.fr>
#       * Arezki Feth <f.a@majerti.fr>;
#       * Miotte Julien <j.m@majerti.fr>;
"""
Configuration management tools

Tools to retrieve elements from the main app configuration
"""


def get_registry():
    """
    Return the Pyramid application registry associated to the current running
    application

    :returns: A Pyramid registry instance
    """
    from pyramid_celery import celery_app
    return celery_app.conf['PYRAMID_REGISTRY']


def get_setting(key, mandatory=False, default=None):
    """
    Collect a given setting

    :param str key: The key to collect
    :param bool mandatory: Is the key mandatory (if it is a KeyError may be
    raised)
    :param default: The default value to return
    :rtype: str
    """
    settings = get_registry().settings
    if mandatory:
        return settings[key]
    else:
        return settings.get(key, default)


def get_sysadmin_mail():
    """
    Retrieve the sysadmin mail from the current configuration or None if not set

    :rtype: str
    """
    return get_setting("autonomie.sysadmin_mail")
