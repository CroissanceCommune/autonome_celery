# -*- coding:utf-8 -*-
import locale
locale.setlocale(locale.LC_ALL, "fr_FR.UTF-8")
locale.setlocale(locale.LC_TIME, "fr_FR.UTF-8")

import logging
from pyramid.config import Configurator
from pyramid.paster import setup_logging
from sqlalchemy import engine_from_config
from pyramid_beaker import set_cache_regions_from_settings

from autonomie.models.initialize import initialize_sql


def main(global_config, **settings):
    """
    Entry point for the pyramid celery stuff
    """
    logging.basicConfig()
    setup_logging(global_config['__file__'])
    logger = logging.getLogger(__name__)
    logger.info("Bootstraping app")
    engine = engine_from_config(settings, 'sqlalchemy.')
    set_cache_regions_from_settings(settings)
    initialize_sql(engine)
    config = Configurator(settings=settings)
    config.configure_celery(global_config['__file__'])
    config.commit()
    return config
