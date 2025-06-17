from celery import Celery
from celery.schedules import crontab

app = Celery("activitypub_toolkit")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
