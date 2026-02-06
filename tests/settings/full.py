from .core import *  # noqa
from .core import INSTALLED_APPS as CORE_APPS
from .lemmy import LEMMY_TOKEN_LIFETIME, LEMMY_TOKEN_SIGNING_KEY, FEDERATION, ROOT_URLCONF  # noqa
from .oauth import (  # noqa
    OAUTH2_PROVIDER_ACCESS_TOKEN_MODEL,
    OAUTH2_PROVIDER_APPLICATION_MODEL,
    OAUTH2_PROVIDER_REFRESH_TOKEN_MODEL,
    OAUTH2_PROVIDER_ID_TOKEN_MODEL,
    OAUTH2_PROVIDER_GRANT_MODEL,
    OAUTH2_PROVIDER,
)

INSTALLED_APPS = CORE_APPS + [
    "oauth2_provider",
    "oauth_dcr",
    "taggit",
    "tree_queries",
    "activitypub.extras.oauth",
    "activitypub.adapters.lemmy",
]

REST_FRAMEWORK = {
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "oauth2_provider.contrib.rest_framework.OAuth2Authentication",
        "activitypub.adapters.lemmy.authentication.LemmyJWTAuthentication",
    ],
}
