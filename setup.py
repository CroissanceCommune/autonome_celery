import os

from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(here, 'README.txt')) as f:
    README = f.read()

requires = [
    'pyramid',
    'pyramid_tm',
    'pyramid-celery==3.0.0',
    'SQLAlchemy',
    'transaction',
    'zope.sqlalchemy',
    'redis==2.10.5',
    'kombu==4.0.2',
    'celery==4.0.2',
    'billiard==3.5.0.2',
    ]

tests_require = [
    'WebTest >= 1.3.1',  # py3 compat
    'pytest',  # includes virtualenv
    'pytest-cov',
    ]


entry_points = {
    "paste.app_factory": "main = autonomie_celery:main",
}

setup(name='autonomie_celery',
      version='1.2.2',
      description='autonomie_celery',
      long_description=README,
      license='GPLv3',
      classifiers=[
          "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
          "Programming Language :: Python",
          "Framework :: Pyramid",
          "Topic :: Internet :: WWW/HTTP",
          "Topic :: Internet :: WWW/HTTP :: WSGI :: Application",
      ],
      author='Majerti',
      author_email='equipe@majerti.fr',
      url='https://github.com/CroissanceCommune/autonomie_base',
      keywords='web wsgi bfg pylons pyramid celery',
      packages=find_packages(),
      include_package_data=True,
      zip_safe=False,
      extras_require={
          'testing': tests_require,
      },
      install_requires=requires,
      entry_points=entry_points,
      )
