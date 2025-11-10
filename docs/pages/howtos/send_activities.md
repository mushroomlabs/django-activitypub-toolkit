# Send Activities

This guide shows you how to publish activities from your application to the Fediverse.

## Understanding Activity Publishing

When your users create content or perform actions, you publish activities to make them visible to followers. Activities are added to outboxes where remote servers can discover them.

The toolkit supports both:

- **Pull-based publishing**: Activities in collections that remote servers fetch
- **Push-based delivery**: Direct delivery to follower inboxes (optional)

## Create Activities for New Content

When users create content, generate corresponding activities:

```python
from activitypub.models import ActivityContext, ObjectContext, Reference, Domain

class Post(models.Model):
    # ... fields ...

    @classmethod
    def create_post(cls, author, title, content):
        """Create a post with its federated activity."""
        domain = Domain.get_default()

        # Create post object
        post_ref = ObjectContext.generate_reference(domain)
        post_obj = ObjectContext.make(
            reference=post_ref,
            type=ObjectContext.Types.ARTICLE,
            name=title,
            content=content,
            published=timezone.now(),
            attributed_to=author.actor.reference,
        )

        # Create activity
        activity_ref = ActivityContext.generate_reference(domain)
        activity = ActivityContext.make(
            reference=activity_ref,
            type=ActivityContext.Types.CREATE,
            actor=author.actor.reference,
            object=post_ref,
            published=timezone.now(),
        )

        # Set addressing (public post)
        activity.to.add(Reference.make('https://www.w3.org/ns/activitystreams#Public'))
        if author.actor.followers:
            activity.cc.add(author.actor.followers)

        # Add to outbox
        outbox = author.actor.outbox.get_by_context(CollectionContext)
        if outbox:
            outbox.append(activity_ref)

        # Create Django model
        post = cls.objects.create(
            author=author,
            title=title,
            content=content,
            reference=post_ref
        )

        return post
```

## Publish Existing Content

For content created before federation, add activities:

```python
def publish_existing_post(post):
    """Add federation activities for existing post."""
    domain = Domain.get_default()

    # Create activity
    activity_ref = ActivityContext.generate_reference(domain)
    activity = ActivityContext.make(
        reference=activity_ref,
        type=ActivityContext.Types.CREATE,
        actor=post.author.actor.reference,
        object=post.reference,
        published=post.created_at,
    )

    # Add to outbox
    outbox = post.author.actor.outbox.get_by_context(CollectionContext)
    if outbox:
        outbox.append(activity_ref)

    return activity
```

## Handle User Actions

Create activities for user interactions:

```python
def like_post(user, post):
    """Like a post and send activity."""
    domain = Domain.get_default()

    # Create Like activity
    activity_ref = ActivityContext.generate_reference(domain)
    activity = ActivityContext.make(
        reference=activity_ref,
        type=ActivityContext.Types.LIKE,
        actor=user.actor.reference,
        object=post.reference,
        published=timezone.now(),
    )

    # Add to outbox
    outbox = user.actor.outbox.get_by_context(CollectionContext)
    if outbox:
        outbox.append(activity_ref)

    # Record like locally
    Like.objects.create(user=user, post=post, activity_ref=activity_ref)

    return activity
```

## Manage Collections

Collections organize activities and relationships:

```python
# Add to followers collection
def add_follower(actor, follower_ref):
    """Add a follower to an actor's followers collection."""
    followers = actor.followers.get_by_context(CollectionContext)
    if followers:
        followers.append(follower_ref)

# Remove from following collection
def unfollow(actor, unfollowed_ref):
    """Remove from following collection."""
    following = actor.following.get_by_context(CollectionContext)
    if following:
        following.remove(unfollowed_ref)
```

## Activity Addressing

Control who sees activities with addressing fields:

```python
# Public activity (visible to all)
activity.to.add(Reference.make('https://www.w3.org/ns/activitystreams#Public'))

# Followers-only activity
activity.to.add(actor.followers)

# Direct message (specific recipients)
activity.to.add(specific_actor_ref)

# Courtesy copy (not primary recipients)
activity.cc.add(other_actor_ref)
```

## Serve Outbox Collections

Make outboxes accessible to remote servers:

```python
from activitypub.views import LinkedDataModelView

class UserOutboxView(LinkedDataModelView):
    """Serve a user's outbox collection."""

    def get_object(self):
        username = self.kwargs['username']
        profile = get_object_or_404(UserProfile, user__username=username)
        return profile.actor.outbox
```

Add to URLs:

```python
urlpatterns = [
    path('users/<str:username>/outbox', UserOutboxView.as_view(), name='user-outbox'),
]
```

## Push Delivery (Optional)

For real-time delivery, send activities directly to inboxes:

```python
def deliver_activity(activity, recipients):
    """Deliver activity to recipient inboxes."""
    from activitypub.tasks import deliver_activity_to_inbox

    for recipient_ref in recipients:
        # Resolve recipient to get inbox URL
        if not recipient_ref.is_resolved:
            recipient_ref.resolve()

        recipient_actor = recipient_ref.get_by_context(ActorContext)
        if recipient_actor and recipient_actor.inbox:
            # Queue delivery task
            deliver_activity_to_inbox.delay(
                activity.reference.uri,
                recipient_actor.inbox.uri
            )
```

## Testing Activity Publishing

Test that activities are published correctly:

```bash
# Create a post
python manage.py shell
from yourapp.models import Post
post = Post.create_post(user, "Test Post", "Content")

# Check outbox
outbox = user.actor.outbox.get_by_context(CollectionContext)
activities = outbox.items.all()
print(f"Activities in outbox: {len(activities)}")

# Fetch outbox via HTTP
curl -H "Accept: application/activity+json" \
     http://localhost:8000/users/username/outbox
```

## Activity Types

Common activity types to implement:

- `Create`: Publishing new content
- `Update`: Modifying existing content
- `Delete`: Removing content
- `Follow`: Following users
- `Accept`: Accepting follow requests
- `Like`: Liking content
- `Announce`: Sharing/boosting content
- `Undo`: Reversing actions

## Error Handling

Handle delivery failures gracefully:

```python
def deliver_activity(activity, recipient_inbox):
    try:
        # Attempt delivery
        response = requests.post(
            recipient_inbox,
            json=activity_data,
            headers={'Content-Type': 'application/activity+json'},
            # Include HTTP signatures
        )

        if response.status_code not in [200, 201, 202]:
            logger.warning(f"Delivery failed: {response.status_code}")
            # Queue retry or mark as failed

    except Exception as e:
        logger.error(f"Delivery error: {e}")
        # Handle network errors, timeouts, etc.
```

## Performance Considerations

- Use background tasks for delivery
- Cache resolved actor information
- Batch deliveries when possible
- Implement retry logic with exponential backoff

## Next Steps

With activity publishing working, you can:

- [Handle incoming activities](handle_incoming_activities.md) from other servers
- Set up [WebFinger discovery](register_account.md#integration-with-webfinger) for user lookup
- Implement [moderation features](block_spam.md) for content control
