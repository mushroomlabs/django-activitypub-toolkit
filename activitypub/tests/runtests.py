#!/usr/bin/env python

import os
import sys

import django
from django.conf import settings
from django.core.management import call_command


def runtests():
    if not settings.configured:
        settings.configure(
            SECRET_KEY="testing-key-11234567890",
            ALLOWED_HOSTS=["*"],
            INSTALLED_APPS=[
                "django.contrib.admin",
                "django.contrib.auth",
                "django.contrib.contenttypes",
                "django.contrib.messages",
                "django.contrib.postgres",
                "rest_framework",
                "activitypub",
            ],
            MIDDLEWARE=[
                "django.middleware.security.SecurityMiddleware",
                "django.contrib.sessions.middleware.SessionMiddleware",
                "django.middleware.common.CommonMiddleware",
                "django.middleware.csrf.CsrfViewMiddleware",
                "django.contrib.auth.middleware.AuthenticationMiddleware",
                "django.contrib.messages.middleware.MessageMiddleware",
                "django.middleware.clickjacking.XFrameOptionsMiddleware",
            ],
            APPEND_SLASH=False,
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.postgresql",  # PostgreSQL is required
                    "HOST": os.getenv("ACTIVITYPUB_TOOLKIT_DATABASE_HOST", "db"),
                    "PORT": os.getenv("ACTIVITYPUB_TOOLKIT_DATABASE_PORT", 5432),
                    "NAME": os.getenv("ACTIVITYPUB_TOOLKIT_DATABASE_NAME", "activitypub_toolkit"),
                    "USER": os.getenv("ACTIVITYPUB_TOOLKIT_DATABASE_USER", "activitypub_toolkit"),
                    "PASSWORD": os.getenv("ACTIVITYPUB_TOOLKIT_DATABASE_PASSWORD"),
                }
            },
            CELERY_BROKER_URL="memory://",
            CELERY_BROKER_USE_SSL=False,
            CELERY_TASK_EAGER_MODE=True,
            CELERY_TASK_EAGER_PROPAGATES=True,
            DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
            LANGUAGE_CODE="en-us",
            TIME_ZONE="UTC",
            USE_I18N=True,
            USE_TZ=True,
            REST_FRAMEWORK={
                "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
                "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
                "DEFAULT_AUTHENTICATION_CLASSES": [
                    "rest_framework.authentication.TokenAuthentication"
                ],
            },
            TEMPLATES=[
                {
                    "BACKEND": "django.template.backends.django.DjangoTemplates",
                    "APP_DIRS": True,
                    "OPTIONS": {
                        "context_processors": [
                            "django.template.context_processors.debug",
                            "django.template.context_processors.request",
                            "django.contrib.auth.context_processors.auth",
                            "django.contrib.messages.context_processors.messages",
                        ]
                    },
                }
            ],
            FEDERATION={"DEFAULT_DOMAIN": "testserver", "SOFTWARE_NAME": "activitypub_toolkit"},
        )

    django.setup()
    failures = call_command("test", "activitypub", interactive=False, failfast=False, verbosity=2)

    sys.exit(bool(failures))


if __name__ == "__main__":
    runtests()
