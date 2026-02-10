# Handle Incoming Activities

This guide shows you how to process activities received from other Fediverse servers using custom handlers.

## Understanding Activity Delivery

When users on other servers interact with your content, their servers send activities to your inboxes. The toolkit automatically handles the complete delivery pipeline:

1. Receives HTTP POST requests to inbox endpoints
2. Verifies HTTP signatures for authentication
3. Checks if the sender's domain is blocked
4. Creates a `Notification` record and queues async processing
5. Parses JSON-LD activity documents (in Celery task)
6. Sanitizes and validates the graph
7. Stores activities in context models
8. Processes standard ActivityPub flows via `Activity.do()` (Follow, Like, Announce, etc.)
9. Triggers the `activity_done` signal

**For standard ActivityPub activities, the toolkit handles everything automatically.** You only need custom handlers for application-specific logic beyond the standard protocol behavior.

## When to Write Custom Handlers

You only need custom handlers when:

- **Sending user notifications** - Email or push notifications when someone follows or mentions a user
- **Moderation workflows** - Alert moderators when Flag activities arrive
- **Application-specific state** - Update non-ActivityPub models in your application
- **Custom validation** - Implement business rules beyond standard ActivityPub semantics (use `notification_accepted` signal)
- **Integration hooks** - Trigger external services or webhooks

If you just need to track likes, follows, and shares, **you don't need custom handlers**. The toolkit maintains collections automatically through `Activity.do()`.

## Automatic Processing

The toolkit automatically handles these standard activities via the `Activity.do()` method:

- **Follow** - Creates `FollowRequest` records, adds to following/followers collections when accepted
- **Like** - Adds to the object's `likes` collection and actor's `liked` collection
- **Announce** - Adds to the object's `shares` collection
- **Add/Remove** - Manages collection membership
- **Undo** - Reverses previous activities (unfollows, unlikes, etc.)
- **Accept/Reject** - Processes follow request responses

These work out of the box without any custom code. The `activity_done` signal fires after this automatic processing completes.

## Available Signals

The toolkit provides two signals for custom handling:

### `notification_accepted`

Fires **after** the document is loaded but **before** `Activity.do()` runs. Use this to react to incoming activities or trigger async processing.

```python
from django.dispatch import receiver

from activitypub.core.signals import notification_accepted


@receiver(notification_accepted)
def log_incoming_activity(sender, notification, **kwargs):
    logger.info(f"Received activity {notification.resource.uri} from {notification.sender.uri}")
```

**Note**: To reject activities before processing, use a custom `DocumentProcessor` instead of signal handlers. See the [Block Spam](block_spam.md) guide for examples.

### `activity_done`

Fires **after** standard activity processing completes. Use this for application-specific logic.

```python
from django.dispatch import receiver

from activitypub.core.models import Activity
from activitypub.core.signals import activity_done


@receiver(activity_done)
def handle_activity(sender, activity, **kwargs):
    if activity.type == Activity.Types.LIKE:
        handle_like_notification(activity)
```

## Implement Custom Handlers

Connect to Django signals to add application-specific logic.

**Note**: In signal handlers, `activity.actor` and `activity.object` are `Reference` objects (ForeignKeys), not full context models. To access the actual data (like actor names or object content), use `.get_by_context()`. See the [Reference and Context Architecture](../topics/reference_context_architecture.md) topic guide for details.

```python
import logging

from django.dispatch import receiver

from activitypub.core.models import Activity
from activitypub.core.signals import activity_done

logger = logging.getLogger(__name__)


@receiver(activity_done)
def handle_activity(sender, activity, **kwargs):
    if activity.type == Activity.Types.LIKE:
        handle_like_notification(activity)
    elif activity.type == Activity.Types.FOLLOW:
        handle_follow_notification(activity)
    elif activity.type == Activity.Types.FLAG:
        handle_moderation_flag(activity)
```

Register handlers in your app's `apps.py`:

```python
from django.apps import AppConfig


class YourAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'yourapp'

    def ready(self):
        import yourapp.handlers
```

## Send User Notifications

Notify users when they receive interactions:

```python
from django.core.mail import send_mail

from yourapp.models import Post, UserProfile


def handle_like_notification(activity):
    try:
        post = Post.objects.get(reference=activity.object)

        send_mail(
            subject='Your post was liked',
            message=f'{activity.actor.uri} liked your post: {post.title}',
            from_email='noreply@example.com',
            recipient_list=[post.author.email],
        )

    except Post.DoesNotExist:
        pass


def handle_follow_notification(activity):
    try:
        profile = UserProfile.objects.get(actor_reference=activity.object)

        send_mail(
            subject='New follower',
            message=f'{activity.actor.uri} is now following you',
            from_email='noreply@example.com',
            recipient_list=[profile.user.email],
        )

    except UserProfile.DoesNotExist:
        pass
```

## Handle Moderation Flags

Process Flag activities for content moderation:

```python
import logging

from django.core.mail import send_mail

from activitypub.core.models import ObjectContext
from yourapp.models import Post

logger = logging.getLogger(__name__)


def handle_moderation_flag(activity):
    try:
        flagged_ref = activity.object
        post = Post.objects.get(reference=flagged_ref)

        flagger_uri = activity.actor.uri

        obj = activity.reference.get_by_context(ObjectContext)
        reason = obj.content if obj else "No reason provided"

        send_mail(
            subject=f'Content flagged: {post.title}',
            message=f'User {flagger_uri} flagged post {post.id}\n\nReason: {reason}',
            from_email='noreply@example.com',
            recipient_list=['moderators@example.com'],
        )

        logger.info(f"Sent moderation alert for post {post.id}")

    except Post.DoesNotExist:
        logger.warning(f"Flag activity for unknown object {flagged_ref.uri}")
```

