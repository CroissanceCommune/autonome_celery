# -*- coding: utf-8 -*-
# * Authors:
#       * TJEBBES Gaston <g.t@majerti.fr>
#       * Arezki Feth <f.a@majerti.fr>;
#       * Miotte Julien <j.m@majerti.fr>;
import transaction
from celery.utils.log import get_task_logger

from pyramid_celery import celery_app as app

from autonomie.models.company import Company

logger = get_task_logger(__name__)


@app.task
def test_task(*args):
    transaction.begin()
    logger.debug(u"Running the task we want with args : %s" % args)
    company = Company.get(args[0])
    logger.debug(company.name)
    transaction.commit()
