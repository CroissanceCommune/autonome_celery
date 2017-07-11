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
import transaction
from tempfile import mktemp

from pyramid_celery import celery_app
from beaker.cache import cache_region
from celery.utils.log import get_task_logger

from sqla_inspect.ods import SqlaOdsExporter
from sqla_inspect.excel import SqlaXlsExporter
from sqla_inspect.csv import SqlaCsvExporter
from sqlalchemy.orm import (
    RelationshipProperty,
)
from sqlalchemy.sql.expression import label
from sqlalchemy import (
    desc,
    func,
)

from autonomie_celery.models import FileGenerationJob
from autonomie_celery.tasks import utils

MODELS = {}

logger = get_task_logger(__name__)


GENERATION_ERROR_MESSAGE = (
    u"Une erreur inconnue a été rencontrée à la génération de votre fichier, "
    "veuillez contacter votre administrateur en lui"
    "fournissant l'identifiant suivant : %s"
)


def _add_o2m_headers_to_writer(writer, query):
    """
    Add column headers in the form "label 1",  "label 2" ... to be able to
    insert the o2m related elements to a main model's table export (allow to
    have 3 dimensionnal datas in a 2d array)

    E.g : Userdatas objects have got a o2m relationship on DateDatas objects

    Here we would add date 1, date 2... columns regarding the max number of
    configured datas (if a userdatas has 5 dates, we will have 5 columns)
    We fill the column with the value of an attribute of the DateDatas model
    (that is handled by sqla_inspect thanks to the couple index + related_key
    configuration)

    The name of the attribute is configured using the "flatten" key in the
    relationship's export configuration
    """
    from autonomie_base.models.base import DBSESSION
    new_headers = []
    for header in writer.headers:
        if isinstance(header['__col__'], RelationshipProperty):
            if header['__col__'].uselist:
                class_ = header['__col__'].mapper.class_
                # On compte le nombre maximum d'objet lié que l'on rencontre
                # dans la base
                if not hasattr(class_, 'userdatas_id'):
                    continue
                count = DBSESSION().query(
                    label("nb", func.count(class_.id))
                ).group_by(class_.userdatas_id).order_by(
                    desc("nb")).first()
                if count is not None:
                    count = count[0]
                else:
                    count = 0

                # Pour les relations O2M qui ont un attribut flatten de
                # configuré, On rajoute des colonnes "date 1" "date 2" dans
                # notre sheet principale
                for index in range(0, count):
                    if 'flatten' in header:
                        flatten_keys = header['flatten']
                        if not hasattr(flatten_keys, '__iter__'):
                            flatten_keys = [flatten_keys]

                        for flatten_key, flatten_label in flatten_keys:
                            new_header = {
                                '__col__': header['__col__'],
                                'label': u"%s %s %s" % (
                                    header['label'],
                                    flatten_label,
                                    index + 1),
                                'key': header['key'],
                                'name': u"%s_%s_%s" % (
                                    header['name'],
                                    flatten_key,
                                    index + 1
                                ),
                                'related_key': flatten_key,
                                'index': index
                            }
                            new_headers.append(new_header)

    writer.headers.extend(new_headers)
    return writer


def _add_userdatas_custom_headers(writer, query):
    """
    Specific to userdatas exports

    Add custom headers that are not added through automation

    Add headers for code_compta
    """
    from autonomie_base.models.base import DBSESSION
    from autonomie.models.user import COMPANY_EMPLOYEE
    # Compte analytique
    query = DBSESSION().query(
        func.count(COMPANY_EMPLOYEE.c.company_id).label('nb')
    )
    query = query.group_by(COMPANY_EMPLOYEE.c.account_id)
    code_compta_count = query.order_by(desc("nb")).first()
    if code_compta_count:
        code_compta_count = code_compta_count[0]
        for index in range(0, code_compta_count):
            new_header = {
                'label': "Compte_analytique {0}".format(index + 1),
                'name': "code_compta_{0}".format(index + 1),
            }
            writer.add_extra_header(new_header)

    return writer


