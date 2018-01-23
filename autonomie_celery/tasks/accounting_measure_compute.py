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
from autonomie.models.accounting.treasury_measures import (
    TreasuryMeasure,
    TreasuryMeasureGrid,
    TreasuryMeasureType,
)
from autonomie.models.accounting.general_ledger_measures import (
    GeneralLedgerMeasure,
    GeneralLedgerMeasureGrid,
    GeneralLedgerMeasureType,
)

from autonomie_celery.tasks import utils


logger = utils.get_logger(__name__)


class BaseMeasureCompiler(object):
    """
    Base measure compiler
    """
    measure_type_class = None
    measure_grid_class = None
    measure_class = None

    def __init__(self, upload, operations):
        self.upload = upload
        self.operations = operations
        self.session = DBSESSION()

        self.measure_types = self._collect_measure_types()

        self.grids = self._get_existing_grids()
        self.measures = self._get_existing_measures(self.grids)

    def _collect_measure_types(self):
        return self.measure_type_class.query().filter_by(active=True)

    def _get_existing_grids(self):
        """
        Collect grids already built on the given upload (for each company)

        :returns: dict {'company_id': <Type>MeasureGrid}
        """
        # Stores grids : {'company1_id': <TreasuryMeasureGrid>}
        grids = {}
        for grid in self.measure_grid_class.query().filter_by(
            upload_id=self.upload.id
        ):
            grids[grid.company_id] = grid
        return grids

    def _get_new_measure(self, label, grid_id, measure_type_id=None):
        """
        Build a new measure
        """
        measure = self.measure_class(
            label=label,
            grid_id=grid_id,
            measure_type_id=measure_type_id,
        )
        self.session.add(measure)
        self.session.flush()
        return measure

    def _get_existing_measures(self, grids):
        """
        Build the measures dict based on the given existing grids
        Also reset all values to 0
        """
        # Stores built measures {'company1_id': {'measure1_id': object,
        # 'measure2_id': instance}, ...}
        result = {}
        for grid in grids.values():
            company_measures = result[grid.company_id] = {}
            for measure in grid.measures:
                measure.value = 0
                company_measures[measure.measure_type_id] = measure
        return result

    def process_datas(self):
        """
        Compile measures based on the given operations
        """
        for operation in self.operations:
            if operation.company_id is None:
                continue

            grid = self.grids.get(operation.company_id)
            if grid is None:
                grid = self.grids[operation.company_id] = self._get_new_grid(
                    operation.company_id
                )
                self.session.add(grid)
                self.session.flush()

            company_measures = self.measures.get(operation.company_id)
            if company_measures is None:
                company_measures = self.measures[operation.company_id] = {}

            matched = False
            for measure_type in self.measure_types:
                if measure_type.match(operation.general_account):
                    measure = company_measures.get(measure_type.id)
                    if measure is None:
                        measure = self._get_new_measure(
                            measure_type.label,
                            grid.id,
                            measure_type.id
                        )
                        company_measures[measure_type.id] = measure

                    measure.value += operation.total()
                    matched = True

            if matched:
                self.session.merge(measure)
        return self.grids


class TreasuryMeasureCompiler(BaseMeasureCompiler):
    measure_type_class = TreasuryMeasureType
    measure_grid_class = TreasuryMeasureGrid
    measure_class = TreasuryMeasure

    def _get_new_grid(self, company_id):
        """
        Build a new grid based on the given upload

        :param int company_id: The associated company
        """
        return TreasuryMeasureGrid(
            date=self.upload.date,
            company_id=company_id,
            upload=self.upload,
        )


class GeneralLedgerMeasureCompiler(BaseMeasureCompiler):
    measure_type_class = GeneralLedgerMeasureType
    measure_grid_class = GeneralLedgerMeasureGrid
    measure_class = GeneralLedgerMeasure

    def _get_new_grid(self, company_id):
        """
        Build a new grid based on the given upload

        :param int company_id: The associated company
        """
        return GeneralLedgerMeasureGrid(
            year=self.upload.year,
            month=self.upload.month,
            company_id=company_id,
            upload=self.upload,
        )


def get_measure_compiler(data_type):
    """
    Retrieve the measure compilers to be used with this given type of datas

    :param str data_type: The type of data we build our measures from
    :returns: The measure compiler
    """
    if data_type == 'analytical_balance':
        return TreasuryMeasureCompiler
    elif data_type == 'general_ledger':
        return GeneralLedgerMeasureCompiler


@celery_app.task(bind=True)
def compile_measures_task(self, upload_type, upload_id, operation_ids):
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

    compiler = get_measure_compiler(upload_type)
    try:
        compiler = compiler(upload, operations)
        grids = compiler.process_datas()
        transaction.commit()
    except:
        transaction.abort()
    else:
        logger.info(u"{0} measure grids were handled".format(len(grids)))
        logger.info(u"The transaction has been commited")
        logger.info(u"* Task SUCCEEDED !!!")
