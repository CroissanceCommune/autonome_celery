# -*- coding: utf-8 -*-
# * Copyright (C) 2012-2014 Croissance Commune
# * Authors:
#       * Arezki Feth <f.a@majerti.fr>;
#       * Miotte Julien <j.m@majerti.fr>;
#       * TJEBBES Gaston <g.t@majerti.fr>
#
# This file is part of Autonomie : Progiciel de gestion de CAE.
#
#    Autonomie is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    Autonomie is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with Autonomie.  If not, see <http://www.gnu.org/licenses/>.
"""
Celery tasks related models
"""
import os
import hashlib
from datetime import (
    datetime,
    timedelta,
)
from pyramid.security import (
    Allow,
)
from sqlalchemy import (
    Integer,
    Column,
    ForeignKey,
    String,
    DateTime,
    Text,
)
from autonomie_base.models.types import (
    JsonEncodedList,
    PersistentACLMixin,
    ACLType,
    MutableList,
)
from autonomie_base.models.base import (
    DBBASE,
    default_table_args,
)
from sqlalchemy.orm import (
    relationship,
)


TIMEOUT = timedelta(seconds=10000)


class Job(DBBASE, PersistentACLMixin):
    """
    Base job model, used to communicate a job's status between the main pyramid
    app and celery asynchronous tasks
    """
    __tablename__ = 'job'
    __table_args__ = default_table_args
    __mapper_args__ = {
        'polymorphic_on': 'type_',
        'polymorphic_identity': 'job',
    }
    label = u"Tâche générique"
    id = Column(
        Integer,
        primary_key=True,
    )
    jobid = Column(
        String(255),
        nullable=True,
    )
    status = Column(
        String(20),
        default='planned',
    )
    created_at = Column(
        DateTime(),
        default=datetime.now,
    )
    updated_at = Column(
        DateTime(),
        default=datetime.now,
        onupdate=datetime.now
    )
    type_ = Column(
        'type_',
        String(30),
        nullable=False,
    )
    _acl = Column(
        MutableList.as_mutable(ACLType),
    )

    def todict(self):
        return dict(
            label=self.label,
            jobid=self.jobid,
            status=self.status,
            created_at=self.created_at.strftime("%d/%m/%Y à %H:%M"),
            updated_at=self.updated_at.strftime("%d/%m/%Y à %H:%M"),
        )

    def __json__(self, request):
        return self.todict()

    def set_owner(self, login):
        """
        Set the job owner's acls
        """
        self._acl = [(Allow, login, ('add', 'edit', 'view',))]

    def timeout(self):
        """
        Check if this element should be timeouted
        """
        result = True
        if self.status in ('planned', 'running'):
            if datetime.now() - self.updated_at > TIMEOUT:
                self.status = u"failed"
                if hasattr(self, 'error_messages'):
                    self.error_messages = [
                        u"Cette tâche a été automatiquement annulée car elle "
                        u"n'a pas pu être traitée. Veulliez contacter un "
                        u"administrateur en lui fournissant l'identifiant de "
                        u"tâche suivant : {0}".format(self.id)
                    ]
                result = False
        return result


class CsvImportJob(Job):
    """
    Store csv importation job status
    """
    __tablename__ = 'csv_import_job'
    __table_args__ = default_table_args
    __mapper_args__ = {'polymorphic_identity': 'csv_import'}
    id = Column(Integer, ForeignKey('job.id'), primary_key=True)
    messages = Column(JsonEncodedList, default=None)
    error_messages = Column(JsonEncodedList, default=None)
    in_error_csv = Column(Text(), default=None)
    unhandled_datas_csv = Column(Text(), default=None)
    label = u"Import de données"

    def is_not_void_str(self, value):
        """
        Return True if the string contains datas
        """
        return not (value is None or len(value) == 0)

    def todict(self):
        res = Job.todict(self)
        res['label'] = self.label
        res['messages'] = self.messages
        res['error_messages'] = self.error_messages
        res['has_errors'] = self.is_not_void_str(self.in_error_csv)
        res['has_unhandled_datas'] = self.is_not_void_str(
            self.unhandled_datas_csv
        )
        return res


class MailingJob(Job):
    """
    Store mailing job status
    """
    __tablename__ = 'mailing_job'
    __table_args__ = default_table_args
    __mapper_args__ = {'polymorphic_identity': 'mailing'}
    id = Column(Integer, ForeignKey('job.id'), primary_key=True)
    messages = Column(JsonEncodedList, default=None)
    error_messages = Column(JsonEncodedList, default=None)
    label = u"Envoi de mail"

    def todict(self):
        res = Job.todict(self)
        res['label'] = self.label
        res['messages'] = self.messages
        res['error_messages'] = self.error_messages
        return res


class FileGenerationJob(Job):
    __tablename__ = 'file_generation_job'
    __table_args__ = default_table_args
    __mapper_args__ = {'polymorphic_identity': 'file_generation'}
    id = Column(Integer, ForeignKey('job.id'), primary_key=True)
    filename = Column(Text)
    error_messages = Column(JsonEncodedList, default=None)
    label = u"Génération de fichier"

    def todict(self):
        res = Job.todict(self)
        res['filename'] = self.filename
        res['error_messages'] = self.error_messages
        return res


class MailHistory(DBBASE):
    """
    Stores the history of mail sent by our application to any company
    """
    __tablename__ = 'mail_history'
    __table_args__ = default_table_args
    id = Column(Integer, primary_key=True)
    send_at = Column(
        DateTime(),
        default=datetime.now,
    )

    filepath = Column(String(255))
    md5sum = Column(String(100))
    company_id = Column(ForeignKey('company.id'), nullable=True)
    company = relationship(
        "Company",
    )

    @property
    def filename(self):
        return os.path.basename(self.filepath)


def store_sent_mail(filepath, filedatas, company_id):
    """
    Stores a sent email in the history

    :param filename: The path to the sent file
    :param filedatas: The file datas
    :param int company_id: the id of a company instance
    """
    mail_history = MailHistory(
        filepath=filepath,
        md5sum=hashlib.md5(filedatas).hexdigest(),
        company_id=company_id
    )
    return mail_history


def check_if_mail_sent(filedatas, company_id):
    """
    Check if the given file has already been sent
    :param str filedatas: The content of a file
    :param int company_id: The id of a company
    """
    query = MailHistory.query()
    query = query.filter(MailHistory.company_id == company_id)
    md5sum = hashlib.md5(filedatas).hexdigest()
    query = query.filter(MailHistory.md5sum == md5sum)
    return query.first() is not None
