# -*- coding: utf-8 -*-
# * Authors:
#       * TJEBBES Gaston <g.t@majerti.fr>
#       * Arezki Feth <f.a@majerti.fr>;
#       * Miotte Julien <j.m@majerti.fr>;
import logging
from pyramid_mailer.message import (
    Attachment,
)

from autonomie_base.exception import (
    MailAlreadySent,
    UndeliveredMail,
)
from autonomie_base.mail import send_mail
from autonomie_celery.models import (
    store_sent_mail,
    check_if_mail_sent,
)


logger = logging.getLogger(__name__)


SALARYSHEET_MAIL_MESSAGE = u"""Bonjour,
Vous trouverez ci-joint votre bulletin de salaire.
"""

SALARYSHEET_MAIL_SUBJECT = u"Votre bulletin de salaire"


def send_salary_sheet(
    request, email, company_id, filename, filepath, force=False,
    message=None, subject=None
):
    """
    Send a salarysheet to the given company's e-mail

    :param obj request: A pyramid request object
    :param str company_mail: The mail to send it to
    :param int company_id: The id of the associated company
    :param str filepath: The path to the filename
    :param bool force: Whether to force sending this file again
    :param str message: The mail message
    :param str subject: The mail subject
    :returns: A MailHistory instance
    :TypeError UndeliveredMail: When the company has no mail
    :TypeError MailAlreadySent: if the file has
        already been sent and no force option was passed
    """
    filebuf = file(filepath, 'r')
    filedatas = filebuf.read()

    if not force and check_if_mail_sent(filedatas, company_id):
        logger.warn(u"Mail already sent : mail already sent")
        raise MailAlreadySent(u"Mail already sent")

    filebuf.seek(0)

    if email is None:
        logger.warn(
            u"Undelivered email : no mail provided for company {0}".format(
                company_id
            )
        )
        raise UndeliveredMail(u"no mail provided for company {0}".format(
            company_id)
        )
    else:
        logger.info('Sending the file %s' % filepath)
        logger.info("Sending it to %s" % email)
        attachment = Attachment(filename, "application/pdf", filebuf)

        subject = subject or SALARYSHEET_MAIL_SUBJECT
        message = message or SALARYSHEET_MAIL_MESSAGE

        send_mail(
            request,
            email,
            message,
            subject,
            attachment,
        )
        return store_sent_mail(filepath, filedatas, company_id)
