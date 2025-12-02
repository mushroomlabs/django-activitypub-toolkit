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
        document_processors = [
            "activitypub.processors.ActorDeletionDocumentProcessor",
            "activitypub.processors.CompactJsonLdDocumentProcessor",
        ]

    class LinkedData:
        default_contexts = {
            "activitypub.contexts.AS2_CONTEXT",
            "activitypub.contexts.SEC_V1_CONTEXT",
            "activitypub.contexts.W3C_IDENTITY_V1_CONTEXT",
            "activitypub.contexts.W3C_DID_V1_CONTEXT",
            "activitypub.contexts.W3C_DATAINTEGRITY_V1_CONTEXT",
            "activitypub.contexts.MULTIKEY_V1_CONTEXT",
            "activitypub.contexts.MASTODON_CONTEXT",
            "activitypub.contexts.LEMMY_CONTEXT",
            "activitypub.contexts.FUNKWHALE_CONTEXT",
        }
        extra_contexts = {}

        default_document_resolvers = {
            "activitypub.resolvers.ContextUriResolver",
            "activitypub.resolvers.HttpDocumentResolver",
        }
        extra_document_resolvers = {}

        default_context_models = {
            "activitypub.models.LinkContext",
            "activitypub.models.ObjectContext",
            "activitypub.models.ActorContext",
            "activitypub.models.ActivityContext",
            "activitypub.models.EndpointContext",
            "activitypub.models.QuestionContext",
            "activitypub.models.CollectionContext",
            "activitypub.models.CollectionPageContext",
            "activitypub.models.SecV1Context",
        }
        extra_context_models = {}
        disabled_context_models = {}

        custom_context_serializers = {
            "activitypub.models.CollectionContext": "activitypub.serializers.CollectionContextSerializer",  # noqa
            "activitypub.models.CollectionPageContext": "activitypub.serializers.CollectionPageContextSerializer",  # noqa
            "activitypub.models.QuestionContext": "activitypub.serializers.QuestionContextSerializer",  # noqa
        }

        embedded_context_serializers = {
            "activitypub.models.ActorContext": "activitypub.serializers.EmbeddedActorContextSerializer",  # noqa
            "activitypub.models.CollectionContext": "activitypub.serializers.EmbeddedCollectionContextSerializer",  # noqa
            # Note: CollectionPageContext doesn't have an embedded variant
            # because pages are always shown with their items
        }

    @property
    def PRESET_CONTEXTS(self):
        contexts = self.LinkedData.default_contexts.union(self.LinkedData.extra_contexts)
        return [import_string(s) for s in contexts]

    @property
    def DOCUMENT_RESOLVERS(self):
        resolvers = self.LinkedData.default_document_resolvers.union(
            self.LinkedData.extra_document_resolvers
        )
        return [import_string(s) for s in resolvers]

    @property
    def DOCUMENT_PROCESSORS(self):
        classes = [import_string(s) for s in self.Middleware.document_processors]
        return [c() for c in classes]

    @property
    def CONTEXT_MODELS(self):
        default = self.LinkedData.default_context_models
        extra = self.LinkedData.extra_context_models
        disabled = self.LinkedData.disabled_context_models

        return [import_string(s) for s in default.union(extra).difference(disabled)]

    @property
    def CUSTOM_CONTEXT_SERIALIZERS(self):
        return {
            import_string(model_path): import_string(serializer_path)
            for model_path, serializer_path in self.LinkedData.custom_context_serializers.items()
        }

    @property
    def EMBEDDED_CONTEXT_SERIALIZERS(self):
        return {
            import_string(model_path): import_string(serializer_path)
            for model_path, serializer_path in self.LinkedData.embedded_context_serializers.items()
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
            "DOCUMENT_PROCESSORS": (self.Middleware, "document_processors"),
            "EXTRA_DOCUMENT_RESOLVERS": (self.LinkedData, "extra_document_resolvers"),
            "EXTRA_CONTEXT_MODELS": (self.LinkedData, "extra_context_models"),
            "EXTRA_CONTEXTS": (self.LinkedData, "extra_contexts"),
            "DISABLED_CONTEXT_MODELS": (self.LinkedData, "disabled_context_models"),
            "CUSTOM_CONTEXT_SERIALIZERS": (self.LinkedData, "custom_context_serializers"),
            "EMBEDDED_CONTEXT_SERIALIZERS": (self.LinkedData, "embedded_context_serializers"),
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
