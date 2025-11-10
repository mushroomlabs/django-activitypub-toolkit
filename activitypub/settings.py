import logging
from datetime import timedelta

from django.conf import settings
from django.test.signals import setting_changed
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


class AppSettings:
    class Instance:
        open_registrations = True
        default_url = "http://example.com"
        shared_inbox_view_name = None
        activity_view_name = None
        actor_view_name = None
        system_actor_view_name = None
        collection_view_name = None
        collection_page_view_name = None
        object_view_name = None
        keypair_view_name = None
        force_http = False
        collection_page_size = 25

    class NodeInfo:
        software_name = "django-activitypub"
        software_version = "0.0.1"

    class RateLimit:
        remote_object_fetching = timedelta(minutes=10)

    class Middleware:
        message_processors = [
            "activitypub.message_processors.ActorDeletionMessageProcessor",
            "activitypub.message_processors.CompactJsonLdMessageProcessor",
        ]

    class LinkedData:
        document_resolvers = [
            "activitypub.resolvers.ConstantDocumentResolver",
            "activitypub.resolvers.HttpDocumentResolver",
        ]
        autoloaded_context_models = [
            "activitypub.models.LinkContext",
            "activitypub.models.ObjectContext",
            "activitypub.models.ActorContext",
            "activitypub.models.ActivityContext",
            "activitypub.models.EndpointContext",
            "activitypub.models.QuestionContext",
            "activitypub.models.CollectionContext",
            "activitypub.models.CollectionPageContext",
            "activitypub.models.SecV1Context",
        ]
        custom_serializers = {
            "activitypub.models.CollectionContext": "activitypub.serializers.CollectionContextSerializer",  # noqa
            "activitypub.models.CollectionPageContext": "activitypub.serializers.CollectionContextSerializer",  # noqa
        }

    @property
    def DOCUMENT_RESOLVERS(self):
        return [import_string(s) for s in self.LinkedData.document_resolvers]

    @property
    def AUTOLOADED_CONTEXT_MODELS(self):
        return [import_string(s) for s in self.LinkedData.autoloaded_context_models]

    @property
    def MESSAGE_PROCESSORS(self):
        classes = [import_string(s) for s in self.Middleware.message_processors]
        return [c() for c in classes]

    @property
    def CUSTOM_SERIALIZERS(self):
        return {
            import_string(model_path): import_string(serializer_path)
            for model_path, serializer_path in self.LinkedData.custom_serializers.items()
        }

    def __init__(self):
        self.load()

    def load(self):
        ATTRS = {
            "OPEN_REGISTRATIONS": (self.Instance, "open_registrations"),
            "DEFAULT_URL": (self.Instance, "default_url"),
            "FORCE_INSECURE_HTTP": (self.Instance, "force_http"),
            "SHARED_INBOX_VIEW": (self.Instance, "shared_inbox_view_name"),
            "SYSTEM_ACTOR_VIEW": (self.Instance, "system_actor_view_name"),
            "ACTIVITY_VIEW": (self.Instance, "activity_view_name"),
            "OBJECT_VIEW": (self.Instance, "object_view_name"),
            "COLLECTION_VIEW": (self.Instance, "collection_view_name"),
            "COLLECTION_PAGE_VIEW": (self.Instance, "collection_page_view_name"),
            "ACTOR_VIEW": (self.Instance, "actor_view_name"),
            "KEYPAIR_VIEW": (self.Instance, "keypair_view_name"),
            "COLLECTION_PAGE_SIZE": (self.Instance, "collection_page_size"),
            "SOFTWARE_NAME": (self.NodeInfo, "software_name"),
            "SOFTWARE_VERSION": (self.NodeInfo, "software_version"),
            "RATE_LIMIT_REMOTE_FETCH": (self.RateLimit, "remote_object_fetching"),
            "MESSAGE_PROCESSORS": (self.Middleware, "message_processors"),
            "DOCUMENT_RESOLVERS": (self.LinkedData, "document_resolvers"),
            "AUTOLOADED_CONTEXT_MODELS": (self.LinkedData, "autoloaded_context_models"),
            "CUSTOM_SERIALIZERS": (self.LinkedData, "custom_serializers"),
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
