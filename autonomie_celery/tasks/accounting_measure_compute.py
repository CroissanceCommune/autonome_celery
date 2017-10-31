# -*- coding: utf-8 -*-
# * Authors:
#       * TJEBBES Gaston <g.t@majerti.fr>
#       * Arezki Feth <f.a@majerti.fr>;
#       * Miotte Julien <j.m@majerti.fr>;
"""
Tasks used to compile treasury measures
"""
import transaction

from pyramid_celery import celery_app
from autonomie_base.models.base import DBSESSION
from autonomie.models.accounting.operations import (
    AccountingOperationUpload,
    AccountingOperation,
)
from autonomie.models.accounting.measures import (
    TreasuryMeasure,
    TreasuryMeasureGrid,
    TreasuryMeasureType,
)

from autonomie_celery.tasks import utils


logger = utils.get_logger(__name__)



def collect_main_measure_types():
    """
    Collect the configured TreasuryMeasureType
    """
    return TreasuryMeasureType.query()


def get_new_grid(upload, company_id):
    """
    Build a new grid based on the given upload

    :param obj upload: A AccountingOperationUpload instance
    :param int company_id: The associated company
    """
    return TreasuryMeasureGrid(
        date=upload.date,
        company_id=company_id,
        upload=upload,
    )


def get_existing_grids(upload):
    """
    Collect grids already built on the given upload
    """
    grids = {}
    for grid in TreasuryMeasureGrid.query().filter_by(upload_id=upload.id):
        grids[grid.company_id] = grid
    return grids


def get_new_measure(label, grid_id, measure_type_id=None):
    """
    Build a new measure
    """
    session = DBSESSION()
    measure = TreasuryMeasure(
        label=label,
        grid_id=grid_id,
        measure_type_id=measure_type_id,
    )
    session.add(measure)
    session.flush()
    return measure


def get_existing_measures(grids):
    """
    Build the measures dict based on the given existing grids
    Also reset all values to 0
    """
    result = {}
    for grid in grids.values():
        company_measures = result[grid.company_id] = {}
        for measure in grid.measures:
            measure.value = 0
            company_measures[measure.measure_type_id] = measure
    return result


def compile_measures(upload, operations):
    """
    Compile measures based on the given operations

    :param obj upload: A AccountingOperationUpload instance
    :param list operations: The associated AccountingOperation
    """
    session = DBSESSION()
    measure_types = collect_main_measure_types()

    # Stores grids : {'company1_id': <TreasuryMeasureGrid>}
    grids = get_existing_grids(upload)

    # Stores built measures {'company1_id': {'measure1_id': object,
    # 'measure2_id': instance}, ...}
    measures = get_existing_measures(grids)

    for operation in operations:
        if operation.company_id is None:
            continue

        grid = grids.get(operation.company_id)
        if grid is None:
            grid = grids[operation.company_id] = get_new_grid(
                upload,
                operation.company_id
            )
            session.add(grid)
            session.flush()

        company_measures = measures.get(operation.company_id)
        if company_measures is None:
            company_measures = measures[operation.company_id] = {}

        matched = False
        for measure_type in measure_types:
            if measure_type.match(operation.general_account):
                measure = company_measures.get(measure_type.id)
                if measure is None:
                    measure = get_new_measure(
                        measure_type.label,
                        grid.id,
                        measure_type.id
                    )
                    company_measures[measure_type.id] = measure

                measure.value += operation.total()
                matched = True

        if matched:
            session.merge(measure)
    return grids


@celery_app.task(bind=True)
def compile_measures_task(self, upload_id, operation_ids):
    """
    Celery task handling measures compilation
    """
    logger.info(
        u"Launching the compile measure task for upload {0}".format(upload_id)
    )
    transaction.begin()
    upload = AccountingOperationUpload.get(upload_id)
    operations = AccountingOperation.query().filter_by(
        upload_id=upload_id
    ).all()
    try:
        grids = compile_measures(upload, operations)
    except:
        transaction.abort()
    else:
        transaction.commit()
        logger.info(u"{0} measure grids were handled".format(len(grids)))
        logger.info(u"The transaction has been commited")
        logger.info(u"* Task SUCCEEDED !!!")
