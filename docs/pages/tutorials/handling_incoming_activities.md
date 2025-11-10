---
title: Handling Incoming Activities
---

This tutorial teaches you how to process ActivityPub activities delivered to your server's inbox. You will learn to set up inbox endpoints, authenticate incoming requests, process notifications, and implement activity handlers that update your application state.

By the end of this tutorial, you will understand the complete pipeline from receiving an HTTP POST at an inbox to updating your database based on federated actions.

## Understanding Inbox Delivery

ActivityPub uses inboxes for push-based delivery. When a user on a remote server performs an action—following you, liking your post, replying to your entry—that server POSTs an activity to your inbox. The activity is a JSON-LD document describing what happened.

Your server receives the POST request, authenticates it, stores the activity, and processes it. Processing might create database records, send notifications to users, or trigger side effects. The inbox accepts the request quickly and processes it asynchronously to avoid blocking the sender.

The toolkit provides the infrastructure for this pipeline. Your application implements handlers that define what happens when specific activity types arrive.

## Setting Up an Inbox View

An inbox is a collection that receives activities. Actors have personal inboxes. Servers can have shared inboxes that receive activities for multiple local actors. Start by creating an actor with an inbox for your journal application.

Update your journal entry user model to include actor information in `journal/models.py`:

```python
from activitypub.models import Reference, ActorContext, CollectionContext, Domain
from django.contrib.auth.models import User

class UserProfile(models.Model):
    """Links Django users to ActivityPub actors."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    actor_reference = models.OneToOneField(
        Reference,
        on_delete=models.CASCADE,
        related_name='user_profile'
    )
    
    @classmethod
    def create_for_user(cls, user):
        """Create an actor and profile for a Django user."""
        domain = Domain.get_default()
        actor_ref = ActorContext.generate_reference(domain)
        
        # Create actor context
        actor = ActorContext.make(
            reference=actor_ref,
            type=ActorContext.Types.PERSON,
            preferred_username=user.username,
            name=user.get_full_name() or user.username,
        )
        
        # Create inbox collection
        inbox_ref = CollectionContext.generate_reference(domain)
        inbox = CollectionContext.make(
            reference=inbox_ref,
            type=CollectionContext.Types.ORDERED_COLLECTION,
        )
        actor.inbox = inbox_ref
        actor.save()
        
        # Create outbox collection
        outbox_ref = CollectionContext.generate_reference(domain)
        outbox = CollectionContext.make(
            reference=outbox_ref,
            type=CollectionContext.Types.ORDERED_COLLECTION,
        )
        actor.outbox = outbox_ref
        actor.save()
        
        # Create profile
        profile = cls.objects.create(
            user=user,
            actor_reference=actor_ref
        )
        
        return profile
    
    @property
    def actor(self):
        """Access the actor context."""
        return self.actor_reference.get_by_context(ActorContext)
```

Create profiles for existing users with a management command in `journal/management/commands/create_profiles.py`:

```python
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from journal.models import UserProfile

class Command(BaseCommand):
    help = 'Create actor profiles for users without them'
    
    def handle(self, *args, **options):
        users_without_profiles = User.objects.filter(profile__isnull=True)
        
        for user in users_without_profiles:
            profile = UserProfile.create_for_user(user)
            self.stdout.write(
                self.style.SUCCESS(f'Created profile for {user.username}')
            )
```

Run migrations and create profiles:

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py create_profiles
```

## Inbox View Implementation

The toolkit provides `ActivityPubObjectDetailView` which handles both GET and POST requests. GET serves the resource as JSON-LD. POST to an inbox creates a notification for processing.

Create an inbox view in `journal/views.py`:

```python
from activitypub.views import ActivityPubObjectDetailView
from activitypub.models import Reference
from django.shortcuts import get_object_or_404
from journal.models import UserProfile

class UserInboxView(ActivityPubObjectDetailView):
    """Handle inbox delivery for a specific user."""
    
    def get_object(self):
        username = self.kwargs.get('username')
        profile = get_object_or_404(UserProfile, user__username=username)
        return profile.actor.inbox
```

Update `journal/urls.py`:

```python
from django.urls import path
from journal.views import EntryDetailView, UserInboxView

app_name = 'journal'