def _add_userdatas_code_compta(writer, userdatas):
    """
    Add code compta to exports (specific for userdatas exports)

    :param obj writer: The tabbed file writer
    :param obj userdatas: The UserDatas instance we manage
    """
    user_account = userdatas.user
    if user_account:
        datas = []
        for company in user_account.companies:
            datas.append(company.code_compta)
        writer.add_extra_datas(datas)
    return writer


def _get_tmp_directory_path():
    """
    Return the tmp filepath configured in the current configuration
    :param obj request: The pyramid request object
    """
    registry = celery_app.conf['PYRAMID_REGISTRY']
    asset_path_spec = registry.settings.get('autonomie.static_tmp')
    return asset_path_spec


def _get_tmp_filepath(directory, basename, extension):
    """
    Return a temp filepath for the given filename

    :param str basename: The base name to use
    :returns: A path to a non existing file
    :rtype: str
    """
    if not extension.startswith('.'):
        extension = u'.' + extension

    filepath = mktemp(prefix=basename, suffix=extension, dir=directory)
    while os.path.exists(filepath):
        filepath = mktemp(prefix=basename, suffix=extension, dir=directory)
    return filepath


@cache_region('default_term')
def _write_file_on_disk(tmpdir, model_type, ids, filename, extension):
    """
    Return a path to a generated file

    :param str tmpdir: The path to write to
    :param str model_type: The model key we want to generate an ods file for
    :param list ids: An iterable containing all ids of models to be included in
    the output
    :param str filename: The path to the file output
    :param str extension: The desired extension (xls/ods)
    :returns: The name of the generated file (unique and temporary name)
    :rtype: str
    """
    logger.debug(" No file was cached yet")
    model = MODELS[model_type]
    query = model.query()
    if ids:
        query = query.filter(model.id.in_(ids))

    if extension == 'ods':
        writer = SqlaOdsExporter(model=model)
    elif extension == 'xls':
        writer = SqlaXlsExporter(model=model)
    elif extension == 'csv':
        writer = SqlaCsvExporter(model=model)

    writer = _add_o2m_headers_to_writer(writer, query)
    if model_type == 'userdatas':
        writer = _add_userdatas_custom_headers(writer, query)

    for item in query:
        writer.add_row(item)
        if model_type == 'userdatas':
            _add_userdatas_code_compta(writer, item)

    filepath = _get_tmp_filepath(tmpdir, filename, extension)
    logger.debug(" + Writing file to %s" % filepath)

    with open(filepath, 'w') as f_buf:
        writer.render(f_buf)

    return os.path.basename(filepath)


@celery_app.task(bind=True)
def export_to_file(self, job_id, model_type, ids, filename='test',
                   file_format='ods'):
    """
    Export the datas provided in the given query to ods format and generate a

    :param int job_id: The id of the job object used to record file_generation
    informations
    :param str model_type: The model we want to export (see MODELS)
    :param list ids: List of ids to query
    :param str filename: The filename to use for the export
    :param str file_format: The format in which we want to export
    """
    logger.info(u"Exporting to a file")
    logger.info(u" + model_type : %s", model_type)
    logger.info(u" + ids : %s", ids)

    from autonomie_base.models.base import DBSESSION
    job = utils.get_job(self.request, FileGenerationJob, job_id)
    if job is None:
        return

    tmpdir = _get_tmp_directory_path()

    try:
        result_filename = _write_file_on_disk(
            tmpdir,
            model_type,
            ids,
            filename,
            file_format,
        )
        logger.debug(u" -> The file %s been written", result_filename)
        job.status = 'completed'
        job.filename = result_filename
        DBSESSION().merge(job)
    except:
        logger.exception("Error while generating ods file")
        errors = [GENERATION_ERROR_MESSAGE % job_id]
        utils.record_failure(
            FileGenerationJob, job_id, self.request.id,  errors
        )
    else:
        transaction.commit()
        logger.info(u"The transaction has been commited")
        logger.info(u"* Task SUCCEEDED !!!")

    return ""
