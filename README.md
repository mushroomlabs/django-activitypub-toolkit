# Django ActivityPub Toolkit

[![PyPI
version](https://badge.fury.io/py/django-activitypub-toolkit.svg)](https://pypi.org/project/django-activitypub-toolkit/)
[![Python
versions](https://img.shields.io/pypi/pyversions/django-activitypub-toolkit.svg)](https://pypi.org/project/django-activitypub-toolkit/)
[![Django
versions](https://img.shields.io/badge/Django-4.2%2B-blue.svg)](https://www.djangoproject.com/)

A comprehensive Django application that brings ActivityPub federation
to your web projects. Transform your Django applications into active
participants in the decentralized social web.

## What is ActivityPub?

ActivityPub is the protocol that powers the decentralized social web,
enabling different social platforms to communicate and share content
seamlessly. It's the technology behind Mastodon, PeerTube, and many
other federated services.

## Philosophy

**Reference-First Architecture**: Instead of replicating social graph
data, we use references to connect your application data to the
federated social graph. This approach keeps your business logic pure
while enabling federation.

**Vocabulary Agnostic**: Support any ActivityStreams vocabulary
through extensible context models. Whether you're building a
microblog, video platform, or something entirely new, the toolkit
adapts to your domain.

**Standards Compliant**: Full ActivityPub implementation with proper
HTTP signatures, JSON-LD contexts, and WebFinger discovery.

## Quick Start

```bash
pip install django-activitypub-toolkit
```

Add to your Django settings:

```python
INSTALLED_APPS = [
    # ... your other apps
    'activitypub',
]

FEDERATION = {
    'DEFAULT_URL': 'https://yourdomain.com',
}
```

## Features

- **Complete ActivityPub Implementation**: Server-to-server and
  client-to-server APIs
- **Reference Architecture**: Connect existing Django models to the
  fediverse
- **Extensible Contexts**: Support custom vocabularies and platform
  extensions
- **Background Processing**: Celery-based task processing for
  federation activities
- **Security**: HTTP signature verification and cryptographic key
  management
- **WebFinger**: Automatic actor discovery and profile resolution

## Relevant Links

 - [Full Documentation](https://activitypub.mushroomlabs.com)
 - [Issues](https://codeberg.org/mushroomlabs/django-activitypub-toolkit/issues)

## License

BSD 3-Clause License - see [LICENSE](LICENSE) file for details.
