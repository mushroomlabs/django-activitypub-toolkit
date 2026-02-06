from .core import *  # noqa
from .core import INSTALLED_APPS as CORE_APPS

INSTALLED_APPS = CORE_APPS + [
    "taggit",
    "tree_queries",
    "activitypub.adapters.lemmy",
]

ROOT_URLCONF = "tests.lemmy.urls"

REST_FRAMEWORK = {
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "activitypub.adapters.lemmy.authentication.LemmyJWTAuthentication"
    ],
}

# Lemmy JWT Authentication Settings
LEMMY_TOKEN_LIFETIME = 60 * 60 * 24 * 30  # 30 days in seconds
LEMMY_TOKEN_SIGNING_KEY = "jwt-signing-test-key"

FEDERATION = {
    "DEFAULT_URL": "http://testserver",
    "EXTRA_CONTEXT_MODELS": {"activitypub.adapters.lemmy.models.LemmyContextModel"},
}
