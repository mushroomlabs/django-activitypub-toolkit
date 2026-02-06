from django.apps import AppConfig


class LemmyAdapterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "activitypub.adapters.lemmy"
    label = "activitypub_lemmy_adapter"
    verbose_name = "Lemmy Adapter"

    def ready(self):
        from . import handlers  # noqa
