import logging
from datetime import timedelta
from enum import StrEnum, auto

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

    class Policies:
        follow_request_rejection_policies = []

    class OAuth:
        class DynamicClientRegistration(StrEnum):
            DISABLED = auto()
            AUTHENTICATION_REQUIRED = auto()
            OPEN = auto()

        dynamic_client_registration = DynamicClientRegistration.OPEN

    class LinkedData:
        default_contexts = {
            "activitypub.contexts.AS2_CONTEXT",
            "activitypub.contexts.SEC_V1_CONTEXT",
            "activitypub.contexts.W3C_IDENTITY_V1_CONTEXT",
            "activitypub.contexts.W3C_DID_V1_CONTEXT",
            "activitypub.contexts.W3C_DATAINTEGRITY_V1_CONTEXT",
            "activitypub.contexts.MULTIKEY_V1_CONTEXT",
            "activitypub.contexts.MASTODON_CONTEXT",
            "activitypub.contexts.MBIN_CONTEXT",
            "activitypub.contexts.LEMMY_CONTEXT",
            "activitypub.contexts.FUNKWHALE_CONTEXT",
            "activitypub.contexts.SCHEMA_LANGUAGE_CONTEXT",
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
            "activitypub.models.SourceContentContext",
        }
        extra_context_models = {}
        disabled_context_models = {}
        projection_selector = "activitypub.projections.default_projection_selector"

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
    def PROJECTION_SELECTOR(self):
        return import_string(self.LinkedData.projection_selector)

    @property
    def REJECT_FOLLOW_REQUEST_POLICIES(self):
        return [import_string(s) for s in self.Policies.follow_request_rejection_policies]

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
            "PROJECTION_SELECTOR": (self.LinkedData, "projection_selector"),
            "EXTRA_DOCUMENT_RESOLVERS": (self.LinkedData, "extra_document_resolvers"),
            "EXTRA_CONTEXT_MODELS": (self.LinkedData, "extra_context_models"),
            "EXTRA_CONTEXTS": (self.LinkedData, "extra_contexts"),
            "DISABLED_CONTEXT_MODELS": (self.LinkedData, "disabled_context_models"),
            "REJECT_FOLLOW_REQUEST_CHECKS": (
                self.Policies,
                "follow_request_rejection_policies",
            ),
            "OAUTH_DYNAMIC_CLIENT_REGISTRATION": (self.OAuth, "dynamic_client_registration"),
        }
        user_settings = getattr(settings, "FEDERATION", {})

        for setting, value in user_settings.items():
            logger.debug(f"setting {setting} -> {value}")
            if setting not in ATTRS:
                logger.warning(f"Ignoring {setting} as it is not a setting for ActivityPub")
                continue

            setting_class, attr = ATTRS[setting]
            setattr(setting_class, attr, value)

        # Validate OAuth settings
        dcr_mode = self.OAuth.dynamic_client_registration
        valid_modes = {"disabled", "authentication_required", "open"}
        if dcr_mode not in valid_modes:
            logger.warning(
                f"Invalid OAUTH_DYNAMIC_CLIENT_REGISTRATION value: '{dcr_mode}'. "
                f"Must be one of {valid_modes}. Defaulting to 'open'."
            )
            self.OAuth.dynamic_client_registration = "open"


app_settings = AppSettings()


def reload_settings(*args, **kw):
    setting = kw["setting"]
    if setting == "FEDERATION":
        app_settings.load()


setting_changed.connect(reload_settings)
