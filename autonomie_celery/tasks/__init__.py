# -*- coding: utf-8 -*-
# * Authors:
#       * TJEBBES Gaston <g.t@majerti.fr>
#       * Arezki Feth <f.a@majerti.fr>;
#       * Miotte Julien <j.m@majerti.fr>;

from sqlalchemy import (
    desc,
    func,
)

from autonomie_base.utils.renderers import configure_export
from autonomie.utils.strings import format_amount
from autonomie.models.user import UserDatas
from autonomie.models.customer import Customer
from autonomie.models.tva import Tva
from autonomie.models.task import Task


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


def _add_invoice_custom_headers(writer, invoices):
    """
    Invoice export headers

    * Entreprise ;
    • Client ;
    • Date ;
    • Numéro de factures ;
    • Objet ;
    • Lieu des travaux ;
    • HT (par taux de tva) ;
    • TVA (par taux de tva) ;
    • TTC.
    """
    for tva in Tva.query():
        writer.add_extra_header({
            'label': u"HT {tva.name}".format(tva=tva),
            "name": u"HT {tva.value}".format(tva=tva),
        })
        writer.add_extra_header({'label': tva.name, "name": tva.value})

    writer.add_extra_header({'label': u"Montat TTC", "name": "ttc"})
    return writer


def _add_invoice_datas(writer, invoice):
    ht_values = invoice.tva_ht_parts()
    tva_values = invoice.get_tvas()
    datas = []
    for tva in Tva.query():
        datas.append(
            format_amount(
                ht_values.get(tva.value, 0),
                precision=5,
                trim=False,
                grouping=False,
            )
        )
        datas.append(
            format_amount(
                tva_values.get(tva.value, 0),
                precision=5,
                trim=False,
                grouping=False,

            )
        )
    datas.append(
        format_amount(
            invoice.ttc,
            precision=5,
            trim=False,
            grouping=False
        )
    )
    writer.add_extra_datas(datas)
    return writer


def includeme(config):
    configure_export()
    config.register_import_model(
        key='userdatas',
        model=UserDatas,
        label=u"Données de gestion sociale",
        permission='admin_userdatas',
        excludes=(
            'name',
            'created_at',
            'updated_at',
            'type_',
            '_acl',
            'parent_id',
            'parent',
        )
    )
    config.register_import_model(
        key='customers',
        model=Customer,
        label=u"Clients",
        permission='add_customer',
        excludes=(
            'created_at',
            'updated_at',
            'company_id',
            'company',
        ),
    )

    config.register_export_model(
        key='userdatas',
        model=UserDatas,
        options={
            'hook_init': _add_userdatas_custom_headers,
            'hook_add_row': _add_userdatas_code_compta,
            'foreign_key_name': 'userdatas_id',
        }
    )

    config.register_export_model(
        key='invoices',
        model=Task,
        options={
            'hook_init': _add_invoice_custom_headers,
            'hook_add_row': _add_invoice_datas,
            'foreign_key_name': 'task_id',
            'excludes': ('name', 'created_at', 'updated_at', 'type_'),
            'order': (
                'company',
                'customer',
                'date',
                'official_number',
                'description',
                'workplace',
            )
        }
    )
