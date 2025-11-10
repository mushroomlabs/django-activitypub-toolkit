import django
from celery import current_app

from . import settings as test_settings


def pytest_configure(config):
    from django.conf import settings

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
            CELERY_BROKER_URL="memory://",
            CELERY_BROKER_USE_SSL=False,
            CELERY_TASK_ALWAYS_EAGER=True,
            CELERY_TASK_EAGER_PROPAGATES=True,
            DEFAULT_AUTO_FIELD=test_settings.DEFAULT_AUTO_FIELD,
            REST_FRAMEWORK=test_settings.REST_FRAMEWORK,
            TEMPLATES=test_settings.TEMPLATES,
            FEDERATION=test_settings.FEDERATION,
        )

    django.setup()

    current_app.config_from_object("django.conf:settings", namespace="CELERY")
    current_app.conf.update(
        task_always_eager=True,
        task_eager_propagates=True,
    )
    current_app.autodiscover_tasks(["activitypub"])
    print(f"Registered tasks: {list(current_app.tasks.keys())}")
