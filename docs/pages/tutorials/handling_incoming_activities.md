---
title: Handling Incoming Activities
---

This tutorial teaches you how to receive and process ActivityPub activities delivered to your server. You will learn to configure a catch-all URL pattern that handles any local object reference, understand what happens automatically when activities arrive, and implement optional custom handlers for application-specific logic.

By the end of this tutorial, you will understand how the toolkit's built-in machinery processes standard ActivityPub flows automatically, and when you need to add custom handlers for your application's specific needs.

## Understanding ActivityPub Delivery

ActivityPub uses push-based delivery through inboxes. When a user on a remote server performs an action—following you, liking your post, replying to your content—that server POSTs an activity to your inbox. The activity is a JSON-LD document describing what happened.

The toolkit handles the complete delivery pipeline. Your server receives the POST request, authenticates it using HTTP signatures, stores the activity document, creates a notification, and processes it asynchronously. For standard ActivityPub activities like Follow, Like, and Announce, the toolkit automatically updates the appropriate collections without requiring any custom code.

## The Catch-All URL Pattern

The toolkit provides `ActivityPubObjectDetailView`, which serves as a universal handler for any local object reference. This view handles both GET and POST requests automatically.

For GET requests, the view returns the JSON-LD representation of the requested object. For POST requests, the view checks whether the target is an inbox or outbox, then processes the activity accordingly.

Configure your URL patterns to use this view as a catch-all. In your project's `urls.py`:

```python
from django.urls import path
from activitypub.views import ActivityPubObjectDetailView

urlpatterns = [
    # Your other URL patterns here
    path('<path:resource>', ActivityPubObjectDetailView.as_view(), name='activitypub-resource'),
]
```

The view uses the request's absolute URI to look up the corresponding `Reference` object in your database. When a POST arrives at any local reference that represents an inbox or outbox, the view automatically handles it.

## What Happens Automatically

When an activity is POSTed to an inbox, the view performs these steps without requiring any custom code:

1. **Domain blocking check** - Rejects activities from blocked domains immediately
2. **Notification creation** - Creates a `Notification` linking the sender, target inbox, and activity
3. **Signature capture** - If the request includes an HTTP signature, creates an `HttpSignatureProof`
4. **Document storage** - Stores the JSON-LD document as a `LinkedDataDocument`
5. **Asynchronous processing** - Queues the `process_incoming_notification` task

The processing task then:

1. **Loads the document** - Parses the JSON-LD into RDF and populates context models
2. **Resolves the sender** - Fetches the sender's actor document if needed
3. **Emits notification_accepted signal** - Triggers the standard activity flow processor
4. **Adds to inbox collection** - Appends the activity to the inbox collection

For standard ActivityPub activities, the toolkit's built-in handlers automatically manage collections. When a Like activity arrives for a local object, the toolkit adds it to both the object's `likes` collection and the actor's `liked` collection. When an Announce activity arrives, it goes into the object's `shares` collection. Follow activities create `FollowRequest` records that are automatically accepted if the target actor doesn't require manual approval.

You do not need to write handlers for these standard flows. The machinery is already in place.

## Setting Up Actors and Inboxes

Before you can receive activities, you need actors with inboxes. Create a model that links your application's users to ActivityPub actors.

In your application's `models.py`:

```python
from django.db import models
from django.contrib.auth.models import User
from activitypub.models import Reference, ActorContext, CollectionContext, Domain

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    actor_reference = models.OneToOneField(
        Reference,
        on_delete=models.CASCADE,
        related_name='user_profile'
    )
    
    @classmethod
    def create_for_user(cls, user):
        domain = Domain.get_default()
        actor_ref = ActorContext.generate_reference(domain)
        
        actor = ActorContext.make(
            reference=actor_ref,
            type=ActorContext.Types.PERSON,
            preferred_username=user.username,
            name=user.get_full_name() or user.username,
        )
        
        inbox_ref = CollectionContext.generate_reference(domain)
        inbox = CollectionContext.make(
            reference=inbox_ref,
            type=CollectionContext.Types.ORDERED_COLLECTION,
        )
        actor.inbox = inbox_ref
        actor.save()
        
        outbox_ref = CollectionContext.generate_reference(domain)
        outbox = CollectionContext.make(
            reference=outbox_ref,
            type=CollectionContext.Types.ORDERED_COLLECTION,
        )
        actor.outbox = outbox_ref
        actor.save()
        
        profile = cls.objects.create(
            user=user,
            actor_reference=actor_ref
        )
        
        return profile
    
    @property
    def actor(self):
        return self.actor_reference.get_by_context(ActorContext)
```

Run migrations to create the model:

```bash
python manage.py makemigrations
python manage.py migrate
```

Create profiles for your users with a management command or in your user registration flow:

```python
from django.contrib.auth.models import User
from myapp.models import UserProfile

for user in User.objects.filter(profile__isnull=True):
    UserProfile.create_for_user(user)
```

