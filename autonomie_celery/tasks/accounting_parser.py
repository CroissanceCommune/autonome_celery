# -*- coding: utf-8 -*-
# * Authors:
#       * TJEBBES Gaston <g.t@majerti.fr>
#       * Arezki Feth <f.a@majerti.fr>;
#       * Miotte Julien <j.m@majerti.fr>;
"""
Accounting operations parsing

Parses :

    csv files
    slk files

1- Collect the administration mail address
2- Check the filename
3- Parse with csv or with SylkParser
"""
import datetime
import os
import re
import transaction
import hashlib

from sylk_parser import SylkParser

from pyramid_celery import celery_app
from autonomie_base.mail import send_mail
from autonomie_base.utils import csv_tools
from autonomie_base.models.base import DBSESSION
from autonomie_base.utils.math import convert_to_float
from autonomie.models.config import get_admin_mail
from autonomie.models.company import Company
from autonomie.models.accounting.operations import (
    AccountingOperationUpload,
    AccountingOperation,
)
from autonomie_celery.tasks import utils
from autonomie_celery.tasks.accounting_measure_compute import (
    compile_measures,
)


logger = utils.get_logger(__name__)


def _get_registry():
    return celery_app.conf['PYRAMID_REGISTRY']


def _get_base_path():
    """
    Retreive the base working path as configured in the ini file
    """
    return _get_registry().settings['autonomie.parsing_pool_parent']


def _get_path(directory):
    """
    Return the abs path for the given directory

    :param str directory: The directory name pool/error/processed
    :rtype: str
    """
    return os.path.join(_get_base_path(), directory)


def _get_file_path_from_pool(pool_path):
    """
    Handle file remaining in the pool

    :param str pool_path: The pool path to look into
    :returns: The name of the first file we find in the rep
    :rtype: str
    """
    result = None
    if os.path.isdir(pool_path):
        files = os.listdir(pool_path)
        for file_ in files:
            path = os.path.join(pool_path, file_)
            if os.path.isfile(path):
                result = path
                break
    return result


def _get_md5sum(file_path,  blocksize=65536):
    """
    Return a md5 sum of the given file_path informations
    """
    hash = hashlib.md5()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(blocksize), b""):
            hash.update(block)
    return hash.hexdigest()


def _mv_file(file_path, queue='processed'):
    """
    Move the file to the processed directory
    """
    if os.path.isfile(file_path):
        new_dir = _get_path('processed')
        new_file_path = os.path.join(new_dir, os.path.basename(file_path))
        os.system('mv "{0}" "{1}"'.format(file_path, new_file_path))
        logger.info("The file {0} has been moved to the {1} directory".format(
            file_path,
            new_dir,
        ))


class KnownError(Exception):
    pass


class Parser(object):
    _supported_extensions = ('.csv', '.slk')
    _filenames_re = re.compile(
        r'(?P<year>[0-9]+)'
        '_(?P<month>[^_]+)'
        '_(?P<day>[^_]+)'
        '_(?P<doctype>[^_]+)',
        re.IGNORECASE
    )
    quotechar = '"'
    delimiter = ','
    encoding = 'cp1252'

    def __init__(self, file_path, force=False):
        self.file_path = file_path
        self.force = force

    def _get_datas_from_file_path(self):
        base_name, extension = os.path.splitext(
            os.path.basename(self.file_path)
        )
        if extension not in self._supported_extensions:
            raise KnownError(u"L'extension du fichier est inconnue")

        re_match = self._filenames_re.match(base_name)
        if re_match is None:
            raise KnownError(
                u"Le fichier ne respecte pas la nomenclature de nom supportée"
                u" par Autonomie ex : '2017_12_01_tresorerie.slk'"
            )
        result = re_match.groupdict()
        result['date'] = datetime.date(
            int(result['year']), int(result['month']), int(result['day'])
        )
        result['extension'] = extension[1:]
        result['md5sum'] = _get_md5sum(self.file_path)
        return result

    def _get_stream_from_slk(self):
        """
        Stream the datas coming from a slk file
        :returns: An iterator for the sheet's lines
        """
        return SylkParser(self.file_path)

    def _get_stream_from_csv(self):
        """
        Stream csv datas
        :returns: An iterator of sheet lines as lists
        """
        with open(self.file_path) as fbuf:
            for line in csv_tools.UnicodeReader(
                fbuf, quotechar=self.quotechar, delimiter=self.delimiter,
                encoding=self.encoding,
            ):
                yield line

    def _find_company_id(self, analytical_account):
        """
        Find a company object starting from its analytical_account

        :param str analytical_account: The account
        :returns: The company's id
        """
        query = DBSESSION().query(Company.id)
        query = query.filter_by(code_compta=analytical_account)
        result = query.first()
        if result is not None:
            result = result[0]
        return result

    def _build_operation(self, line_datas):
        """
        Build an AccountingOperation object

        :param dict line_datas: The streamed line datas
        """
        result = None
        if len(line_datas) >= 7:
            # If it's the headers line
            if line_datas[0] != u"Compte analytique de l'entrepreneur":
                company_id = self._find_company_id(line_datas[0])
                result = AccountingOperation(
                    analytical_account=line_datas[0],
                    general_account=line_datas[2],
                    label=line_datas[3],
                    debit=convert_to_float(line_datas[4], 0),
                    credit=convert_to_float(line_datas[5], 0),
                    balance=convert_to_float(line_datas[6], 0),
                    company_id=company_id,
                )
        else:
            if line_datas:
                logger.error(
                    u"This line is missing informations : %s" % line_datas
                )
        return result

    def _fill_db(self, file_datas):
        """
        Fill the database with datas found in the current file

        1- Init an AccountingOperationUpload
        2- Find the good parsing strategy to stream lines
        3- Fill AccountingOperation instances
            - Find the associated company (?)
            - Create new instance

        :param dict file_datas: The collected file related informations
        """
        extension = file_datas['extension']
        if extension == 'slk':
            lines = self._get_stream_from_slk()
        else:
            lines = self._get_stream_from_csv()

        upload_object = AccountingOperationUpload(
            filename=os.path.basename(self.file_path),
            date=file_datas['date'],
            md5sum=file_datas['md5sum'],
        )
        missed_associations = 0

        for line in lines:
            operation = self._build_operation(line)
            if operation is not None:
                upload_object.operations.append(operation)
                if operation.company_id is None:
                    missed_associations += 1

        return upload_object, missed_associations

    def _already_loaded(self, file_datas):
        query = DBSESSION().query(AccountingOperationUpload)
        query = query.filter_by(md5sum=file_datas['md5sum'])
        return query.count() > 0

    def _clean_old_operations(self, old_ids):
        """
        Clean old AccountingOperation entries
        :param list old_ids: The list of ids present in db before treating this
        file
        """
        logger.info(u"  + Cleaning {0} old operations".format(len(old_ids)))
        op = AccountingOperation.__table__.delete().where(
            AccountingOperation.id.in_(old_ids)
        )
        op.execute()

    def _get_existing_operation_ids(self):
        """
        Return ids of the operations already stored in database
        """
        return [
            entry[0] for entry in DBSESSION().query(AccountingOperation.id)
        ]

    def process_file(self):
        file_datas = self._get_datas_from_file_path()
        if self.force or not self._already_loaded(file_datas):
            old_ids = self._get_existing_operation_ids()
            upload_object, missed_associations = self._fill_db(file_datas)
            logger.info(
                u"Storing {0} new operations in database".format(
                    len(upload_object.operations)
                )
            )
            logger.info(
                "  + {0} operations were not associated to an existing "
                "company".format(missed_associations)
            )
            DBSESSION().add(upload_object)
            DBSESSION().flush()
            if upload_object.operations and old_ids:
                self._clean_old_operations(old_ids)

            try:
                compile_measures(upload_object, upload_object.operations)
            except:
                logger.exception(u"Error while compiling measures")

            return len(upload_object.operations), missed_associations
        else:
            logger.error(u"File {0} already loaded".format(self.file_path))
            _mv_file(self.file_path)
            raise KnownError(
                u"Ce fichier a déjà été traité : {0}".format(self.file_path)
            )

