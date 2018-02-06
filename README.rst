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

Autonomie celery provides all the models that should be used to store task
execution related stuff (see autonomie_celery.models).

Install
-------

System packages
................

autonmie_celery needs a redis server to run

On Debian

.. code-block:: console

    apt-get install redis-server


On Fedora

.. code-block:: console

    dnf install redis-server

Python stuff
.............

autonomie_celery should be run in the same environment as Autonomie :
https://github.com/CroissanceCommune/autonomie

You may first run

.. code-block:: console

    workon autonomie


.. code-block:: console

    git clone https://github.com/CroissanceCommune/autonomie_celery.git
    cd autonomie_celery
    python setup.py install
    cp development.ini.sample development.ini

Customize the development.ini file as needed


Start it
---------

Launch the following command to launch the worker daemon::

    celery worker -A pyramid_celery.celery_app --ini development.ini

Launch the following command to launch the beat daemon::

    celery beat -A pyramid_celery.celery_app --ini development.ini
