---
hide:
  - navigation
  - toc
---


{% include "sponsors.md" %}

# Django ActivityPub Toolkit

*Django ActivityPub Toolkit* brings federation to your Django
applications. Whether you're building a blog, a project management
tool, or a collaborative platform, add ActivityPub support without
rebuilding your app from scratch.

## Powerful abstractions for the Social Web. Still Django at heart.

Django ActivityPub Toolkit follows Django conventions. Built for
developers who want to integrate with the Fediverse, it handles
federation infrastructure so you can focus on your application's
unique features. It provides models, views, serializers, and admin
interfaces that work seamlessly with your existing Django project.
Install it as an app, run migrations, and start federating.

[Get started with Django ActivityPub
Toolkit](tutorials/getting_started.md)

## Build on the social graph.

Instead of replicating followers and social connections in every
federated application, your app operates on the social graph that
already exists across the Fediverse. Users bring their identity and
connections. You add capabilities.

[See what you can build](tutorials/index.md)

## Standards compliant.

Django ActivityPub Toolkit implements ActivityPub, ActivityStreams
2.0, JSON-LD, HTTP Signatures, and WebFinger. Full support for the W3C
specifications means your application interoperates with Mastodon,
Pixelfed, PeerTube, and the entire Fediverse.

[Learn about the architecture](topics/index.md)

## Separation of concerns.

Your application models handle business logic. ActivityPub context
models handle federation vocabulary. References connect the two
layers. This clean separation lets you evolve your application
independently of federation concerns.

[Read about references and context
models](topics/reference_context_architecture.md)

## Production ready.

Django ActivityPub Toolkit powers production applications. It handles
HTTP Signature verification, background task processing, collection
pagination, domain moderation, and multi-domain hosting from a single
installation.

[Integrate with your existing
project](tutorials/integration_with_existing_project.md)

# Quick Installation

Install the package:

```bash
pip install django-activitypub-toolkit
```

Add to your `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # Your existing apps
    'activitypub',
]
```

Configure your server:

```python
FEDERATION = {
    'DEFAULT_URL': 'https://yourdomain.com',
    'SOFTWARE_NAME': 'YourApp',
    'SOFTWARE_VERSION': '1.0.0',
}
```

Run migrations:

```bash
python manage.py migrate activitypub
```

Connect your models to the Fediverse:

```python
from django.db import models
from activitypub.models import Reference

class BlogPost(models.Model):
    reference = models.OneToOneField(
        Reference,
        on_delete=models.CASCADE,
        related_name='blog_post'
    )
    title = models.CharField(max_length=200)
    content = models.TextField()
    author = models.ForeignKey(User, on_delete=models.CASCADE)
```

[Follow the complete tutorial](tutorials/getting_started.md)

# What Django ActivityPub Toolkit Includes

**Reference-based architecture** - Connect your models to the
federated graph using stable URI references.

**Context models** - Built-in support for ActivityStreams vocabulary
with extensible custom contexts.

**HTTP Signatures** - Cryptographic verification of incoming
activities with multiple algorithm support.

**WebFinger discovery** - Built-in views for account discovery and
server metadata.

**Collection management** - Ordered and unordered collections with
pagination support.

**Activity handlers** - Extensible framework for processing incoming
federated activities.

**Admin interfaces** - Django admin integration for managing actors,
activities, and federation.

**Pull-based resolution** - Lazy loading of remote resources reduces
storage and respects privacy.

[Explore all features](topics/index.md)

# Related Work

**[Vocata](https://codeberg.org/Vocata/vocata)** - Demonstrated
treating the Fediverse as a global shared graph rather than isolated
platforms.

**[Takahē](https://jointakahe.org/)** - Pioneered multi-domain
ActivityPub servers, separating infrastructure from identity.

# Get Involved

Django ActivityPub Toolkit is open source software. Contributions, bug
reports, and feedback are welcome.

**Repository**: [Codeberg -
mushroomlabs/django-activitypub-toolkit](https://codeberg.org/mushroomlabs/django-activitypub-toolkit)

**License**: Check repository for details