The catch-all URL pattern now handles GET requests to any actor, inbox, or outbox URI automatically. POST requests to inbox URIs trigger the automatic processing pipeline.

## Testing Inbox Delivery

Test that your inbox receives and processes activities. Create a test script that simulates a remote server POSTing a Like activity:

```python
from django.test import Client
from myapp.models import UserProfile
import json

profile = UserProfile.objects.first()
actor = profile.actor

activity = {
    "@context": "https://www.w3.org/ns/activitystreams",
    "id": "https://remote.example/activities/test-like-001",
    "type": "Like",
    "actor": "https://remote.example/users/alice",
    "object": "http://localhost:8000/objects/some-local-object",
    "published": "2025-11-25T12:00:00Z"
}

client = Client()
response = client.post(
    actor.inbox.uri,
    data=json.dumps(activity),
    content_type='application/activity+json'
)

print(f"Response: {response.status_code}")
```

A 202 Accepted response indicates the activity was queued for processing. Check that the activity was added to the inbox collection:

```python
from activitypub.models import CollectionContext

inbox = actor.inbox.get_by_context(CollectionContext)
print(f"Inbox has {inbox.total_items} items")
```

For a Like activity targeting a local object, the toolkit automatically adds the activity to the object's `likes` collection and the actor's `liked` collection. For a Follow activity, it creates a `FollowRequest` record. For an Announce activity, it adds the activity to the object's `shares` collection.

## When to Write Custom Handlers

The toolkit handles standard ActivityPub flows automatically. You only need custom handlers when your application requires logic beyond the standard protocol behavior.

Common reasons to write custom handlers:

- **User notifications** - Send an email or push notification when someone follows or mentions a user
- **Moderation workflows** - Alert moderators when a Flag activity arrives
- **Application-specific state** - Update non-ActivityPub models in your application
- **Custom validation** - Implement business rules beyond standard ActivityPub semantics
- **Integration hooks** - Trigger external services or webhooks

If your application simply needs to track likes, follows, and shares, you do not need custom handlers. The collections are already maintained automatically.

## Implementing Custom Handlers

Custom handlers connect to Django signals. The toolkit emits signals at key points in the processing pipeline.

The `notification_accepted` signal fires after a notification has been authenticated and loaded. The `activity_done` signal fires after the standard activity flows have completed. Connect to these signals to add your application-specific logic.

Create a handlers module in your application:

```python
import logging
from django.dispatch import receiver
from activitypub.signals import activity_done
from activitypub.models import ActivityContext

logger = logging.getLogger(__name__)

@receiver(activity_done)
def notify_user_of_interaction(sender, activity, **kwargs):
    """Send notification to user when they receive an interaction."""
    
    if activity.type == ActivityContext.Types.LIKE:
        handle_like_notification(activity)
    elif activity.type == ActivityContext.Types.FOLLOW:
        handle_follow_notification(activity)

def handle_like_notification(activity):
    """Notify a user that their content was liked."""
    from myapp.models import JournalEntry
    
    try:
        # Check if the liked object is one of our entries
        entry = JournalEntry.objects.get(reference=activity.object)
        
        # Send notification to the entry's author
        logger.info(f"Sending like notification to {entry.user.email}")
        # Your notification logic here - email, push notification, etc.
        
    except JournalEntry.DoesNotExist:
        # Not one of our entries, nothing to do
        pass

def handle_follow_notification(activity):
    """Notify a user that someone followed them."""
    from myapp.models import UserProfile
    
    try:
        # Check if the followed actor is one of our users
        profile = UserProfile.objects.get(actor_reference=activity.object)
        
        logger.info(f"Sending follow notification to {profile.user.email}")
        # Your notification logic here
        
    except UserProfile.DoesNotExist:
        pass
```

Register your handlers in your app's `apps.py`:

```python
from django.apps import AppConfig

class MyAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'myapp'
    
    def ready(self):
        import myapp.handlers  # noqa
```

This handler runs after the toolkit has already updated the collections. Your code adds application-specific behavior on top of the standard protocol handling.

## Custom Handler for Moderation

Another common use case is handling Flag activities for content moderation. The toolkit doesn't have built-in moderation workflows, so you implement your own:

```python
@receiver(activity_done)
def handle_moderation_flags(sender, activity, **kwargs):
    """Alert moderators when content is flagged."""
    
    if activity.type != ActivityContext.Types.FLAG:
        return
    
    from django.core.mail import send_mail
    from myapp.models import JournalEntry
    
    try:
        # Get the flagged object
        flagged_ref = activity.object
        entry = JournalEntry.objects.get(reference=flagged_ref)
        
        # Get the flagger
        flagger_uri = activity.actor.uri
        
        # Send email to moderators
        send_mail(
            subject=f'Content flagged: {entry.title}',
            message=f'User {flagger_uri} flagged entry {entry.id}',
            from_email='noreply@example.com',
            recipient_list=['moderators@example.com'],
        )
        
        logger.info(f"Sent moderation alert for entry {entry.id}")
        
    except JournalEntry.DoesNotExist:
        logger.warning(f"Flag activity for unknown object {flagged_ref.uri}")
```

