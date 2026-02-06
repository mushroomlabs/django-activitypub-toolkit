from django.apps import AppConfig


class ActivityPubOAuthConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "activitypub.extras.oauth"
    label = "activitypub_extras_oauth"
    verbose_name = "ActivityPub OAuth"