urlpatterns = [
    path('entries/<int:pk>', EntryDetailView.as_view(), name='entry-detail'),
    path('users/<str:username>/inbox', UserInboxView.as_view(), name='user-inbox'),
]
```

The view retrieves the user's actor, then returns their inbox reference. When a POST arrives, `ActivityPubObjectDetailView` handles it automatically: extracting the activity document, creating a notification, storing the document, and queuing it for processing.

## The Notification Model

When an activity arrives at an inbox, the toolkit creates a `Notification` instance. This model links:

- `sender` - Reference to the actor who sent the activity
- `target` - Reference to the inbox that received it
- `resource` - Reference to the activity itself

The notification also tracks authentication state through related `NotificationIntegrityProof` and `NotificationProofVerification` records. An HTTP signature proof is created if the request included a signature header.

Processing happens asynchronously through the `process_incoming_notification` task. This task authenticates the notification and triggers activity processing.

## Activity Processing Pipeline

Activity processing follows these steps:

1. **Authentication** - Verify the HTTP signature using the sender's public key
2. **Document Loading** - Parse the JSON-LD into an RDF graph and populate context models
3. **Signal Emission** - Fire signals that application handlers can connect to
4. **State Updates** - Handlers update application models based on the activity

The toolkit handles steps 1-3. Your application implements step 4 through signal handlers.

## Implementing Activity Handlers

Activity handlers connect to Django signals that fire when specific activity types are processed. The toolkit provides signals for common activities.

Create a handlers module in `journal/handlers.py`:

```python
import logging
from django.dispatch import receiver
from activitypub.signals import activity_processed
from activitypub.models import ActivityContext, ObjectContext, ActorContext

logger = logging.getLogger(__name__)

@receiver(activity_processed)
def handle_activity(sender, activity, **kwargs):
    """Route activities to specific handlers based on type."""
    activity_ctx = activity.get_by_context(ActivityContext)
    if not activity_ctx:
        logger.warning(f"Could not get ActivityContext for {activity.uri}")
        return
    
    activity_type = activity_ctx.type
    
    handlers = {
        ActivityContext.Types.CREATE: handle_create,
        ActivityContext.Types.LIKE: handle_like,
        ActivityContext.Types.ANNOUNCE: handle_announce,
        ActivityContext.Types.FOLLOW: handle_follow,
    }
    
    handler = handlers.get(activity_type)
    if handler:
        handler(activity_ctx)
    else:
        logger.info(f"No handler for activity type {activity_type}")

def handle_create(activity):
    """Handle Create activities - someone created content."""
    logger.info(f"Processing Create activity {activity.reference.uri}")
    
    # Get the object that was created
    obj_ref = activity.object
    if not obj_ref:
        logger.warning("Create activity has no object")
        return
    
    # Resolve the object if it's remote
    if not obj_ref.is_resolved:
        obj_ref.resolve()
    
    obj_ctx = obj_ref.get_by_context(ObjectContext)
    if not obj_ctx:
        logger.warning(f"Could not get ObjectContext for {obj_ref.uri}")
        return
    
    # Check if this is a reply to one of our entries
    if obj_ctx.in_reply_to:
        handle_reply(obj_ctx)

def handle_reply(obj):
    """Handle a reply to one of our journal entries."""
    from journal.models import JournalEntry, Reply
    
    # Check if the reply is to a local entry
    try:
        entry = JournalEntry.objects.get(reference=obj.in_reply_to)
    except JournalEntry.DoesNotExist:
        logger.info(f"Reply to unknown entry {obj.in_reply_to.uri}")
        return
    
    # Create a reply record
    Reply.objects.get_or_create(
        entry=entry,
        reply_reference=obj.reference,
        defaults={
            'content': obj.content,
            'author_reference': obj.attributed_to,
            'published': obj.published,
        }
    )
    
    logger.info(f"Recorded reply from {obj.attributed_to.uri} to entry {entry.id}")

def handle_like(activity):
    """Handle Like activities - someone liked content."""
    logger.info(f"Processing Like activity {activity.reference.uri}")
    
    from journal.models import JournalEntry, Like
    
    # Get what was liked
    obj_ref = activity.object
    if not obj_ref:
        return
    
    # Check if it's one of our entries
    try:
        entry = JournalEntry.objects.get(reference=obj_ref)
    except JournalEntry.DoesNotExist:
        logger.info(f"Like for unknown entry {obj_ref.uri}")
        return
    
    # Record the like
    Like.objects.get_or_create(
        entry=entry,
        actor_reference=activity.actor,
        defaults={
            'activity_reference': activity.reference,
        }
    )
    
    logger.info(f"Recorded like from {activity.actor.uri} for entry {entry.id}")

