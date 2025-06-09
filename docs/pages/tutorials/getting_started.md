# Getting Started with Django ActivityPub Toolkit

Welcome to Django ActivityPub Toolkit! This tutorial will guide you
through setting up your first ActivityPub server using our framework.
By the end of this tutorial, you'll have a working microblogging server
that can:

- Create and manage user accounts
- Compose and publish blog posts
- Handle basic ActivityPub activities (Create, Follow, Like)
- Interact with other ActivityPub servers

## Prerequisites

Before we begin, make sure you have:

- Python 3.8 or higher installed
- pip (Python package manager)
- A basic understanding of Django (our framework is built on top of Django)
- A text editor or IDE of your choice

## Setting Up Your Development Environment

Let's start by creating a new virtual environment and installing the required packages:

```bash
# Create a new virtual environment
python -m venv venv

# Activate the virtual environment
# On Linux/macOS:
source venv/bin/activate
# On Windows:
.\venv\Scripts\activate

# Install Django ActivityPub Toolkit
pip install django-activitypub-toolkit
```

## Creating Your Microblogging Server

In this section, we'll create a simple microblogging server called "adapt" (A Django ActivityPub Toolkit). We'll use Django's admin interface to compose and manage blog posts.

### 1. Create the Django Project and App

```bash
# Create a new Django project
django-admin startproject adapt
cd adapt

# Create a new app for our blog functionality
python manage.py startapp blog
```

### 2. Configure Your Project

Update `adapt/settings.py` to include our apps and configure ActivityPub:

```python
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'activitypub',  # Add ActivityPub Toolkit
    'blog',  # Add our blog app
]

# ActivityPub settings
ACTIVITYPUB = {
    'DOMAIN': 'localhost:8000',  # Change this in production
}

# Add to your existing settings
STATIC_URL = '/static/'
MEDIA_URL = '/media/'
```

### 3. Create the Blog Models

Create `blog/models.py` to define our account model:

```python
from django.contrib.auth.models import User
from django.db import models
from activitypub.models import Account

class UserAccount(models.Model):
    """A model that associates a Django User with an ActivityPub Account."""
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    account = models.OneToOneField(Account, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.user.username}'s ActivityPub account"
```

### 4. Set Up URL Routing

Create `adapt/urls.py` to handle all our routes:

```python
from activitypub.views import (
    ActivityPubObjectDetailView,
    ActorDetailView,
    HostMeta,
    Webfinger,
)
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path

from blog.views import NodeInfoView

urlpatterns = [
    path(".well-known/nodeinfo", NodeInfoView.as_view(), name="nodeinfo"),
    path(".well-known/webfinger", Webfinger.as_view(), name="webfinger"),
    path(".well-known/host-meta", HostMeta.as_view(), name="host-meta"),
    path("nodeinfo/2.0", NodeInfo2.as_view(), name="nodeinfo20"),
    path("nodeinfo/2.0.json", NodeInfo2.as_view(), name="nodeinfo20-json"),
    path("@<str:subject_name>", ActorDetailView.as_view(), name="actor-detail-by-subject-name"),
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns.extend(static(settings.STATIC_URL, document_root=settings.STATIC_ROOT))
    urlpatterns.extend(static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT))

urlpatterns.append(
    path("<path:resource>", ActivityPubObjectDetailView.as_view(), name="activitypub-resource")
)
```

### 5. Create the NodeInfo View

Create `blog/views.py` to handle server information:

```python
from django.urls import reverse
from activitypub.views.activitystreams import ActorDetailView
from activitypub.views.discovery import NodeInfo2
from blog.models import UserAccount

class NodeInfoView(NodeInfo2):
    def get_usage(self):
        return {"users": {"total": UserAccount.objects.count()}}

__all__ = ("NodeInfoView",)
```

### 6. Register Models in Admin

Create `blog/admin.py` to make our models manageable in the admin interface:

```python
from django.contrib import admin
from blog.models import UserAccount

@admin.register(UserAccount)
class UserAccountAdmin(admin.ModelAdmin):
    list_display = ('user', 'account')
    search_fields = ('user__username',)
```

### 7. Run Migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

## Testing Your Microblogging Server

Let's verify that your server is working:

1. Start the development server:
```bash
python manage.py runserver
```

2. Create a superuser:
```bash
python manage.py createsuperuser
```

3. Visit http://localhost:8000/admin and log in with your superuser credentials.

4. Create a new user account:
   - Go to the admin interface
   - Create a new Django User
   - Create a new UserAccount and associate it with the User
   - The system will automatically create an ActivityPub Account

5. Create a blog post:
   - In the admin interface, go to ActivityPub Objects
   - Click "Add Object"
   - Set the type to "Note"
   - Fill in the content
   - Set the attributedTo field to your user's account
   - Save the object

## Understanding What We've Built

Let's break down what we've created:

1. **Project Structure**:
   - `adapt/`: The main Django project
   - `blog/`: Our application for user account management
   - Models for user accounts
   - Views for server information and ActivityPub endpoints

2. **ActivityPub Integration**:
   - We use ActivityPub's built-in `Object` model for all content
   - User accounts are linked to ActivityPub accounts
   - All objects are automatically available as ActivityPub resources
   - The server supports standard ActivityPub endpoints

3. **Linked Data Principles**:
   - Our framework follows Linked Data principles
   - A single view handles all ActivityPub requests
   - URLs are determined by the object's properties
   - All objects are automatically serialized to ActivityPub format

## Further Learning

- Check out the [How-to Guides](../howtos/index.md) for specific tasks
- Read the [Reference](../references/index.md) for detailed API documentation
- Explore the [Topics](../topics/index.md) section for in-depth explanations of ActivityPub concepts

Remember, this is just the beginning! ActivityPub is a powerful protocol, and our framework makes it easy to build sophisticated social applications. As you continue learning, you'll discover more features and capabilities that you can add to your server.
