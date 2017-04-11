# -*- coding: utf-8 -*-
# * Authors:
#       * TJEBBES Gaston <g.t@majerti.fr>
#       * Arezki Feth <f.a@majerti.fr>;
#       * Miotte Julien <j.m@majerti.fr>;
"""
Celery tasks used to asynchronously generate exports (like excel exports)


Workflow :
    user provide filters
    TODO : user provide columns

    For UserDatas exports, we need to add some fields


    1- Task entry
    2- retrieve model
    3- generate the file or re-use the cached one
"""
import os
import time
from pyramid_celery import celery_app
from sqla_inspect.ods import SqlaOdsExporter
from beaker.cache import cache_region
from autonomie.models.user import UserDatas
from celery.utils.log import get_task_logger


MODELS = {
    'userdatas': UserDatas,
}

logger = get_task_logger(__name__)


def get_tmp_filepath():
    """
    Return the tmp filepath configured in the current configuration
    :param obj request: The pyramid request object
    """
    registry = celery_app.conf['PYRAMID_REGISTRY']
    asset_path_spec = registry.settings.get('autonomie.static_tmp')
    return asset_path_spec


@cache_region('default_term')
def get_export_ods(tmpdir, model, query, fields):
    """
    Return a path to an ods generated file
    """
    writer = SqlaOdsExporter(model=model)
    for item in query:
        writer.add_row(item)
    filename = os.path.join(tmpdir, "test_%s.ods" % time.time())
    with open(filename, 'w') as f_buf:
        writer.render(f_buf)
    return filename


@celery_app.task(bind=True)
def export_to_ods(self, model_type, filters, fields):
    """
    Export the datas provided in the given query to ods format
    """
    logger.info(u"Exporting to an ods file")
    logger.info(u"  + model_type : %s", model_type)
    logger.info(u"  + filters : %s", filters)
    logger.info(u"  + fields : %s", fields)
    model = MODELS[model_type]
    tmpdir = get_tmp_filepath()
    query = model.query()
    for key, value in filters:
        query = query.filter(getattr(model, key) == value)

    try:
        result_filepath = get_export_ods(tmpdir, model, query, fields)
        logger.debug(u" -> A file has been written in %s", result_filepath)
    except:
        logger.exception("Error while generating ods file")
        result_filepath = None
    return result_filepath