## Authentication and Authorization

The toolkit handles HTTP signature verification automatically. When a POST arrives with a signature header, the view creates an `HttpSignatureProof` attached to the notification. The processing task verifies the signature using the sender's public key fetched from their actor document.

Only authenticated notifications proceed to activity processing. The domain blocking check happens before authentication, rejecting activities from blocked domains immediately.

Implement additional authorization in your handlers if needed. For example, you might want to enforce custom policies on which users can interact with your content:

```python
@receiver(notification_accepted)
def enforce_interaction_policy(sender, notification, **kwargs):
    """Enforce custom policies before standard processing."""
    
    from myapp.models import BlockedUser
    from activitypub.models import ActivityContext
    
    activity_ref = notification.resource
    activity = activity_ref.get_by_context(ActivityContext)
    
    # Check if the actor is blocked
    if activity.actor and BlockedUser.objects.filter(actor_reference=activity.actor).exists():
        logger.info(f"Rejecting activity from blocked user {activity.actor.uri}")
        # Mark notification as rejected
        from activitypub.models import NotificationProcessResult
        NotificationProcessResult.objects.create(
            notification=notification,
            type=NotificationProcessResult.Types.FORBIDDEN,
            message="Actor is blocked"
        )
        # Prevent further processing
        raise Exception("Actor is blocked")
```

This handler runs before the standard activity flows, allowing you to reject activities from blocked users before they are added to any collections.

## Displaying Federated Interactions

The toolkit maintains collections automatically, so displaying interactions is straightforward. Query the collections to show likes, shares, and replies. When a Create activity arrives with an object that has `in_reply_to` set, the toolkit automatically adds it to the parent object's `replies` collection through the signal handler in `activitypub/handlers.py`. You simply query the collection to display the replies.

```python
from django.views.generic import DetailView
from myapp.models import JournalEntry
from activitypub.models import CollectionContext, ObjectContext

class EntryDetailView(DetailView):
    model = JournalEntry
    template_name = 'myapp/entry_detail.html'
    context_object_name = 'entry'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        entry = self.object
        
        # Get the ActivityPub object context
        obj = entry.reference.get_by_context(ObjectContext)
        
        # Get likes
        if obj.likes:
            likes_collection = obj.likes.get_by_context(CollectionContext)
            context['likes_count'] = likes_collection.total_items
        
        # Get shares
        if obj.shares:
            shares_collection = obj.shares.get_by_context(CollectionContext)
            context['shares_count'] = shares_collection.total_items
        
        # Get replies - automatically populated by the toolkit
        if obj.replies:
            replies_collection = obj.replies.get_by_context(CollectionContext)
            context['replies_count'] = replies_collection.total_items
            # You can also iterate through the replies
            context['replies'] = [
                item.get_by_context(ObjectContext) 
                for item in replies_collection.items.all()
            ]
        
        return context
```

In your template:

```django
{% raw %}
<div class="entry">
    <h2>{{ entry.title }}</h2>
    <div class="content">{{ entry.content }}</div>
    
    <div class="interactions">
        <span>{{ likes_count }} likes</span>
        <span>{{ shares_count }} shares</span>
        <span>{{ replies_count }} replies</span>
    </div>
</div>
{% endraw %}
```

## Error Handling

Not all activities process successfully. Remote servers might send malformed documents, reference nonexistent objects, or fail signature verification. The toolkit handles these errors gracefully.

Failed signature verification prevents the notification from being accepted, so the activity never reaches your handlers. Malformed JSON-LD creates a notification result with type `BAD_REQUEST`. Activities from blocked domains are rejected with `FORBIDDEN`.

Your custom handlers should handle errors gracefully:

```python
@receiver(activity_done)
def safe_notification_handler(sender, activity, **kwargs):
    """Handle activities with proper error handling."""
    
    try:
        # Your handler logic here
        pass
    except Exception as e:
        logger.error(f"Error processing activity {activity.reference.uri}: {e}", exc_info=True)
        # Don't raise - let other handlers continue
```

Failed notifications remain in the database with their error status recorded in `NotificationProcessResult`. You can inspect them for debugging or implement retry logic if appropriate.

## Summary

You have learned how the toolkit handles incoming ActivityPub activities automatically. The `ActivityPubObjectDetailView` serves as a catch-all handler for any local object reference. When activities arrive at inboxes, the toolkit creates notifications, verifies signatures, and processes standard ActivityPub flows without requiring custom code.

Standard activities like Follow, Like, and Announce update collections automatically. You only write custom handlers when your application needs logic beyond the standard protocol behavior—sending user notifications, implementing moderation workflows, or integrating with application-specific models.

This architecture separates protocol mechanics from application logic. The toolkit handles ActivityPub semantics. Your handlers implement business logic specific to your application.

The next tutorial covers the outbound side: creating activities, publishing content to the Fediverse, and managing outbox delivery.
