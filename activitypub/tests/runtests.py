#!/usr/bin/env python

import sys

import django
from celery import Celery
from django.conf import settings
from django.core.management import call_command

from activitypub.tests import settings as test_settings


def runtests():
    if not settings.configured:
        settings.configure(
            SECRET_KEY=test_settings.SECRET_KEY,
            ALLOWED_HOSTS=test_settings.ALLOWED_HOSTS,
            INSTALLED_APPS=test_settings.INSTALLED_APPS,
            MIDDLEWARE=test_settings.MIDDLEWARE,
            ROOT_URLCONF=test_settings.ROOT_URLCONF,
            APPEND_SLASH=test_settings.APPEND_SLASH,
            DATABASES=test_settings.DATABASES,
            USE_TZ=test_settings.USE_TZ,
            CELERY_BROKER_URL=test_settings.CELERY_BROKER_URL,
            CELERY_BROKER_USE_SSL=test_settings.CELERY_BROKER_USE_SSL,
            CELERY_TASK_EAGER_MODE=test_settings.CELERY_TASK_EAGER_MODE,
            CELERY_TASK_EAGER_PROPAGATES=test_settings.CELERY_TASK_EAGER_PROPAGATES,
            DEFAULT_AUTO_FIELD=test_settings.DEFAULT_AUTO_FIELD,
            REST_FRAMEWORK=test_settings.REST_FRAMEWORK,
            TEMPLATES=test_settings.TEMPLATES,
            FEDERATION=test_settings.FEDERATION,
        )

    django.setup()
    app = Celery("activitypub_toolkit_test")
    app.config_from_object("django.conf:settings", namespace="CELERY")
    app.autodiscover_tasks()
    failures = call_command("test", "activitypub", interactive=False, failfast=False, verbosity=2)

    sys.exit(bool(failures))


if __name__ == "__main__":
    runtests()
