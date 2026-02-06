import os

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(PROJECT_DIR)
SECRET_KEY = "testing-key-11234567890"
ALLOWED_HOSTS = ["*"]
DEBUG = True

# Application definitionn
INSTALLED_APPS = [
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.messages",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "rest_framework",
    "oauth2_provider",
    "oauth_dcr",
    "taggit",
    "tree_queries",
    "activitypub.core",
    "activitypub.adapters.lemmy",
    "activitypub.extras.oauth",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

APPEND_SLASH = False
ROOT_URLCONF = "project.urls"

# Database
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.getenv("ACTIVITYPUB_TOOLKIT_DATABASE_NAME", "activitypub_toolkit.db"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Celery
CELERY_BROKER_URL = "memory://"
CELERY_BROKER_USE_SSL = False
CELERY_TASK_EAGER_MODE = True
CELERY_TASK_EAGER_PROPAGATES = True

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Rest Framework
REST_FRAMEWORK = {
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.TokenAuthentication"],
}

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

STATIC_URL = "/static/"
STATIC_ROOT = os.getenv("ACTIVITYPUB_TOOLKIT_STATIC_ROOT", "static")

# ActivityPub
FEDERATION = {"DEFAULT_URL": "http://testserver", "SOFTWARE_NAME": "activitypub_toolkit"}

LOG_LEVEL = "DEBUG" if DEBUG else "INFO"
LOGGING_HANDLERS = {
    "null": {"level": "DEBUG", "class": "logging.NullHandler"},
    "console": {
        "level": LOG_LEVEL,
        "class": "logging.StreamHandler",
        "formatter": "verbose",
    },
}

LOGGING_HANDLER_METHODS = ["console"]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": "ACTIVITYPUB_LOG_DISABLE_EXISTING_LOGGERS" in os.environ,
    "formatters": {
        "verbose": {
            "format": "%(asctime)s %(levelname)s:%(pathname)s %(process)d %(lineno)d %(message)s"
        },
        "simple": {"format": "%(levelname)s:%(module)s %(lineno)d %(message)s"},
    },
    "handlers": LOGGING_HANDLERS,
    "loggers": {
        "django": {"handlers": ["null"], "propagate": True, "level": "INFO"},
        "django.db.backends:": {
            "handlers": LOGGING_HANDLER_METHODS,
            "level": "ERROR",
            "propagate": False,
        },
        "django.request": {
            "handlers": LOGGING_HANDLER_METHODS,
            "level": "ERROR",
            "propagate": False,
        },
        "activitypub": {
            "handlers": LOGGING_HANDLER_METHODS,
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
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
