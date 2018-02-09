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

- Collect the administration mail address
- Inspect the pool for waiting files
- Find the parser and the filetype
- Parse
    - Collect file informations
    - Ensure we have csv datas
    - Insert lines in database

"""
import datetime
import os
import re
import transaction
import hashlib

from sylk_parser import SylkParser

from pyramid_celery import celery_app
from autonomie_base.mail import send_mail
from autonomie_base.utils import csv_tools, date as date_utils
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
    get_measure_compiler
)


logger = utils.get_logger(__name__)
FILENAME_ERROR = (
    u"Le fichier ne respecte pas la nomenclature de nom "
    u"supportée par Autonomie ex : \n"
    u" Pour les états de trésorerie : "
    u"'2017_12_01_balance_analytique.slk'.\n"
    u"Pour les comptes de résultat : \n"
    u"2017_12_resultat.slk",
)


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
        new_dir = _get_path(queue)
        new_file_path = os.path.join(new_dir, os.path.basename(file_path))
        os.system('mv "{0}" "{1}"'.format(file_path, new_file_path))
        logger.info("The file {0} has been moved to the {1} directory".format(
            file_path,
            new_dir,
        ))


def _clean_old_operations(old_ids):
    """
    Clean old AccountingOperation entries
    :param list old_ids: The ids of items to remove
    """
    logger.info(u"  + Cleaning {0} old operations".format(len(old_ids)))
    op = AccountingOperation.__table__.delete().where(
        AccountingOperation.id.in_(old_ids)
    )
    op.execute()


class KnownError(Exception):
    pass


class AccountingDataParser(object):
    """
    Base Accounting datas parser
    """
    _supported_extensions = ('csv', 'slk')
    quotechar = '"'
    delimiter = ','
    encoding = 'utf-8'

    # To be filled in subclasses
    _filename_re = None
    filetype = None

    def __init__(self, file_path, force=False):
        self.file_path = file_path
        self.force = force
        self._file_datas = {}
        self._collect_main_file_infos()
        self.basename = self._file_datas['basename']
        if hasattr(self, '_collect_specific_file_infos'):
            self._collect_specific_file_infos()

    @classmethod
    def match(cls, filename):
        """
        Return True if the current parser should be able to handle that type of
        file
        """
        re_match = cls._filename_re.match(filename)
        return re_match is not None

    def _collect_main_file_infos(self):
        """
        Collect main informations about the current file

        basename extension (without the leading dot) md5sum
        :returns: A dict containing collected datas
        :rtype: dict
        """
        basename, extension = os.path.splitext(
            os.path.basename(self.file_path)
        )
        if extension:
            extension = extension[1:]
        if extension not in self._supported_extensions:
            raise KnownError(u"L'extension du fichier est inconnue")

        self._file_datas['basename'] = basename
        self._file_datas['extension'] = extension
        self._file_datas['md5sum'] = _get_md5sum(self.file_path)
        self._file_datas['filetype'] = self.filetype
        return self._file_datas

    def _stream_slk(self):
        """
        Stream the datas coming from a slk file
        :returns: An iterator for the sheet's lines
        """
        return SylkParser(self.file_path, use_unicode=True)

    def _stream_csv(self):
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

    def _stream_datas(self):
        """
        Stream the datas coming from a slk file
        :returns: An iterator for the sheets line
        """
        extension = self._file_datas['extension']

        func = getattr(self, "_stream_%s" % extension, None)
        if func is not None:
            for line in func():
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

    def _build_operation_upload_object(self):
        """
        Build an AccountingOperationUpload instance with current file datas

        :returns: An AccountingOperationUpload for the current parsed file
        """
        return AccountingOperationUpload(
            filename=os.path.basename(self.file_path),
            date=self._file_datas['date'],
            md5sum=self._file_datas['md5sum'],
            filetype=self._file_datas['filetype'],
        )

    def _build_operation(self, line_datas):
        """
        Build an AccountingOperation with the given line datas

        :param list line_datas: List of datas found in the line
        :returns: An instance of AccountingOperation
        """
        raise NotImplemented(
            u"_build_operation should be implemented in subclasses"
        )

    def _build_operations(self):
        """
        Build AccountingOperation based on the current file's datas

        :returns: A 2-uple with operations and number of missed associations
        :rtype: tuple (list, int)
        """
        operations = []
        missed_associations = 0
        for line in self._stream_datas():
            operation = self._build_operation(line)
            if operation is not None:
                operations.append(operation)
                if operation.company_id is None:
                    missed_associations += 1
        return operations, missed_associations

    def _already_loaded(self):
        """
        Check if the current file has already been loaded

        :rtype: bool
        """
        query = DBSESSION().query(AccountingOperationUpload.id)
        query = query.filter_by(md5sum=self._file_datas['md5sum'])
        return query.count() > 0

    def _get_existing_operation_ids(self):
        """
        Return ids of the operations already stored in database
        """
        return [
            entry[0] for entry in DBSESSION().query(AccountingOperation.id)
        ]

    def _get_num_val(self, line, index):
        """
        Retreieve the numeric value found at index in the line_datas list

        :param list line: List of datas coming from parsed file
        :param int index: The index in which we should retrieve the datas
        """
        result = 0
        if len(line) > index:
            result = line[index].strip() or 0
        return result

    def process_file(self):
        """
        Process file parsing

        :returns: The new AccountingOperationUpload instance and the number of
        missed associations (lines where we didn't found any matching company)
        :rtype: 2-uple
        """
        if self.force or not self._already_loaded():
            old_ids = self._get_existing_operation_ids()
            upload_object = self._build_operation_upload_object()
            operations, missed_associations = self._build_operations()
            logger.info(
                u"Storing {0} new operations in database".format(
                    len(operations)
                )
            )
            logger.info(
                "  + {0} operations were not associated to an existing "
                "company".format(missed_associations)
            )
            if operations:
                upload_object.operations = operations
            else:
                old_ids = []

            DBSESSION().add(upload_object)
            DBSESSION().flush()

            return upload_object.id, missed_associations, old_ids

        else:
            logger.error(u"File {0} already loaded".format(self.file_path))
            raise KnownError(
                u"Ce fichier a déjà été traité : {0}".format(self.file_path)
            )


class GeneralLedgerParser(AccountingDataParser):
    _filename_re = re.compile(
        'general_ledger_'
        '(?P<year>[0-9]+)'
        '_(?P<month>[^_]+)'
        '_(?P<doctype>[^_]+)',
        re.IGNORECASE
    )
    filetype = 'general_ledger'

    def _collect_specific_file_infos(self):
        """
        Return specific file info
        """
        re_match = self._filename_re.match(self.basename)
        if re_match is None:
            raise KnownError(FILENAME_ERROR)

        logger.info(u"It's an General Ledger file")
        self._file_datas.update(re_match.groupdict())
        self._file_datas['date'] = datetime.date(
            int(self._file_datas['year']), int(self._file_datas['month']), 1
        )
        return self._file_datas

    def _build_operation(self, line_datas):
        """
        Build an AccountingOperation object

        :param list line_datas: List of datas found in the line
        :returns: An instance of AccountingOperation
        """
        result = None
        if len(line_datas) >= 6:
            if line_datas[0].strip() not in (
                u"Compte analytique de l'entrepreneur",
                u"Numéro analytique",
            ):
                analytical_account = line_datas[0].strip()
                general_account = line_datas[1].strip()
                date = date_utils.str_to_date(line_datas[2].strip())
                if not date:
                    logger.error(
                        u"This line has incorrect datas : %s" % line_datas
                    )
                    return None
                label = line_datas[5].strip()
                debit = self._get_num_val(line_datas, index=6)
                credit = self._get_num_val(line_datas, index=7)
                balance = 0
                company_id = self._find_company_id(analytical_account)
                result = AccountingOperation(
                    analytical_account=analytical_account,
                    general_account=general_account,
                    date=date,
                    label=label,
                    debit=convert_to_float(debit),
                    credit=convert_to_float(credit),
                    balance=convert_to_float(balance),
                    company_id=company_id,
                )
        else:
            if line_datas:
                logger.error(
                    u"This line is missing informations : %s" % line_datas
                )
        return result


class AnalyticalBalanceParser(AccountingDataParser):
    _filename_re = re.compile(
        'analytical_balance_'
        '(?P<year>[0-9]+)'
        '_(?P<month>[0-9]+)'
        '_(?P<day>[0-9]+)'
        '_(?P<doctype>[^_]+)',
        re.IGNORECASE
    )
    filetype = 'analytical_balance'

    def _collect_specific_file_infos(self):
        """
        Collect key datas from the file path
        """
        re_match = self._filename_re.match(self.basename)
        if re_match is None:
            raise KnownError(FILENAME_ERROR)

        logger.info(u"It's an Analytical Balance file")
        self._file_datas.update(re_match.groupdict())
        self._file_datas['date'] = datetime.date(
            int(self._file_datas['year']),
            int(self._file_datas['month']),
            int(self._file_datas['day']),
        )

        return self._file_datas

    def _build_operation(self, line_datas):
        """
        Build an AccountingOperation object

        :param list line_datas: List of datas found in the line
        :returns: An instance of AccountingOperation
        """
        result = None
        if len(line_datas) >= 5:
            if line_datas[0] not in (
                u"Compte analytique de l'entrepreneur",
                u"Numéro analytique",
            ):
                analytical_account = line_datas[0].strip()
                general_account = line_datas[2].strip()
                label = line_datas[3].strip()
                debit = self._get_num_val(line_datas, index=4)
                credit = self._get_num_val(line_datas, index=5)
                balance = self._get_num_val(line_datas, index=6)
                company_id = self._find_company_id(analytical_account)
                result = AccountingOperation(
                    analytical_account=analytical_account,
                    general_account=general_account,
                    label=label,
                    debit=convert_to_float(debit),
                    credit=convert_to_float(credit),
                    balance=convert_to_float(balance),
                    company_id=company_id,
                )
        else:
            if line_datas:
                logger.error(
                    u"This line is missing informations : %s" % line_datas
                )
        return result


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
    if mail_address:
        try:
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
        except:
            logger.exception("send_success error")


def send_unknown_error(request, mail_address, filename, err):
    if mail_address:
        try:
            subject = MAIL_ERROR_SUBJECT.format(filename=filename)
            print(err.message)
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
        except:
            logger.exception("send_success error")


def send_success(request, mail_address, filename, new_entries, missing):
    if mail_address:
        try:
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
        except:
            logger.exception("send_success error")


def _get_parser_factory(filename):
    """
    Find out which type of file we handle and return the associated parser

    :param str filename: The filename of the file to parse
    """
    result = None
    # ATtention l'ordre est important (le deuxième matche les fichiers qui
    # doivent être traités par le premier, mais pas l'inverse)
    for parser in (AnalyticalBalanceParser, GeneralLedgerParser):
        if parser.match(filename):
            result = parser
            break
    return result


@celery_app.task(bind=True)
def handle_pool_task(self, force=False):
    """
    Parse the files present in the configured file pool
    """
    pool_path = _get_path('pool')
    file_to_parse = _get_file_path_from_pool(pool_path)

    if file_to_parse is None:
        return

    else:
        logger.info(u"Parsing an accounting file : %s" % file_to_parse)
        mail_address = get_admin_mail()
        if mail_address:
            setattr(self.request, "registry", _get_registry())

        filename = os.path.basename(file_to_parse)
        parser_factory = _get_parser_factory(filename)
        if parser_factory is None:
            err = Exception("Type de fichier inconnu")
            send_error(self.request, mail_address, filename, err)
            logger.error(u"Incorrect file type : %s" % filename)
            _mv_file(file_to_parse, "error")
            return False
        try:
            parser = parser_factory(file_to_parse, force)

            transaction.begin()
            logger.info(u"  + Storing accounting operations in database")
            upload_object_id, missed_associations, old_ids = \
                parser.process_file()
            logger.debug(u"  + File was processed")
            transaction.commit()
        except KnownError as err:
            transaction.abort()
            logger.exception(u"KnownError : %s" % err.message)
            logger.exception(u"* FAILED : transaction has been rollbacked")
            if mail_address:
                send_error(self.request, mail_address, filename, err)
                logger.error(
                    u"An error mail has been sent to {0}".format(mail_address)
                )
            _mv_file(file_to_parse, 'error')
            logger.error(u"File has been moved to error directory")
            return False

        except Exception as err:
            transaction.abort()
            logger.exception(u"Unkown Error")
            logger.exception(u"* FAILED : transaction has been rollbacked")
            if mail_address:
                send_unknown_error(self.request, mail_address, filename, err)
                logger.error(
                    u"An error mail has been sent to {0}".format(mail_address)
                )
            _mv_file(file_to_parse, 'error')
            logger.error(u"File has been moved to error directory")
            return False

        else:
            logger.info(u"Accounting operations where successfully stored")
            _mv_file(file_to_parse)
            logger.info(u"File has been moved to processed directory")

        if old_ids:
            transaction.begin()
            logger.info("  + Cleaning %s old operations" % len(old_ids))
            try:
                _clean_old_operations(old_ids)
                transaction.commit()
            except:
                transaction.abort()
                logger.exception(u"Error while cleaning old operations")
            else:
                logger.info(u" * Old datas cleaned successfully")

        transaction.begin()
        logger.info(u" + Compiling the measures")
        # On rafraichit l'objet car nous sommes dans une nouvelle transaction
        # on évite ainsi le problème de "is not bound to a Session"
        upload_object = AccountingOperationUpload.get(upload_object_id)
        num_operations = len(upload_object.operations)

        logger.debug(" + Retrieved the upload object %s" % upload_object.date)
        logger.debug(" + %s operations" % num_operations)

        measure_compiler_factory = get_measure_compiler(parser.filetype)

        try:
            measure_compiler = measure_compiler_factory(
                upload_object, upload_object.operations
            )
            measure_compiler.process_datas()
            transaction.commit()
        except KnownError as err:
            transaction.abort()
            logger.exception(u"KnownError : %s" % err.message)
            if mail_address:
                send_error(self.request, mail_address, filename, err)
                logger.error(
                    u"An error mail has been sent to {0}".format(mail_address)
                )
            logger.exception(u"* FAILED : transaction has been rollbacked")
            return False

        except Exception as err:
            transaction.abort()
            logger.exception(u"Unkown Error")
            if mail_address:
                send_unknown_error(self.request, mail_address, filename, err)
                logger.error(
                    u"An error mail has been sent to {0}".format(mail_address)
                )
            logger.exception(u"* FAILED : transaction has been rollbacked")
            return False

        else:
            logger.info(u"Measure computing transaction has been commited")
            logger.info(u"* SUCCEEDED !!!")

            if mail_address:
                send_success(
                    self.request,
                    mail_address,
                    filename,
                    num_operations,
                    missed_associations,
                )
                logger.info(
                    u"A success email has been sent to {0}".format(mail_address)
                )
