# Handle Incoming Activities

This guide shows you how to process activities received from other Fediverse servers using custom handlers.

## Understanding Activity Delivery

When users on other servers interact with your content, their servers send activities to your inboxes. The toolkit automatically handles the complete delivery pipeline:

1. Receives HTTP POST requests to inbox endpoints (via the catch-all `ActivityPubObjectDetailView`)
2. Verifies HTTP signatures for authentication
3. Parses JSON-LD activity documents
4. Stores activities in context models
5. Processes standard ActivityPub flows (Follow, Like, Announce, etc.)
6. Triggers processing signals

**For standard ActivityPub activities, the toolkit handles everything automatically.** You only need custom handlers for application-specific logic beyond the standard protocol behavior.

## When to Write Custom Handlers

You only need custom handlers when:

- **Sending user notifications** - Email or push notifications when someone follows or mentions a user
- **Moderation workflows** - Alert moderators when Flag activities arrive
- **Application-specific state** - Update non-ActivityPub models in your application
- **Custom validation** - Implement business rules beyond standard ActivityPub semantics
- **Integration hooks** - Trigger external services or webhooks

If you just need to track likes, follows, and shares, **you don't need custom handlers**. The toolkit maintains collections automatically.

## Automatic Processing

The toolkit automatically handles these standard activities:

- **Follow** - Creates `FollowRequest` records, adds to following/followers collections when accepted
- **Like** - Adds to the object's `likes` collection and actor's `liked` collection
- **Announce** - Adds to the object's `shares` collection
- **Add/Remove** - Manages collection membership
- **Undo** - Reverses previous activities (unfollows, unlikes, etc.)

These work out of the box without any custom code.

## Implement Custom Handlers

Connect to Django signals to add application-specific logic:

```python
from django.dispatch import receiver
from activitypub.signals import activity_done, notification_accepted
from activitypub.models import Activity, ActivityContext

@receiver(activity_done)
def handle_activity(sender, activity, **kwargs):
    """Add custom logic after standard processing completes."""
    
    # activity_done fires after the toolkit has updated collections
    # This is where you add application-specific behavior
    
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
        import yourapp.handlers  # noqa
```

## Send User Notifications

Notify users when they receive interactions:

```python
from django.core.mail import send_mail
from yourapp.models import Post, UserProfile

def handle_like_notification(activity):
    """Send notification when content is liked."""
    try:
        # Check if the liked object is one of our posts
        post = Post.objects.get(reference=activity.object)
        
        # Send notification to the post's author
        send_mail(
            subject=f'Your post was liked',
            message=f'{activity.actor.uri} liked your post: {post.title}',
            from_email='noreply@example.com',
            recipient_list=[post.author.email],
        )
        
    except Post.DoesNotExist:
        # Not one of our posts, nothing to do
        pass

def handle_follow_notification(activity):
    """Notify user when someone follows them."""
    try:
        # Check if the followed actor is one of our users
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
from yourapp.models import Post
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

def handle_moderation_flag(activity):
    """Alert moderators when content is flagged."""
    try:
        # Get the flagged object
        flagged_ref = activity.object
        post = Post.objects.get(reference=flagged_ref)
        
        # Get the flagger
        flagger_uri = activity.actor.uri
        
        # Send email to moderators
        send_mail(
            subject=f'Content flagged: {post.title}',
            message=f'User {flagger_uri} flagged post {post.id}\n\n{activity.content}',
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
from yourapp.models import Post, Like

def handle_like_notification(activity):
    """Update application state when content is liked."""
    try:
        post = Post.objects.get(reference=activity.object)
        
        # Create application-specific Like record
        Like.objects.get_or_create(
            post=post,
            actor_uri=activity.actor.uri,
            defaults={
                'activity_reference': activity.reference,
                'created_at': activity.published,
            }
        )
        
        # Update denormalized like count
        post.like_count = Like.objects.filter(post=post).count()
        post.save()
        
    except Post.DoesNotExist:
        pass
```

## Custom Authorization

Enforce application-specific policies before standard processing:

```python
from activitypub.signals import notification_accepted
from yourapp.models import BlockedUser
from activitypub.models import ActivityContext
from activitypub.exceptions import DropMessage

@receiver(notification_accepted)
def enforce_interaction_policy(sender, notification, **kwargs):
    """Enforce custom policies before standard processing."""
    activity_ref = notification.resource
    activity = activity_ref.get_by_context(ActivityContext)
    
    # Check if the actor is blocked
    if activity.actor and BlockedUser.objects.filter(actor_uri=activity.actor.uri).exists():
        logger.info(f"Rejecting activity from blocked user {activity.actor.uri}")
        
        # Prevent further processing
        raise DropMessage("Actor is blocked")
```

The `notification_accepted` signal fires before standard activity processing, allowing you to reject activities early.

## Auto-Accept Follow Requests

Automatically accept follow requests instead of requiring manual approval:

```python
from activitypub.models import FollowRequest

@receiver(activity_done)
def auto_accept_follows(sender, activity, **kwargs):
    """Automatically accept follow requests."""
    
    if activity.type != Activity.Types.FOLLOW:
        return
    
    try:
        request = FollowRequest.objects.get(activity=activity)
        if request.status == FollowRequest.STATUS.pending:
            request.accept()
    except FollowRequest.DoesNotExist:
        pass
```

The `FollowRequest.accept()` method handles adding the follower to the followers collection and sending the Accept activity.

## Track Activity Statistics

Maintain statistics about federated interactions:

```python
from yourapp.models import ActivityStats

@receiver(activity_done)
def update_activity_stats(sender, activity, **kwargs):
    """Track activity statistics."""
    
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
@receiver(activity_done)
def safe_handler(sender, activity, **kwargs):
    """Handle activities with proper error handling."""
    
    try:
        # Your handler logic here
        process_activity(activity)
    except Exception as e:
        logger.error(
            f"Error processing activity {activity.reference.uri}: {e}",
            exc_info=True
        )
        # Don't re-raise - let other handlers continue
```

## Testing Custom Handlers

Test your handlers by simulating incoming activities:

```python
from django.test import TestCase
from activitypub.models import ActivityContext, Reference, Domain

class ActivityHandlerTest(TestCase):
    def test_like_notification(self):
        """Test that like activities trigger notifications."""
        
        # Create test activity
        domain = Domain.get_default()
        activity_ref = ActivityContext.generate_reference(domain)
        
        activity = ActivityContext.make(
            reference=activity_ref,
            type=ActivityContext.Types.LIKE,
            actor=Reference.make('https://example.com/users/alice'),
            object=self.post.reference,
        )
        
        # Trigger signal
        activity_done.send(sender=ActivityContext, activity=activity)
        
        # Assert notification was sent
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('liked', mail.outbox[0].subject)
```

## What You DON'T Need to Do

The toolkit handles these automatically - **you don't need custom handlers for**:

- Adding likes to the `likes` collection
- Adding shares to the `shares` collection
- Adding followers to the `followers` collection
- Creating `FollowRequest` records
- Processing Undo activities (unfollows, unlikes)
- Managing collection membership (Add/Remove activities)
- Adding activities to inbox collections

These all work out of the box through the toolkit's built-in handlers.

## Next Steps

With custom activity handlers implemented, you can:

- [Send activities](send_activities.md) to publish your content
- [Block spam](block_spam.md) from malicious servers
- Review the [integration tutorial](../tutorials/integration_with_existing_project.md#webfinger-discovery) for WebFinger discovery setup
