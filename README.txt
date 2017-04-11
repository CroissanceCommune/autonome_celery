Autonomie asynchronous tasks
============================

Asynchronous tasks are executed through celery.
pyramid_celery is used to integrate celery with the Pyramid related stuff.
pyramid_beaker is used to cache responses.

tasks:

    Asynchronous tasks called from Autonomie

scheduler:

    Beat tasks, repeated along the time (like cron tasks)

Results
-------

No result backend is used, tasks interact directly with Autonomie's database to
return datas.

Autonomie provides all the models that should be used to store task execution
related stuff (see autonomie.models.job).
