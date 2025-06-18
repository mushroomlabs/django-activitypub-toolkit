import logging
from datetime import timedelta

from django.conf import settings
from django.test.signals import setting_changed
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


class AppSettings:
    class Instance:
        open_registrations = True
        default_domain = "example.com"
        shared_inbox_view_name = None
        activity_view_name = None
        actor_view_name = None
        system_actor_view_name = None
        collection_view_name = None
        object_view_name = None
        force_http = False
        collection_page_size = 25

    class NodeInfo:
        software_name = "django-activitypub"
        software_version = "0.0.1"

    class RateLimit:
        remote_object_fetching = timedelta(minutes=10)

    class Middleware:
        message_adapters = ["activitypub.adapters.ActorDeletionMessageAdapter"]

    @property
    def MESSAGE_ADAPTERS(self):
        classes = [import_string(s) for s in self.Middleware.message_adapters]
        return [c() for c in classes]

    def __init__(self):
        self.load()

    def load(self):
        ATTRS = {
            "OPEN_REGISTRATIONS": (self.Instance, "open_registrations"),
            "DEFAULT_DOMAIN": (self.Instance, "default_domain"),
            "FORCE_INSECURE_HTTP": (self.Instance, "force_http"),
            "SHARED_INBOX_VIEW": (self.Instance, "shared_inbox_view_name"),
            "SYSTEM_ACTOR_VIEW": (self.Instance, "system_actor_view_name"),
            "ACTIVITY_VIEW": (self.Instance, "activity_view_name"),
            "OBJECT_VIEW": (self.Instance, "object_view_name"),
            "COLLECTION_VIEW": (self.Instance, "collection_view_name"),
            "ACTOR_VIEW": (self.Instance, "actor_view_name"),
            "COLLECTION_PAGE_SIZE": (self.Instance, "collection_page_size"),
            "SOFTWARE_NAME": (self.NodeInfo, "software_name"),
            "SOFTWARE_VERSION": (self.NodeInfo, "software_version"),
            "RATE_LIMIT_REMOTE_FETCH": (self.RateLimit, "remote_object_fetching"),
            "MESSAGE_ADAPTERS": (self.Middleware, "message_adapters"),
        }
        user_settings = getattr(settings, "FEDERATION", {})

        for setting, value in user_settings.items():
            logger.debug(f"setting {setting} -> {value}")
            if setting not in ATTRS:
                logger.warning(f"Ignoring {setting} as it is not a setting for ActivityPub")
                continue

            setting_class, attr = ATTRS[setting]
            setattr(setting_class, attr, value)


app_settings = AppSettings()


def reload_settings(*args, **kw):
    setting = kw["setting"]
    if setting == "FEDERATION":
        app_settings.load()


setting_changed.connect(reload_settings)
