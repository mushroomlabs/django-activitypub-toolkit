# Send Activities

This guide shows you how to publish activities from your application to the Fediverse by creating activities and delivering them to follower inboxes.

## Understanding Activity Publishing

Publishing to the Fediverse means creating activities and delivering them to remote inboxes. When your users create content, you:

1. Create an ObjectContext for the content
2. Create an ActivityContext that wraps the object
3. Add addressing (who should receive it)
4. Add to the actor's outbox
5. Deliver to follower inboxes using Notifications

The toolkit handles HTTP delivery automatically through the `send_notification` task.

## Create Activities for New Content

When users create content, generate corresponding activities:

```python
from activitypub.models import (
    ActivityContext,
    ObjectContext,
    CollectionContext,
    Notification,
    Reference,
    Domain,
    Actor,
)
from activitypub.tasks import send_notification
from activitypub.schemas import AS2
from django.utils import timezone

class Post(models.Model):
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    content = models.TextField()
    reference = models.OneToOneField(Reference, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def create_post(cls, author, title, content, public=True):
        """Create a post and publish to followers."""
        domain = Domain.get_default()
        
        # Create post object
        post_ref = ObjectContext.generate_reference(domain)
        post_obj = ObjectContext.make(
            reference=post_ref,
            type=ObjectContext.Types.ARTICLE,
            name=title,
            content=content,
            published=timezone.now(),
            attributed_to=author.profile.actor_reference,
        )
        
        # Create Django model
        post = cls.objects.create(
            author=author,
            title=title,
            content=content,
            reference=post_ref
        )
        
        # Create activity
        activity_ref = ActivityContext.generate_reference(domain)
        activity = ActivityContext.make(
            reference=activity_ref,
            type=ActivityContext.Types.CREATE,
            actor=author.profile.actor_reference,
            object=post_ref,
            published=timezone.now(),
        )
        
        # Set addressing
        actor = author.profile.actor_reference.get_by_context(Actor)
        if public:
            # Public post: to=Public, cc=followers
            activity.to.add(Reference.make(str(AS2.Public)))
            if actor and actor.followers:
                activity.cc.add(actor.followers)
        else:
            # Followers-only: to=followers
            if actor and actor.followers:
                activity.to.add(actor.followers)
        
        activity.save()
        
        # Add to outbox
        if actor and actor.outbox:
            outbox = actor.outbox.get_by_context(CollectionContext)
            if outbox:
                outbox.append(activity_ref)
        
        # Deliver to followers
        if actor:
            for inbox_ref in actor.followers_inboxes:
                notification = Notification.objects.create(
                    resource=activity_ref,
                    sender=author.profile.actor_reference,
                    target=inbox_ref,
                )
                send_notification.delay(notification_id=str(notification.id))
        
        return post
```

## Update Existing Content

When content changes, send Update activities:

```python
def update_post(self, title=None, content=None):
    """Update the post and send Update activity to followers."""
    
    # Update the object
    obj = self.reference.get_by_context(ObjectContext)
    if title is not None:
        obj.name = title
        self.title = title
    if content is not None:
        obj.content = content
        self.content = content
    obj.updated = timezone.now()
    obj.save()
    self.save()
    
    # Create Update activity
    domain = Domain.get_default()
    activity_ref = ActivityContext.generate_reference(domain)
    actor_ref = self.author.profile.actor_reference
    
    activity = ActivityContext.make(
        reference=activity_ref,
        type=ActivityContext.Types.UPDATE,
        actor=actor_ref,
        object=self.reference,
        published=timezone.now(),
    )
    
    # Set addressing
    actor = actor_ref.get_by_context(Actor)
    activity.to.add(Reference.make(str(AS2.Public)))
    if actor and actor.followers:
        activity.cc.add(actor.followers)
    activity.save()
    
    # Add to outbox
    if actor and actor.outbox:
        outbox = actor.outbox.get_by_context(CollectionContext)
        if outbox:
            outbox.append(activity_ref)
    
    # Deliver to followers
    if actor:
        for inbox_ref in actor.followers_inboxes:
            notification = Notification.objects.create(
                resource=activity_ref,
                sender=actor_ref,
                target=inbox_ref,
            )
            send_notification.delay(notification_id=str(notification.id))
```

## Delete Content

When content is deleted, send Delete activities:

