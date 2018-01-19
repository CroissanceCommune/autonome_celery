# -*- coding: utf-8 -*-
# * Authors:
#       * TJEBBES Gaston <g.t@majerti.fr>
#       * Arezki Feth <f.a@majerti.fr>;
#       * Miotte Julien <j.m@majerti.fr>;
import time
import transaction

from sqlalchemy.orm.exc import NoResultFound
from celery.utils.log import get_task_logger


JOB_RETRIEVE_ERROR = u"We can't retrieve the job {jobid}, the task will not \
be run"


def get_logger(name=""):
    return get_task_logger("celery." + name)

logger = get_logger(__name__)


# we wait max TIMEOUT seconds before considering there was an error while
# inserting job in the database on main process side
TIMEOUT = 20
# Interval of "try again"
INTERVAL = 2


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

    # We try to get tje job back, waiting for the current request to be finished
    # : since we use a transaction manager, the delay call launched in a view is
    # done before the job  element is commited to the bdd (at the end of the
    # request) if we query for the job too early, the session will not be able
    # to retrieve the newly created job
    current_time = 0
    job = None
    while current_time <= TIMEOUT and job is None:
        try:
            job = DBSESSION().query(job_model).filter(
                job_model.id == job_id
            ).one()
            job.jobid = celery_request.id
            if job.status not in ('planned'):
                logger.error(u"Job has already been launched")
                job = None
        except NoResultFound:
            transaction.abort()
            transaction.begin()
            logger.debug(" -- No job found")
            logger.exception(JOB_RETRIEVE_ERROR.format(jobid=job_id))

        if job is None:
            time.sleep(INTERVAL)
            current_time += INTERVAL

    return job


def _record_running(job):
    """
    Record that a job is running
    """
    job.status = "running"
    from autonomie_base.models.base import DBSESSION
    DBSESSION().merge(job)


def start_job(celery_request, job_model, job_id):
    """
    Entry point to launch when starting a job

    :param obj celery_request: The current celery request object
    :param obj job_model: The Job model
    :param int job_id: The id of the job

    :returns: The current job or None
    """
    logger.info(u" Starting job %s %s" % (job_model, job_id))
    transaction.begin()
    try:
        job = get_job(celery_request, job_model, job_id)
        if job is not None:
            _record_running(job)
        else:
            raise Exception(u"No job found")
        transaction.commit()
    except:
        transaction.abort()
        raise Exception(u"Error while launching start_job")

    logger.info(u"Task marked as RUNNING")


def _record_job_status(job_model, job_id, status_str):
    """
    Record a status and return the job object
    """
    # We fetch the job again since we're in a new transaction
    from autonomie_base.models.base import DBSESSION
    job = DBSESSION().query(job_model).filter(
        job_model.id == job_id
    ).first()
    job.status = status_str
    return job


def record_failure(job_model, job_id, e=None, **kwargs):
    """
    Record a job's failure
    """
    transaction.begin()
    job = _record_job_status(job_model, job_id, 'failed')
    # We append an error
    if hasattr(job, 'error_messages') and e:
        job.error_messages = [u"%s" % e]

    for key, value in kwargs.items():
        setattr(job, key, value)

    transaction.commit()
    logger.info(u"* Task marked as FAILED")


def record_completed(job_model, job_id, **kwargs):
    """
    Record job's completion and set additionnal arguments
    """
    transaction.begin()
    job = _record_job_status(job_model, job_id, 'completed')
    for key, value in kwargs.items():
        setattr(job, key, value)
    transaction.commit()
    logger.info(u"* Task marked as COMPLETED")


def check_alive():
    """
    Check the redis service is available
    """
    from pyramid_celery import celery_app
    from redis.exceptions import ConnectionError

    return_code = True
    return_msg = None
    try:
        from celery.app.control import Inspect
        insp = Inspect(app=celery_app)

        stats = insp.stats()
        if not stats:
            return_code = False
            return_msg = (
                u"Le service backend ne répond pas "
                u"(Celery service not available)."
            )
    except (Exception, ConnectionError) as e:
        return_code = False
        return_msg = u"Erreur de connextion au service backend (%s)." % e

    if return_code is False:
        return_msg += u" Veuillez contacter un administrateur"

    return return_code, return_msg
