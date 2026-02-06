from .core import *  # noqa

from .core import INSTALLED_APPS as CORE_APPS

INSTALLED_APPS = CORE_APPS + [
    "oauth2_provider",
    "oauth_dcr",
    "activitypub.extras.oauth",
]

REST_FRAMEWORK = {
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "oauth2_provider.contrib.rest_framework.OAuth2Authentication",
    ],
}


OAUTH2_PROVIDER_ACCESS_TOKEN_MODEL = "activitypub_extras_oauth.OAuthAccessToken"
OAUTH2_PROVIDER_APPLICATION_MODEL = "activitypub_extras_oauth.OAuthClientApplication"
OAUTH2_PROVIDER_REFRESH_TOKEN_MODEL = "activitypub_extras_oauth.OAuthRefreshToken"
OAUTH2_PROVIDER_ID_TOKEN_MODEL = "activitypub_extras_oauth.OidcIdentityToken"
OAUTH2_PROVIDER_GRANT_MODEL = "activitypub_extras_oauth.OAuthAuthorizationCode"

OAUTH2_PROVIDER = {
    "OAUTH2_BACKEND_CLASS": "activitypub.extras.oauth.views.ActivityPubOAuthServer",
    "OAUTH2_VALIDATOR_CLASS": "activitypub.extras.oauth.views.ActivityPubIdentityOAuth2Validator",
    "ALLOWED_REDIRECT_URI_SCHEMES": ["https", "http"],
    # OAuth Admin Classes
    "APPLICATION_ADMIN_CLASS": "activitypub.extras.oauth.admin.OAuthClientApplicationAdmin",
    "ACCESS_TOKEN_ADMIN_CLASS": "activitypub.extras.oauth.admin.OAuthAccessTokenAdmin",
    "GRANT_ADMIN_CLASS": "activitypub.extras.oauth.admin.OAuthAuthorizationCodeAdmin",
    "REFRESH_TOKEN_ADMIN_CLASS": "activitypub.extras.oauth.admin.OAuthRefreshTokenAdmin",
    "ID_TOKEN_ADMIN_CLASS": "activitypub.extras.oauth.admin.OidcIdentityTokenAdmin",
}