```python
def delete_post(self):
    """Delete the post and send Delete activity to followers."""
    
    # Create Delete activity before deleting the object
    domain = Domain.get_default()
    activity_ref = ActivityContext.generate_reference(domain)
    actor_ref = self.author.profile.actor_reference
    
    activity = ActivityContext.make(
        reference=activity_ref,
        type=ActivityContext.Types.DELETE,
        actor=actor_ref,
        object=self.reference,
        published=timezone.now(),
    )
    
    # Set addressing
    actor = actor_ref.get_by_context(Actor)
    activity.to.add(Reference.make(str(AS2.Public)))
    if actor and actor.followers:
        activity.cc.add(actor.followers)
    activity.save()
    
    # Add to outbox
    if actor and actor.outbox:
        outbox = actor.outbox.get_by_context(CollectionContext)
        if outbox:
            outbox.append(activity_ref)
    
    # Deliver to followers
    if actor:
        for inbox_ref in actor.followers_inboxes:
            notification = Notification.objects.create(
                resource=activity_ref,
                sender=actor_ref,
                target=inbox_ref,
            )
            send_notification.delay(notification_id=str(notification.id))
    
    # Delete the post and object
    self.reference.delete()
    self.delete()
```

## Handle User Actions

Create activities for user interactions like likes:

```python
def like_post(user, post):
    """Like a post and send activity to the post author's inbox."""
    from activitypub.models import ActorContext
    
    domain = Domain.get_default()
    
    # Create Like activity
    activity_ref = ActivityContext.generate_reference(domain)
    activity = ActivityContext.make(
        reference=activity_ref,
        type=ActivityContext.Types.LIKE,
        actor=user.profile.actor_reference,
        object=post.reference,
        published=timezone.now(),
    )
    
    # Address to the post author and public
    activity.to.add(post.author.profile.actor_reference)
    activity.cc.add(Reference.make(str(AS2.Public)))
    activity.save()
    
    # Add to user's outbox
    actor = user.profile.actor_reference.get_by_context(Actor)
    if actor and actor.outbox:
        outbox = actor.outbox.get_by_context(CollectionContext)
        if outbox:
            outbox.append(activity_ref)
    
    # Deliver to post author's inbox
    post_author_actor = post.author.profile.actor_reference.get_by_context(ActorContext)
    if post_author_actor and post_author_actor.inbox:
        notification = Notification.objects.create(
            resource=activity_ref,
            sender=user.profile.actor_reference,
            target=post_author_actor.inbox,
        )
        send_notification.delay(notification_id=str(notification.id))
    
    # Record like locally
    from yourapp.models import Like
    Like.objects.create(
        user=user,
        post=post,
        activity_reference=activity_ref
    )
    
    return activity
```

## Follow Remote Users

Send Follow activities to remote actors:

```python
def follow_user(follower, followed_actor_uri):
    """Follow a remote user."""
    from activitypub.models import ActorContext
    
    domain = Domain.get_default()
    
    # Get or create reference to followed actor
    followed_ref = Reference.make(followed_actor_uri)
    if not followed_ref.is_resolved:
        followed_ref.resolve()
    
    # Create Follow activity
    activity_ref = ActivityContext.generate_reference(domain)
    activity = ActivityContext.make(
        reference=activity_ref,
        type=ActivityContext.Types.FOLLOW,
        actor=follower.profile.actor_reference,
        object=followed_ref,
        published=timezone.now(),
    )
    
    # Address to the followed actor
    activity.to.add(followed_ref)
    activity.save()
    
    # Add to follower's outbox
    actor = follower.profile.actor_reference.get_by_context(Actor)
    if actor and actor.outbox:
        outbox = actor.outbox.get_by_context(CollectionContext)
        if outbox:
            outbox.append(activity_ref)
    
    # Deliver to followed actor's inbox
    followed_actor = followed_ref.get_by_context(ActorContext)
    if followed_actor and followed_actor.inbox:
        notification = Notification.objects.create(
            resource=activity_ref,
            sender=follower.profile.actor_reference,
            target=followed_actor.inbox,
        )
        send_notification.delay(notification_id=str(notification.id))
    
    return activity
```

## Activity Addressing

Control who sees activities with addressing fields:

