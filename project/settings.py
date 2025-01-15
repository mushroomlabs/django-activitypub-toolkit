import os

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(PROJECT_DIR)
SECRET_KEY = "testing-key-11234567890"
ALLOWED_HOSTS = ["*"]

# Application definitionn
INSTALLED_APPS = [
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.messages",
    "django.contrib.postgres",
    "rest_framework",
    "activitypub",
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
        "ENGINE": "django.db.backends.postgresql",  # PostgreSQL is required
        "HOST": os.getenv("ACTIVITYPUB_TOOLKIT_DATABASE_HOST", "127.0.0.1"),
        "PORT": os.getenv("ACTIVITYPUB_TOOLKIT_DATABASE_PORT", 5432),
        "NAME": os.getenv("ACTIVITYPUB_TOOLKIT_DATABASE_NAME", "activitypub_toolkit"),
        "USER": os.getenv("ACTIVITYPUB_TOOLKIT_DATABASE_USER", "activitypub_toolkit"),
        "PASSWORD": os.getenv("ACTIVITYPUB_TOOLKIT_DATABASE_PASSWORD"),
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


# ActivityPub
FEDERATION = {"DEFAULT_DOMAIN": "testserver", "SOFTWARE_NAME": "activitypub_toolkit"}
