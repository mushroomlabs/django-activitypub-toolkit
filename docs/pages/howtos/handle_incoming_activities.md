# Handle Incoming Activities

This guide shows you how to process activities received from other Fediverse servers.

## Understanding Activity Delivery

When users on other servers interact with your content, their servers send activities to your inboxes. These activities describe actions like likes, follows, replies, and shares.

The toolkit automatically:
1. Receives HTTP POST requests to inbox endpoints
2. Verifies HTTP signatures for authentication
3. Parses JSON-LD activity documents
4. Stores activities in context models
5. Triggers processing signals

Your application implements handlers to respond to these activities.

## Set Up Inbox Endpoints

Create inbox views for your actors:

```python
from activitypub.views import ActivityPubObjectDetailView

class UserInboxView(ActivityPubObjectDetailView):
    """Handle inbox delivery for a user."""

    def get_object(self):
        username = self.kwargs['username']
        profile = get_object_or_404(UserProfile, user__username=username)
        return profile.actor.inbox
```

Add URL routing:

```python
urlpatterns = [
    path('users/<str:username>/inbox', UserInboxView.as_view(), name='user-inbox'),
]
```

## Implement Activity Handlers

Connect to the `activity_processed` signal to handle activities:

```python
from django.dispatch import receiver
from activitypub.signals import activity_processed
from activitypub.models import ActivityContext

@receiver(activity_processed)
def handle_activity(sender, activity, **kwargs):
    """Route activities to specific handlers."""
    activity_ctx = activity.get_by_context(ActivityContext)
    if not activity_ctx:
        return

    activity_type = activity_ctx.type

    handlers = {
        ActivityContext.Types.FOLLOW: handle_follow,
        ActivityContext.Types.LIKE: handle_like,
        ActivityContext.Types.CREATE: handle_create,
        ActivityContext.Types.ANNOUNCE: handle_announce,
    }

    handler = handlers.get(activity_type)
    if handler:
        handler(activity_ctx)
```

## Handle Follow Activities

Process follow requests:

```python
def handle_follow(activity):
    """Handle a follow request."""
    from yourapp.models import FollowRequest

    follower_ref = activity.actor
    followed_ref = activity.object

    # Check if this is a follow for our user
    try:
        profile = UserProfile.objects.get(actor_reference=followed_ref)
    except UserProfile.DoesNotExist:
        return  # Not following our user

    # Create follow request
    FollowRequest.objects.get_or_create(
        profile=profile,
        follower_reference=follower_ref,
        defaults={'activity_reference': activity.reference}
    )

    # Optionally auto-accept or notify user
    # send_notification(profile.user, f"{follower_ref.uri} wants to follow you")
```

## Handle Like Activities

Process likes on your content:

```python
def handle_like(activity):
    """Handle a like on our content."""
    from yourapp.models import Like, Post

    liked_ref = activity.object

    # Find the post that was liked
    try:
        post = Post.objects.get(reference=liked_ref)
    except Post.DoesNotExist:
        return  # Not our content

    # Record the like
    Like.objects.get_or_create(
        post=post,
        actor_reference=activity.actor,
        defaults={'activity_reference': activity.reference}
    )

    # Update like count or send notification
    # notify_post_author(post, f"Your post was liked by {activity.actor.uri}")
```

## Handle Create Activities

Process new content, especially replies:

```python
def handle_create(activity):
    """Handle creation of new content."""
    obj_ref = activity.object
    if not obj_ref:
        return

    # Resolve the object to get its data
    if not obj_ref.is_resolved:
        obj_ref.resolve()

    obj_ctx = obj_ref.get_by_context(ObjectContext)
    if not obj_ctx:
        return

    # Check if it's a reply to our content
    if obj_ctx.in_reply_to:
        handle_reply(obj_ctx, activity)
```

## Handle Reply Activities

Process replies to your content:

```python
def handle_reply(obj_ctx, activity):
    """Handle a reply to our content."""
    from yourapp.models import Reply, Post

    # Find the original post
    try:
        original_post = Post.objects.get(reference=obj_ctx.in_reply_to)
    except Post.DoesNotExist:
        return

    # Create reply record
    Reply.objects.get_or_create(
        post=original_post,
        reply_reference=obj_ctx.reference,
        defaults={
            'content': obj_ctx.content,
            'author_reference': activity.actor,
            'published': obj_ctx.published,
        }
    )
```

## Handle Announce Activities

Process shares/boosts of your content:

```python
def handle_announce(activity):
    """Handle sharing/boosting of our content."""
    from yourapp.models import Share, Post

    shared_ref = activity.object

    try:
        post = Post.objects.get(reference=shared_ref)
    except Post.DoesNotExist:
        return

    Share.objects.get_or_create(
        post=post,
        actor_reference=activity.actor,
        defaults={'activity_reference': activity.reference}
    )
```

## Accept Follow Requests

Create a method to accept follows:

```python
class FollowRequest(models.Model):
    # ... fields ...

    def accept(self):
        """Accept this follow request."""
        if self.accepted:
            return

        # Add follower to followers collection
        actor = self.profile.actor
        followers = actor.followers.get_by_context(CollectionContext)
        if followers:
            followers.append(self.follower_reference)

        # Send Accept activity
        accept_activity = create_accept_activity(self)

        self.accepted = True
        self.save()

        return accept_activity
```

## Error Handling

Handle processing errors gracefully:

```python
@receiver(activity_processed)
def handle_activity(sender, activity, **kwargs):
    try:
        # ... processing logic ...
    except Exception as e:
        logger.error(f"Error processing activity {activity.uri}: {e}")
        # Don't re-raise - prevents blocking other activities
```

## Testing Inbox Delivery

Test with curl:

```bash
curl -X POST http://localhost:8000/users/username/inbox \
  -H "Content-Type: application/activity+json" \
  -d '{
    "@context": "https://www.w3.org/ns/activitystreams",
    "id": "https://example.com/activities/1",
    "type": "Like",
    "actor": "https://example.com/users/alice",
    "object": "http://localhost:8000/posts/123"
  }'
```

## Security Considerations

- Always verify activity signatures before processing
- Validate that activities reference your content
- Implement rate limiting for inbox endpoints
- Handle malformed or malicious activities gracefully

## Next Steps

With incoming activities handled, you can:

- [Send activities](send_activities.md) to publish your content
- [Block spam](block_spam.md) from malicious servers
- Set up [WebFinger discovery](register_account.md#integration-with-webfinger) for user lookup
