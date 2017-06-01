# -*- coding: utf-8 -*-
# * Authors:
#       * TJEBBES Gaston <g.t@majerti.fr>
#       * Arezki Feth <f.a@majerti.fr>;
#       * Miotte Julien <j.m@majerti.fr>;
import time
import transaction

from sqlalchemy.orm.exc import NoResultFound
from celery.utils.log import get_task_logger


JOB_RETRIEVE_ERROR = u"We can't retrieve the job {jobid}, the task is cancelled"

logger = get_task_logger(__name__)


def get_job(celery_request, job_model, job_id):
    """
    Return the current executed job (in autonomie's sens)

    :param obj celery_request: The current celery request object
    :param obj job_model: The Job model
    :param int job_id: The id of the job

    :returns: The current job
    :raises sqlalchemy.orm.exc.NoResultFound: If the job could not be found
    """
    logger.debug("Retrieving a job with id : {0}".format(job_id))
    from autonomie_base.models.base import DBSESSION
    # We sleep a bit to wait for the current request to be finished : since we
    # use a transaction manager, the delay call launched in a view is done
    # before the job  element is commited to the bdd (at the end of the request)
    # if we query for the job too early, the session will not be able to
    # retrieve the newly created job
    time.sleep(2)
    try:
        job = DBSESSION().query(job_model).filter(job_model.id == job_id).one()
        job.jobid = celery_request.id
    except NoResultFound:
        logger.debug(" -- No job found")
        logger.exception(JOB_RETRIEVE_ERROR.format(job_id))
        job = None
    return job


def record_failure(job_model, job_id, task_id, e):
    """
    Record a job's failure
    """
    transaction.begin()
    # We fetch the job again since we're in a new transaction
    from autonomie_base.models.base import DBSESSION
    job = DBSESSION().query(job_model).filter(
        job_model.id == job_id
    ).first()
    job.jobid = task_id
    job.status = "failed"
    # We append an error
    if hasattr(job, 'error_messages'):
        if job.error_messages is None:
            job.error_messages = []
        job.error_messages.append(u"%s" % e)
    transaction.commit()
