# Content Moderation and Spam Prevention

This tutorial teaches you how to build a content moderation system for your federated application. You'll learn to block malicious domains, filter spam content, implement rate limiting, and create a moderation queue.

By the end of this tutorial, you'll have a working moderation system that protects your users from spam and abuse while maintaining a healthy federated community.

## What You'll Build

- Domain blocking system with admin interface
- Automatic spam detection based on content patterns
- Rate limiting to prevent abuse
- Moderation queue for suspicious activities
- User-level blocking

## Prerequisites

- Completed the [Getting Started](getting_started.md) tutorial
- Understanding of [Reference and Context Architecture](../topics/reference_context_architecture.md)
- Familiarity with Django signals and models

## Understanding the Moderation Architecture

The toolkit provides three levels where you can enforce moderation policies:

1. **Inbox view** - Blocks domains before creating notifications (returns 403)
2. **Document processors** - Filter activities before they're parsed (can raise `DropMessage`)
3. **Signal handlers** - React to activities after processing (for automatic blocking)

In signal handlers, `activity.actor` and `activity.object` are `Reference` objects, not full context models. To access actual data, use `.get_by_context()`.

### Set Up Domain Blocking

Start by adding domain blocking to your Django admin.

Create `yourapp/admin.py`:

```python
from django.contrib import admin

from activitypub.core.models import Domain


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ('name', 'local', 'blocked', 'is_active')
    list_filter = ('local', 'blocked', 'is_active')
    search_fields = ('name',)
    actions = ['block_domains', 'unblock_domains']

    def block_domains(self, request, queryset):
        count = queryset.update(blocked=True)
        self.message_user(request, f"Blocked {count} domains")

    def unblock_domains(self, request, queryset):
        count = queryset.update(blocked=False)
        self.message_user(request, f"Unblocked {count} domains")
```

Test it by running your development server and navigating to the admin interface. Block a test domain and verify that activities from that domain are rejected with 403 Forbidden.

The toolkit automatically checks `actor_reference.domain.blocked` in the inbox view before processing any activity.

### Create Automatic Spam Detection

Now you'll build a system that automatically blocks domains sending spam.

Create `yourapp/moderation.py`:

```python
import logging
from datetime import timedelta

from django.dispatch import receiver
from django.utils import timezone

from activitypub.core.models import Activity, ObjectContext
from activitypub.core.signals import activity_done

logger = logging.getLogger(__name__)


@receiver(activity_done)
def check_for_spam(sender, activity, **kwargs):
    # activity.actor is a Reference (ForeignKey), not an ActorContext
    # See: ../topics/reference_context_architecture.md
    if not activity.actor:
        return

    actor_domain = activity.actor.domain

    if actor_domain and actor_domain.blocked:
        return

    if is_spam_activity(activity):
        actor_domain.blocked = True
        actor_domain.save()
        logger.warning(f"Blocked domain {actor_domain.name} for spam")


def is_spam_activity(activity):
    # Check for excessive posting from the same actor (Reference)
    recent_activities = Activity.objects.filter(
        actor=activity.actor,
        published__gte=timezone.now() - timedelta(hours=1)
    ).count()

    if recent_activities > 100:
        return True

    # activity.object is also a Reference, need to get the ObjectContext
    # See: ../topics/reference_context_architecture.md for Reference/Context patterns
    if activity.object:
        obj = activity.object.get_by_context(ObjectContext)
        if obj and obj.content:
            spam_keywords = ['buy now', 'click here', 'limited offer']
            content_lower = obj.content.lower()
            if any(keyword in content_lower for keyword in spam_keywords):
                return True

    return False
```

Register the handlers in `yourapp/apps.py`:

```python
from django.apps import AppConfig


class YourAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'yourapp'

    def ready(self):
        import yourapp.moderation
```

Test by creating a test activity with spam keywords. The domain should be automatically blocked.

### Add Content Filtering with Document Processors

Signal handlers run after activities are processed. To reject activities before they're even loaded, create a document processor.

Create `yourapp/processors.py`:

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
                if content:
                    content_lower = str(content).lower()
                    spam_keywords = ['buy now', 'click here', 'limited offer']
                    if any(keyword in content_lower for keyword in spam_keywords):
                        logger.info(f"Dropping spam activity {document['id']}")
                        raise DropMessage("Spam content detected")
        except (KeyError, AssertionError):
            pass
```

Register it in `settings.py`:

```python
FEDERATION = {
    # ... other settings ...
    'DOCUMENT_PROCESSORS': [
        'activitypub.core.processors.ActorDeletionDocumentProcessor',
        'activitypub.core.processors.CompactJsonLdDocumentProcessor',
        'yourapp.processors.SpamFilterProcessor',
    ],
}
```

Document processors run before the document is parsed into context models. Raising `DropMessage` prevents any further processing and returns a "dropped" status.

### Implement Rate Limiting

Prevent abuse by limiting how many activities a domain can send per hour.

Add to `yourapp/processors.py`:

```python
from django.core.cache import cache

from activitypub.core.models import Reference


def check_rate_limit(domain_name, max_requests=100, window=3600):
    cache_key = f"domain_requests_{domain_name}"
    request_count = cache.get(cache_key, 0)

    if request_count >= max_requests:
        return False

    cache.set(cache_key, request_count + 1, window)
    return True


class RateLimitProcessor(DocumentProcessor):
    def process_incoming(self, document):
        if not document:
            return

        try:
            actor_uri = document.get('actor')
            if not actor_uri:
                return

            actor_ref = Reference.make(actor_uri)
            if not actor_ref.domain:
                return

            domain_name = actor_ref.domain.name

            if not check_rate_limit(domain_name):
                logger.warning(f"Rate limit exceeded for domain {domain_name}")
                actor_ref.domain.blocked = True
                actor_ref.domain.save()
                raise DropMessage("Rate limit exceeded")
        except (KeyError, AttributeError):
            pass