def handle_announce(activity):
    """Handle Announce activities - someone shared/boosted content."""
    logger.info(f"Processing Announce activity {activity.reference.uri}")
    
    from journal.models import JournalEntry, Announce
    
    obj_ref = activity.object
    if not obj_ref:
        return
    
    try:
        entry = JournalEntry.objects.get(reference=obj_ref)
    except JournalEntry.DoesNotExist:
        logger.info(f"Announce for unknown entry {obj_ref.uri}")
        return
    
    Announce.objects.get_or_create(
        entry=entry,
        actor_reference=activity.actor,
        defaults={
            'activity_reference': activity.reference,
            'published': activity.published,
        }
    )
    
    logger.info(f"Recorded announce from {activity.actor.uri} for entry {entry.id}")

def handle_follow(activity):
    """Handle Follow activities - someone wants to follow a local user."""
    logger.info(f"Processing Follow activity {activity.reference.uri}")
    
    from journal.models import UserProfile, FollowRequest
    
    # Get who is being followed
    followed_ref = activity.object
    if not followed_ref:
        return
    
    try:
        profile = UserProfile.objects.get(actor_reference=followed_ref)
    except UserProfile.DoesNotExist:
        logger.info(f"Follow for unknown actor {followed_ref.uri}")
        return
    
    # Create a follow request
    FollowRequest.objects.get_or_create(
        profile=profile,
        follower_reference=activity.actor,
        defaults={
            'activity_reference': activity.reference,
        }
    )
    
    logger.info(f"Recorded follow request from {activity.actor.uri} to {profile.user.username}")
```

Create the application models these handlers reference in `journal/models.py`:

```python
class Reply(models.Model):
    """A reply to a journal entry from a remote user."""
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name='replies')
    reply_reference = models.ForeignKey(Reference, on_delete=models.CASCADE)
    author_reference = models.ForeignKey(
        Reference,
        on_delete=models.CASCADE,
        related_name='replies_authored'
    )
    content = models.TextField()
    published = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['published']
        unique_together = ['entry', 'reply_reference']

class Like(models.Model):
    """A like on a journal entry."""
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name='likes')
    actor_reference = models.ForeignKey(Reference, on_delete=models.CASCADE)
    activity_reference = models.ForeignKey(
        Reference,
        on_delete=models.CASCADE,
        related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['entry', 'actor_reference']

class Announce(models.Model):
    """A share/boost of a journal entry."""
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name='announces')
    actor_reference = models.ForeignKey(Reference, on_delete=models.CASCADE)
    activity_reference = models.ForeignKey(
        Reference,
        on_delete=models.CASCADE,
        related_name='+'
    )
    published = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['entry', 'actor_reference']

class FollowRequest(models.Model):
    """A request to follow a local user."""
    profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='follow_requests')
    follower_reference = models.ForeignKey(Reference, on_delete=models.CASCADE)
    activity_reference = models.ForeignKey(
        Reference,
        on_delete=models.CASCADE,
        related_name='+'
    )
    accepted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['profile', 'follower_reference']
```

Register the handlers in your app's `apps.py`:

```python
from django.apps import AppConfig

class JournalConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'journal'
    
    def ready(self):
        import journal.handlers  # noqa
```

Run migrations:

```bash
python manage.py makemigrations
python manage.py migrate
```

## Testing Inbox Delivery

Test inbox delivery by simulating a remote server POSTing an activity. Create a test script or management command:

```python
# journal/management/commands/test_inbox.py
from django.core.management.base import BaseCommand
from django.test import Client
from journal.models import UserProfile
import json

class Command(BaseCommand):
    help = 'Test inbox delivery'
    
    def add_arguments(self, parser):
        parser.add_argument('username', type=str)
    
    def handle(self, *args, **options):
        username = options['username']
        profile = UserProfile.objects.get(user__username=username)
        
        # Simulate a Like activity
        activity = {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": "https://remote.example/activities/test-like-001",
            "type": "Like",
            "actor": "https://remote.example/users/alice",
            "object": f"http://localhost:8000/entries/1",
            "published": "2025-01-15T12:00:00Z"
        }
        
        client = Client()
        response = client.post(
            f'/users/{username}/inbox',
            data=json.dumps(activity),
            content_type='application/activity+json'
        )
        
        self.stdout.write(f"Response: {response.status_code}")
        if response.status_code == 202:
            self.stdout.write(self.style.SUCCESS('Activity accepted'))
        else:
            self.stdout.write(self.style.ERROR(f'Error: {response.content}'))
```

Run the test:

```bash
python manage.py test_inbox your_username
```

Check that a `Like` record was created:

```python
python manage.py shell

from journal.models import Like
likes = Like.objects.all()
for like in likes:
    print(f"{like.actor_reference.uri} liked entry {like.entry.id}")
