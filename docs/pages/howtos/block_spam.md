# Block Spam and Malicious Servers

This guide shows you how to block domains and filter unwanted content in your federated application.

## Block a Domain

Block a domain to reject all activities from it:

```python
from activitypub.core.models import Domain

domain = Domain.objects.get(name="spam.example")
domain.blocked = True
domain.save()
```

The toolkit automatically rejects activities from blocked domains with a 403 Forbidden response at the inbox level.

## Filter Content Before Processing

Create a document processor to reject activities based on content:

```python
import logging

import rdflib

from activitypub.core.contexts import AS2
from activitypub.core.exceptions import DropMessage
from activitypub.core.models import LinkedDataDocument
from activitypub.core.processors import DocumentProcessor

logger = logging.getLogger(__name__)


class SpamFilterProcessor(DocumentProcessor):
    def process_incoming(self, document):
        if not document:
            return

        try:
            g = LinkedDataDocument.get_graph(document)
            subject_uri = rdflib.URIRef(document["id"])

            obj_uri = g.value(subject=subject_uri, predicate=AS2.object)
            if obj_uri:
                content = g.value(subject=obj_uri, predicate=AS2.content)
                if content and 'spam' in str(content).lower():
                    logger.info(f"Dropping spam activity {document['id']}")
                    raise DropMessage("Spam content detected")
        except (KeyError, AssertionError):
            pass
```

Register in settings:

```python
FEDERATION = {
    'DOCUMENT_PROCESSORS': [
        'activitypub.core.processors.ActorDeletionDocumentProcessor',
        'activitypub.core.processors.CompactJsonLdDocumentProcessor',
        'yourapp.processors.SpamFilterProcessor',
    ],
}
```

Document processors run before activities are parsed. Raising `DropMessage` prevents further processing.

## Automatically Block Domains

Use signal handlers to automatically block domains based on patterns:

```python
import logging
from datetime import timedelta

from django.dispatch import receiver
from django.utils import timezone

from activitypub.core.models import Activity
from activitypub.core.signals import activity_done

logger = logging.getLogger(__name__)


@receiver(activity_done)
def auto_block_spam_domains(sender, activity, **kwargs):
    if not activity.actor or not activity.actor.domain:
        return

    domain = activity.actor.domain

    if domain.blocked:
        return

    # Check for excessive posting (more than 100 activities per hour)
    recent_count = Activity.objects.filter(
        actor__domain=domain,
        published__gte=timezone.now() - timedelta(hours=1)
    ).count()

    if recent_count > 100:
        domain.blocked = True
        domain.save()
        logger.warning(f"Auto-blocked domain {domain.name} for excessive posting")
```

Register in your app's `apps.py`:

```python
from django.apps import AppConfig


class YourAppConfig(AppConfig):
    name = 'yourapp'

    def ready(self):
        import yourapp.handlers
```

## Understanding the Architecture

The toolkit provides three levels for moderation:

1. **Inbox view** - Checks `domain.blocked` before creating notifications (returns 403)
2. **Document processors** - Filter before parsing (raise `DropMessage`)
3. **Signal handlers** - React after processing (for automatic blocking)

**Note**: In signal handlers, `activity.actor` is a `Reference` object, not a full `ActorContext`. See [Reference and Context Architecture](../topics/reference_context_architecture.md) for details.

## When to Use Each Approach

- **Manual blocking** - Use Django admin or management commands
- **Content filtering** - Use document processors to raise `DropMessage`
- **Automatic blocking** - Use `activity_done` signal handlers to analyze patterns

## Further Reading

- [Content Moderation Tutorial](../tutorials/content_moderation.md) - Build a complete moderation system
- [Handle Incoming Activities](handle_incoming_activities.md) - Work with signals
- [Reference and Context Architecture](../topics/reference_context_architecture.md) - Understand References vs Contexts
