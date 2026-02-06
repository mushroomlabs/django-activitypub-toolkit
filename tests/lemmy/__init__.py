from celery import Celery

app = Celery("activitypub_lemmy_adapter")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