```python
from activitypub.schemas import AS2

# Public activity (visible to all)
activity.to.add(Reference.make(str(AS2.Public)))
if actor.followers:
    activity.cc.add(actor.followers)

# Followers-only activity
if actor.followers:
    activity.to.add(actor.followers)

# Direct message (specific recipients)
activity.to.add(specific_actor_ref)

# Courtesy copy (not primary recipients)
activity.cc.add(other_actor_ref)

# Save after setting addressing
activity.save()
```

## Understanding Delivery

The delivery workflow uses the Notification system:

1. **Create Notification** - Links the activity, sender, and target inbox
2. **Queue Task** - `send_notification.delay()` queues async delivery
3. **Serialize Activity** - Task converts activity to JSON-LD
4. **Sign Request** - Task creates HTTP signature using sender's keypair
5. **POST to Inbox** - Task sends signed request to remote inbox
6. **Record Result** - Task creates `NotificationProcessResult` with status

The `actor.followers_inboxes` property returns inbox References for all followers, preferring shared inboxes when available.

## Testing Activity Publishing

Test that activities are published correctly:

```python
from django.test import TestCase
from yourapp.models import Post

class PublishingTest(TestCase):
    def test_create_post_publishes_activity(self):
        """Test that creating a post publishes a Create activity."""
        
        # Create post
        post = Post.create_post(
            author=self.user,
            title="Test Post",
            content="Test content",
            public=True
        )
        
        # Check activity was created
        actor = self.user.profile.actor_reference.get_by_context(Actor)
        outbox = actor.outbox.get_by_context(CollectionContext)
        
        activities = outbox.items.all()
        self.assertEqual(len(activities), 1)
        
        activity = activities[0].item.get_by_context(ActivityContext)
        self.assertEqual(activity.type, ActivityContext.Types.CREATE)
        self.assertEqual(activity.object, post.reference)
        
        # Check notifications were created
        from activitypub.models import Notification
        notifications = Notification.objects.filter(resource=activity.reference)
        self.assertEqual(notifications.count(), len(actor.followers_inboxes))
```

Test via HTTP:

```bash
# Create a post
python manage.py shell
>>> from yourapp.models import Post
>>> post = Post.create_post(user, "Test", "Content")

# Check outbox via HTTP (using the catch-all view)
curl -H "Accept: application/activity+json" \
     http://localhost:8000/actors/123/outbox

# Check Celery logs for delivery
tail -f celery.log
```

## Error Handling

Handle delivery failures gracefully:

```python
from activitypub.models import NotificationProcessResult

# Check delivery results
def check_delivery_status(activity_ref):
    """Check delivery status for an activity."""
    from activitypub.models import Notification
    
    notifications = Notification.objects.filter(resource=activity_ref)
    
    for notification in notifications:
        results = notification.results.all()
        for result in results:
            if result.result != NotificationProcessResult.Types.OK:
                logger.warning(
                    f"Delivery failed to {notification.target.uri}: {result.result}"
                )
```

The toolkit records delivery results but doesn't retry automatically. You can implement retry logic if needed:

```python
from celery import shared_task

@shared_task
def retry_failed_deliveries():
    """Retry failed deliveries."""
    from activitypub.models import Notification, NotificationProcessResult
    
    # Find notifications with failed results
    failed_results = NotificationProcessResult.objects.filter(
        result__in=[
            NotificationProcessResult.Types.BAD_REQUEST,
            NotificationProcessResult.Types.UNAUTHENTICATED,
        ]
    )
    
    for result in failed_results:
        notification = result.notification
        
        # Retry delivery
        send_notification.delay(notification_id=str(notification.id))
```

## Performance Considerations

- **Use Celery** - The `send_notification.delay()` task runs asynchronously
- **Batch deliveries** - The toolkit automatically batches to shared inboxes
- **Monitor delivery** - Check `NotificationProcessResult` for failures
- **Limit retries** - Don't retry permanent failures (404, 410)

## What You DON'T Need to Do

The toolkit handles these automatically:

- **HTTP signatures** - Generated automatically from actor's keypair
- **JSON-LD serialization** - Activity is serialized to proper format
- **Shared inbox optimization** - `followers_inboxes` prefers shared inboxes
- **Request signing** - The `send_notification` task signs all requests

You just create activities and notifications - the toolkit handles delivery.

## Next Steps

With activity publishing working, you can:

- [Handle incoming activities](handle_incoming_activities.md) from other servers
- [Block spam](block_spam.md) from malicious servers
- Set up [WebFinger discovery](register_account.md) for user lookup