## Update Application Models

Sync ActivityPub events with your application's models:

```python
from django.utils import timezone

from yourapp.models import Like, Post


def handle_like_notification(activity):
    try:
        post = Post.objects.get(reference=activity.object)

        Like.objects.get_or_create(
            post=post,
            actor_uri=activity.actor.uri,
            defaults={
                'activity_reference': activity.reference,
                'created_at': activity.published or timezone.now(),
            }
        )

        post.like_count = Like.objects.filter(post=post).count()
        post.save()

    except Post.DoesNotExist:
        pass
```

## Custom Authorization

Enforce application-specific policies using a document processor:

```python
import rdflib

from activitypub.core.contexts import AS2
from activitypub.core.exceptions import DropMessage
from activitypub.core.models import LinkedDataDocument
from activitypub.core.processors import DocumentProcessor
from yourapp.models import BlockedUser


class UserBlockProcessor(DocumentProcessor):
    def process_incoming(self, document):
        if not document:
            return

        try:
            g = LinkedDataDocument.get_graph(document)
            subject_uri = rdflib.URIRef(document["id"])
            actor_uri = g.value(subject=subject_uri, predicate=AS2.actor)

            if not actor_uri:
                return

            if BlockedUser.objects.filter(actor_uri=str(actor_uri)).exists():
                logger.info(f"Rejecting activity from blocked user {actor_uri}")
                raise DropMessage("Actor is blocked")
        except (KeyError, AttributeError):
            pass
```

Register in settings:

```python
FEDERATION = {
    'DOCUMENT_PROCESSORS': [
        'activitypub.core.processors.ActorDeletionDocumentProcessor',
        'activitypub.core.processors.CompactJsonLdDocumentProcessor',
        'yourapp.processors.UserBlockProcessor',
    ],
}
```

Document processors run before the activity is loaded into context models, allowing you to reject activities early.

## Auto-Accept Follow Requests

Automatically accept follow requests instead of requiring manual approval:

```python
from django.dispatch import receiver

from activitypub.core.models import Activity, FollowRequest
from activitypub.core.signals import activity_done


@receiver(activity_done)
def auto_accept_follows(sender, activity, **kwargs):
    if activity.type != Activity.Types.FOLLOW:
        return

    try:
        request = FollowRequest.objects.get(activity=activity.reference)
        if request.status == FollowRequest.STATUS.submitted:
            request.accept()
    except FollowRequest.DoesNotExist:
        pass
```

The `FollowRequest.accept()` method handles adding the follower to the followers collection and sending the Accept activity.

## Track Activity Statistics

Maintain statistics about federated interactions:

```python
from django.dispatch import receiver
from django.utils import timezone

from activitypub.core.models import Activity
from activitypub.core.signals import activity_done
from yourapp.models import ActivityStats


@receiver(activity_done)
def update_activity_stats(sender, activity, **kwargs):
    stats, created = ActivityStats.objects.get_or_create(
        date=timezone.now().date()
    )

    if activity.type == Activity.Types.LIKE:
        stats.likes_received += 1
    elif activity.type == Activity.Types.FOLLOW:
        stats.follows_received += 1
    elif activity.type == Activity.Types.ANNOUNCE:
        stats.shares_received += 1

    stats.save()
```

## Error Handling

Handle processing errors gracefully without blocking other activities:

```python
import logging

from django.dispatch import receiver

from activitypub.core.signals import activity_done

logger = logging.getLogger(__name__)


@receiver(activity_done)
def safe_handler(sender, activity, **kwargs):
    try:
        process_activity(activity)
    except Exception as e:
        logger.error(
            f"Error processing activity {activity.reference.uri}: {e}",
            exc_info=True
        )
```

## Testing Custom Handlers

Test your handlers by simulating incoming activities:

```python
from django.core import mail
from django.test import TestCase

from activitypub.core.models import ActivityContext, Domain, Reference
from activitypub.core.signals import activity_done


class ActivityHandlerTest(TestCase):
    def test_like_notification(self):
        domain = Domain.get_default()
        activity_ref = ActivityContext.generate_reference(domain)

        activity = ActivityContext.make(
            reference=activity_ref,
            type=ActivityContext.Types.LIKE,
            actor=Reference.make('https://example.com/users/alice'),
            object=self.post.reference,
        )

        activity_done.send(sender=ActivityContext, activity=activity)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('liked', mail.outbox[0].subject)
```

## What You DON'T Need to Do

The toolkit handles these automatically through `Activity.do()` - **you don't need custom handlers for**:

- Adding likes to the `likes` collection
- Adding shares to the `shares` collection
- Adding followers to the `followers` collection
- Creating `FollowRequest` records
- Processing Undo activities (unfollows, unlikes)
- Managing collection membership (Add/Remove activities)
- Adding activities to inbox collections
- Processing Accept/Reject for follow requests

These all work out of the box through the toolkit's built-in `Activity.do()` method.

## Signal Flow Summary

```
Inbox POST
    ↓
Domain block check (in view)
    ↓
Create Notification + LinkedDataDocument
    ↓
Queue Celery task: process_incoming_notification
    ↓
Authenticate HTTP signature
    ↓
Load document: sanitize + validate graph
    ↓
Fire: notification_accepted signal ← Use for early validation/filtering
    ↓
Add activity to inbox collection
    ↓
Queue Celery task: process_standard_activity_flows
    ↓
Call Activity.do() ← Automatic collection management
    ↓
Fire: activity_done signal ← Use for application-specific logic
```

## Next Steps

With custom activity handlers implemented, you can:

- [Send activities](send_activities.md) to publish your content
- [Block spam](block_spam.md) from malicious servers
- Review the [integration tutorial](../tutorials/integration_with_existing_project.md) for complete setup