MAIL_ERROR_SUBJECT = u"[ERREUR] Autonomie : traitement de votre document \
{filename}"

MAIL_ERROR_BODY = u"""Une erreur est survenue lors du traitement du
fichier {filename}:

    {error}
"""
MAIL_UNKNOWN_ERROR_BODY = u"""Une erreur inconnue est survenue lors du
traitement du fichier {filename}:

    {error}

Veuillez contacter votre administrateur
"""
MAIL_SUCCESS_SUBJECT = u"""Autonomie : traitement de votre document {0}"""
MAIL_SUCCESS_BODY = u"""Le fichier {0} a été traité avec succès.
Écritures générées : {1}
Écritures n'ayant pas pu être associées à une entreprise existante dans
Autonomie : {2}

Les indicateurs ont été générés depuis ces écritures.
"""


def send_error(request, mail_address, filename, err):
    message = MAIL_ERROR_BODY.format(
        error=err.message,
        filename=filename
    )
    subject = MAIL_ERROR_SUBJECT.format(filename=filename)
    send_mail(
        request,
        mail_address,
        message,
        subject,
    )


def send_unknown_error(request, mail_address, filename, err):
    subject = MAIL_ERROR_SUBJECT.format(filename=filename)
    message = MAIL_UNKNOWN_ERROR_BODY.format(
        error=err.message,
        filename=filename
    )
    send_mail(
        request,
        mail_address,
        message,
        subject,
    )


def send_success(request, mail_address, filename, new_entries, missing):
    subject = MAIL_SUCCESS_SUBJECT.format(filename)
    message = MAIL_SUCCESS_BODY.format(
        filename,
        new_entries,
        missing,
    )
    send_mail(
        request,
        mail_address,
        message,
        subject,
    )


@celery_app.task(bind=True)
def handle_pool_task(self):
    """
    Parse the files present in the configured file pool
    """
    pool_path = _get_path('pool')
    file_to_parse = _get_file_path_from_pool(pool_path)
    if file_to_parse is None:
        return
    else:
        logger.debug("Parsing a new file")
        mail_address = get_admin_mail()
        if mail_address:
            setattr(self.request, "registry", _get_registry())
            filename = os.path.basename(file_to_parse)
        parser = Parser(file_to_parse)
        transaction.begin()
        try:
            num_operations, missed_associations = parser.process_file()
        except KnownError as err:
            transaction.abort()
            logger.exception(u"KnownError : %s" % err.message)
            if mail_address:
                send_error(self.request, mail_address, filename, err)
            _mv_file(file_to_parse, 'error')
        except Exception as err:
            transaction.abort()
            logger.exception(u"Unkown Error")
            if mail_address:
                send_unknown_error(self.request, mail_address, filename, err)
            _mv_file(file_to_parse, 'error')
        else:
            transaction.commit()
            logger.info(u"The transaction has been commited")
            logger.info(u"* Task SUCCEEDED !!!")
            if mail_address:
                send_success(
                    self.request,
                    mail_address,
                    filename,
                    num_operations,
                    missed_associations,
                )
            _mv_file(file_to_parse)
