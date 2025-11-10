# Install the Toolkit

This guide shows you how to install the Django ActivityPub Toolkit in your Django project.

## Prerequisites

You need:

- Python 3.9 or higher
- Django 4.2.23 or higher
- A Django project to add federation to

## Installation

Install the package using pip:

```bash
pip install django-activitypub-toolkit
```

Or add it to your `requirements.txt`:

```
django-activitypub-toolkit>=0.0.2
```

## Add to Django Project

Add the toolkit to your `INSTALLED_APPS` in `settings.py`:

```python
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Your existing apps
    'blog',  # example
    'accounts',  # example
    # Add the toolkit
    'activitypub',
]
```

## Configure Federation Settings

Add basic federation configuration to your settings:

```python
FEDERATION = {
    'DEFAULT_URL': 'http://localhost:8000',  # Change for production
    'SOFTWARE_NAME': 'YourAppName',
    'SOFTWARE_VERSION': '1.0.0',
}
```

For production, use your actual domain:

```python
FEDERATION = {
    'DEFAULT_URL': 'https://yourdomain.com',
    'SOFTWARE_NAME': 'YourAppName',
    'SOFTWARE_VERSION': '1.0.0',
}
```

## Run Migrations

Create the database tables for federation:

```bash
python manage.py migrate activitypub
```

This creates tables for:

- References (URI pointers)
- Context models (federation data)
- Notifications (incoming activities)
- Domains and accounts

## Verify Installation

Start your Django development server:

```bash
python manage.py runserver
```

The toolkit is now installed and ready for configuration. Next, see [Configure the Toolkit](configure_toolkit.md) to set up your federation settings.