```

Add it to your settings:

```python
FEDERATION = {
    'DOCUMENT_PROCESSORS': [
        'activitypub.core.processors.ActorDeletionDocumentProcessor',
        'activitypub.core.processors.CompactJsonLdDocumentProcessor',
        'yourapp.processors.SpamFilterProcessor',
        'yourapp.processors.RateLimitProcessor',
    ],
}
```

Test by sending multiple activities from the same domain rapidly. After 100 requests in an hour, the domain should be blocked.

### Create a Moderation Queue

Build a queue for suspicious activities that require manual review.

Create `yourapp/models.py`:

```python
from django.contrib.auth.models import User
from django.db import models


class ModerationQueue(models.Model):
    activity_uri = models.CharField(max_length=2083, unique=True)
    reason = models.CharField(max_length=200)
    moderator = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL
    )
    approved = models.BooleanField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.activity_uri} - {self.reason}"
```

Add the processor to `yourapp/processors.py`:

```python
from datetime import timedelta

from django.utils import timezone

from activitypub.core.models import ActorContext

from yourapp.models import ModerationQueue


class ModerationQueueProcessor(DocumentProcessor):
    def process_incoming(self, document):
        if not document:
            return

        try:
            g = LinkedDataDocument.get_graph(document)
            subject_uri = rdflib.URIRef(document["id"])
            actor_uri = g.value(subject=subject_uri, predicate=AS2.actor)

            if not actor_uri:
                return

            actor_ref = Reference.make(str(actor_uri))

            if actor_ref.is_remote and not actor_ref.is_resolved:
                ModerationQueue.objects.create(
                    activity_uri=document["id"],
                    reason="New unresolved remote actor"
                )
                raise DropMessage("Queued for moderation")

            actor = actor_ref.get_by_context(ActorContext)
            if actor and actor.published:
                account_age = timezone.now() - actor.published
                if account_age < timedelta(days=1):
                    ModerationQueue.objects.create(
                        activity_uri=document["id"],
                        reason="Actor account less than 1 day old"
                    )
                    raise DropMessage("Queued for moderation")
        except (KeyError, AttributeError):
            pass
```

Create an admin interface in `yourapp/admin.py`:

```python
from yourapp.models import ModerationQueue


@admin.register(ModerationQueue)
class ModerationQueueAdmin(admin.ModelAdmin):
    list_display = ('activity_uri', 'reason', 'approved', 'moderator', 'created_at')
    list_filter = ('approved', 'created_at')
    search_fields = ('activity_uri', 'reason')
    actions = ['approve_activities', 'reject_activities']

    def approve_activities(self, request, queryset):
        count = queryset.update(approved=True, moderator=request.user)
        self.message_user(request, f"Approved {count} activities")

    def reject_activities(self, request, queryset):
        count = queryset.update(approved=False, moderator=request.user)
        self.message_user(request, f"Rejected {count} activities")
```

Run migrations:

```bash
python manage.py makemigrations
python manage.py migrate
```

Test by sending an activity from a newly created actor. It should appear in the moderation queue.

### Add User-Level Blocking

Allow users to block specific actors.

Add to `yourapp/models.py`:

```python
from activitypub.core.models import Reference


class UserBlock(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    blocked_actor = models.ForeignKey(Reference, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'blocked_actor')
```

Add to `yourapp/moderation.py`:

```python
from yourapp.models import UserBlock


@receiver(activity_done)
def filter_blocked_actors(sender, activity, **kwargs):
    if not activity.actor:
        return

    blocked_by_users = UserBlock.objects.filter(
        blocked_actor=activity.actor
    ).exists()

    if blocked_by_users:
        logger.info(f"Activity from {activity.actor.uri} blocked by user preference")
```

Run migrations and test by creating a user block and verifying that activities from that actor are logged.

### Add Monitoring and Alerts

Send email alerts when domains are automatically blocked.

Add to `yourapp/moderation.py`:

```python
from django.conf import settings
from django.core.mail import send_mail


def send_block_alert(domain):
    send_mail(
        subject=f"Domain {domain.name} has been blocked",
        message=f"Domain {domain.name} was automatically blocked.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=settings.MODERATOR_EMAILS,
    )


@receiver(activity_done)
def alert_on_auto_block(sender, activity, **kwargs):
    if not activity.actor or not activity.actor.domain:
        return

    domain = activity.actor.domain

    if domain.blocked and is_spam_activity(activity):
        send_block_alert(domain)
```

Add to `settings.py`:

```python
MODERATOR_EMAILS = ['moderators@example.com']
```

Test by triggering an automatic block and verifying that an email is sent.

## What You've Learned

You now understand:

- How domain blocking works at the inbox level
- The difference between document processors and signal handlers
- When to use `DropMessage` vs signal-based reactions
- How to work with References vs Context models
- Building a complete moderation system with multiple layers

## Best Practices

- **Start permissive** - Block only when necessary
- **Monitor patterns** - Look for abuse trends before blocking
- **Document reasons** - Keep records of why domains were blocked
- **Regular review** - Periodically review and unblock legitimate domains
- **Graduated response** - Use warnings and rate limits before permanent blocks

## Next Steps

- Implement a public blocklist API for sharing blocked domains
- Add appeal process for blocked users
- Create analytics dashboard for moderation metrics
- Integrate with external spam detection services

## Further Reading

- [Reference and Context Architecture](../topics/reference_context_architecture.md)
- [Handle Incoming Activities](../howtos/handle_incoming_activities.md)
- [Application Settings](../topics/application_settings.md)