```

## Authentication and Authorization

Production inboxes must authenticate incoming requests. The toolkit handles HTTP signature verification automatically. When a POST arrives with a signature header, the view creates an `HttpSignatureProof` and attaches it to the notification.

The `process_incoming_notification` task calls `notification.authenticate()`, which:

1. Resolves the sender's actor to fetch their public key
2. Extracts the public key from the `SecV1Context`
3. Verifies the signature using the key
4. Creates a `NotificationProofVerification` if successful

Only authenticated notifications proceed to activity processing. Implement additional authorization in your handlers:

```python
def handle_create(activity):
    """Handle Create activities with authorization checks."""
    
    # Check if the actor is blocked
    actor_ref = activity.actor
    if actor_ref.domain and actor_ref.domain.blocked:
        logger.warning(f"Rejecting activity from blocked domain {actor_ref.domain}")
        return
    
    # Check if this is a reply
    obj_ref = activity.object
    if not obj_ref:
        return
    
    if not obj_ref.is_resolved:
        obj_ref.resolve()
    
    obj_ctx = obj_ref.get_by_context(ObjectContext)
    if obj_ctx and obj_ctx.in_reply_to:
        # Verify the reply is to a public entry
        try:
            entry = JournalEntry.objects.get(reference=obj_ctx.in_reply_to)
            # Add authorization logic here
            # e.g., check if replies are allowed, if actor is blocked, etc.
            handle_reply(obj_ctx)
        except JournalEntry.DoesNotExist:
            pass
```

## Handling Failures

Not all activities process successfully. The sender might reference nonexistent objects. Signatures might fail verification. Your application might reject activities based on policy.

The notification model tracks processing state. Handlers should handle errors gracefully:

```python
def handle_like(activity):
    """Handle Like activities with error handling."""
    from journal.models import JournalEntry, Like
    
    try:
        obj_ref = activity.object
        if not obj_ref:
            logger.warning(f"Like activity {activity.reference.uri} has no object")
            return
        
        entry = JournalEntry.objects.get(reference=obj_ref)
        
        Like.objects.get_or_create(
            entry=entry,
            actor_reference=activity.actor,
            defaults={'activity_reference': activity.reference}
        )
        
        logger.info(f"Processed like from {activity.actor.uri}")
        
    except JournalEntry.DoesNotExist:
        logger.info(f"Like for nonexistent entry {obj_ref.uri}")
    except Exception as e:
        logger.error(f"Error processing like: {e}", exc_info=True)
```

Failed activities remain in the database as notifications. You can inspect them, retry processing, or implement cleanup logic.

## Displaying Federated Interactions

Show replies, likes, and announces in your application. Update the journal entry detail view to include this data.

Create a template `journal/templates/journal/entry_detail.html`:

```django
{% raw %}
<div class="entry">
    <h2>{{ entry.as2.name }}</h2>
    <div class="content">{{ entry.as2.content }}</div>
    <div class="meta">
        Posted by {{ entry.user.username }} at {{ entry.as2.published }}
    </div>
    
    <div class="interactions">
        <h3>Likes ({{ entry.likes.count }})</h3>
        <ul>
        {% for like in entry.likes.all %}
            <li>{{ like.actor_reference.uri }}</li>
        {% endfor %}
        </ul>
        
        <h3>Shares ({{ entry.announces.count }})</h3>
        <ul>
        {% for announce in entry.announces.all %}
            <li>{{ announce.actor_reference.uri }} at {{ announce.published }}</li>
        {% endfor %}
        </ul>
        
        <h3>Replies ({{ entry.replies.count }})</h3>
        {% for reply in entry.replies.all %}
        <div class="reply">
            <div class="reply-author">{{ reply.author_reference.uri }}</div>
            <div class="reply-content">{{ reply.content }}</div>
            <div class="reply-time">{{ reply.published }}</div>
        </div>
        {% endfor %}
    </div>
</div>
{% endraw %}
```

Create a view:

```python
from django.views.generic import DetailView
from journal.models import JournalEntry

class EntryDetailHTMLView(DetailView):
    model = JournalEntry
    template_name = 'journal/entry_detail.html'
    context_object_name = 'entry'
```

Now your application displays interactions from across the Fediverse.

## Summary

You have implemented a complete inbox processing pipeline. Activities arrive via HTTP POST to inbox endpoints. The toolkit creates notifications, authenticates them, and parses the JSON-LD into context models. Your handlers connect to signals and update application state based on activity type.

This architecture separates protocol concerns from application logic. The toolkit handles ActivityPub mechanics. Your handlers implement business logic specific to your journal application. The same pattern applies to any ActivityPub application.

The next tutorial covers the outbound side: creating activities, managing collections, and delivering to remote inboxes.
