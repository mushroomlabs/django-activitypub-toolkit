# Integrating with Your Existing Django Project

This tutorial guides you through adding federation capabilities to an existing Django application using Django ActivityPub Toolkit. You will learn how to retrofit federation without restructuring your existing models or business logic.

By the end, your existing application will publish content to the Fediverse and receive federated activities while maintaining its current architecture and workflows.

## Prerequisites

You need an existing Django project with models representing content you want to federate. This tutorial assumes you understand your application's model structure and have administrative access to modify settings and run migrations.

The examples use a blogging platform with `Post` and `Comment` models, but the patterns apply to any Django application.

## Installation

Add Django ActivityPub Toolkit to your existing project:

```bash
pip install django-activitypub-toolkit
```

Add the toolkit to `INSTALLED_APPS` in your settings file:

```python
INSTALLED_APPS = [
    # Your existing apps
    'django.contrib.admin',
    'django.contrib.auth',
    # ... other apps ...
    'blog',
    'accounts',
    
    # Add the toolkit
    'activitypub',
]
```

Run migrations to create federation tables:

```bash
python manage.py migrate activitypub
```

The toolkit creates tables for References, LinkedDataDocuments, ActivityPub context models, and supporting infrastructure. These tables coexist with your existing schema without modifying it.

## Configure Federation Settings

Add federation configuration to your settings file:

```python
FEDERATION = {
    'DEFAULT_URL': 'https://yourblog.com',
    'SOFTWARE_NAME': 'YourBlog',
    'SOFTWARE_VERSION': '2.1.0',
}
```

This minimal configuration establishes your server's identity. Additional settings control URL patterns, collection pagination, and resolver behavior. See [Configuration and Customization](../topics/application_settings.md) for details.

## Connecting Your Models to References

The toolkit uses `Reference` objects as graph pointers that connect your application models to federated representations. Add a `OneToOneField` to models you want to federate:

```python
from django.db import models
from django.contrib.auth.models import User
from activitypub.models import Reference

class Post(models.Model):
    # Existing fields
    title = models.CharField(max_length=200)
    content = models.TextField()
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    published_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Add federation support
    reference = models.OneToOneField(
        Reference,
        on_delete=models.CASCADE,
        related_name='blog_post',
        null=True,  # Allows migration for existing data
        blank=True
    )
```

Run migrations to add the field:

```bash
python manage.py makemigrations
python manage.py migrate
```

Existing posts now have a nullable reference field. New posts require reference creation during their creation workflow.

## Creating References for New Content

Modify your content creation flow to generate references. For new posts, create a reference and attach context data:

```python
from django.urls import reverse
from activitypub.models import ObjectContext, Reference

def create_post(user, title, content):
    # Generate URI for this post
    post_id = generate_unique_id()  # Your ID generation strategy
    post_uri = f"https://yourblog.com/posts/{post_id}"
    
    # Create reference
    reference = Reference.make(post_uri)
    
    # Create application model
    post = Post.objects.create(
        title=title,
        content=content,
        author=user,
        reference=reference
    )
    
    # Attach context model for federation
    context = ObjectContext.make(
        reference=reference,
        type=ObjectContext.Types.ARTICLE,
        name=title,
        content=content,
        published=post.published_at,
        attributed_to=user.actor.reference  # Assumes user has actor
    )
    
    return post
```

The reference acts as the bridge. Your `Post` model links to it for local concerns. The `ObjectContext` links to it for federation concerns.

## Backfilling References for Existing Content

Existing posts need references. Create a management command to backfill them:

```python
# blog/management/commands/backfill_references.py
from django.core.management.base import BaseCommand
from activitypub.models import ObjectContext, Reference
from blog.models import Post

class Command(BaseCommand):
    help = 'Create references for existing posts'

    def handle(self, *args, **options):
        posts_without_refs = Post.objects.filter(reference__isnull=True)
        count = 0
        
        for post in posts_without_refs:
            uri = f"https://yourblog.com/posts/{post.id}"
            reference = Reference.make(uri)
            
            context = ObjectContext.make(
                reference=reference,
                type=ObjectContext.Types.ARTICLE,
                name=post.title,
                content=post.content,
                published=post.published_at,
                attributed_to=post.author.actor.reference
            )
            
            post.reference = reference
            post.save()
            count += 1
        
        self.stdout.write(
            self.style.SUCCESS(f'Created {count} references')
        )
```

Run the command:

```bash
python manage.py backfill_references
```

All existing posts now have references and federated representations.

## Linking Users to Actors

Users who create content need `Actor` context models. Create a signal to generate actors when users are created:

```python
# blog/signals.py
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from activitypub.models import Account, ActorContext, CollectionContext, Domain, Reference

@receiver(post_save, sender=User)
def create_user_actor(sender, instance, created, **kwargs):
    if not created:
        return
    
    local_domain = Domain.objects.get(local=True)
    username = instance.username
    
    actor_uri = f"https://yourblog.com/users/{username}"
    actor_ref = Reference.make(actor_uri)
    
    # Create collections
    inbox_ref = Reference.make(f"{actor_uri}/inbox")
    outbox_ref = Reference.make(f"{actor_uri}/outbox")
    followers_ref = Reference.make(f"{actor_uri}/followers")
    following_ref = Reference.make(f"{actor_uri}/following")
    
    inbox = CollectionContext.make(inbox_ref, type=CollectionContext.Types.ORDERED)
    outbox = CollectionContext.make(outbox_ref, type=CollectionContext.Types.ORDERED)
    followers = CollectionContext.make(followers_ref, type=CollectionContext.Types.UNORDERED)
    following = CollectionContext.make(following_ref, type=CollectionContext.Types.UNORDERED)
    
    # Create actor
    actor = ActorContext.make(
        reference=actor_ref,
        type=ActorContext.Types.PERSON,
        preferred_username=username,
        name=instance.get_full_name() or username,
        inbox=inbox_ref,
        outbox=outbox_ref,
        followers=followers_ref,
        following=following_ref
    )
    
    # Create account
    Account.objects.create(
        actor=actor,
        domain=local_domain,
        username=username
    )
```

Register the signal in your app configuration:

```python
# blog/apps.py
from django.apps import AppConfig

class BlogConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'blog'

    def ready(self):
        from . import signals
```

New users automatically receive actors. Backfill actors for existing users with another management command following the same pattern as post backfilling.

## Publishing Activities

When posts are published, create activities and send them to followers. Use Django signals or explicit method calls:

```python
from activitypub.models import Activity, Notification

def publish_post(post):
    author = post.author.actor
    
    # Create activity
    activity_uri = f"https://yourblog.com/activities/{generate_unique_id()}"
    activity_ref = Reference.make(activity_uri)
    
    activity = Activity.make(
        reference=activity_ref,
        type=Activity.Types.CREATE,
        actor=author.reference,
        object=post.reference,
        published=timezone.now()
    )
    
    # Send to followers
    for inbox in author.followers_inboxes:
        Notification.objects.create(
            resource=activity.reference,
            sender=author.reference,
            target=inbox
        )
```

The `Notification` model queues outgoing messages. Background tasks process them asynchronously.

## Receiving Federated Content

Configure an inbox endpoint to receive activities from other servers:

```python
# blog/views.py
from activitypub.views.activitystreams import InboxView

class UserInboxView(InboxView):
    def get_inbox(self):
        username = self.kwargs['username']
        account = Account.objects.get(username=username, domain__local=True)
        return account.actor.inbox
```

Add URL routing:

```python
# blog/urls.py
from django.urls import path
from .views import UserInboxView

urlpatterns = [
    path('users/<str:username>/inbox', UserInboxView.as_view(), name='user-inbox'),
]
```

Incoming activities are received, verified, and processed. The toolkit handles HTTP Signatures, activity validation, and queuing for processing.

## Handling Incoming Activities

Create activity handlers to process incoming content. Handle follows, likes, comments:

```python
# blog/handlers.py
from activitypub.handlers import BaseActivityHandler
from activitypub.models import Activity

class FollowHandler(BaseActivityHandler):
    def can_handle(self, activity):
        return activity.type == Activity.Types.FOLLOW
    
    def handle(self, activity):
        follower = activity.actor
        followed = activity.object
        
        # Your business logic
        # e.g., notify user, update follower count
        
        # Accept the follow
        activity.accept()
```

Register handlers in settings:

```python
FEDERATION = {
    # ... other settings ...
    'ACTIVITY_HANDLERS': [
        'blog.handlers.FollowHandler',
    ],
}
```

See [Handling Incoming Activities](handling_incoming_activities.md) for detailed handler implementation.

## Serving ActivityPub Representations

Create views to serve your content as ActivityPub JSON-LD:

```python
from activitypub.views.linked_data import LinkedDataView

class PostDetailView(LinkedDataView):
    def get_reference(self):
        post_id = self.kwargs['post_id']
        post = Post.objects.get(id=post_id)
        return post.reference
```

Add routes:

```python
urlpatterns = [
    path('posts/<int:post_id>', PostDetailView.as_view(), name='post-detail'),
]
```

Requests with `Accept: application/activity+json` receive JSON-LD representations. Regular requests can return HTML templates by extending the view with template rendering.

## WebFinger Discovery

Enable account discovery using WebFinger:

```python
from django.urls import path
from activitypub.views.discovery import WebFingerView

urlpatterns = [
    path('.well-known/webfinger', WebFingerView.as_view(), name='webfinger'),
    path('.well-known/host-meta', HostMetaView.as_view(), name='host-meta'),
]
```

Users are now discoverable at `@username@yourblog.com` across the Fediverse.

## Maintaining Separation of Concerns

The integration pattern maintains clear boundaries:

- **Application models** handle your business logic, validation, and application-specific features
- **Context models** handle vocabulary translation for federation
- **References** connect the two layers

This separation allows you to evolve your application independently of federation concerns. Change your `Post` model schema without affecting federated representations. Modify federated vocabulary without touching application code.

## Next Steps

Your existing application now federates. To extend functionality:

- Add custom context models for application-specific vocabulary (see [Creating Custom Context Models](creating_custom_context_models.md))
- Implement content moderation and domain blocking policies
- Handle updates and deletions with dedicated activity types
- Integrate with background task queues for message processing (Celery, RQ)

The toolkit grows with your application without imposing structural constraints.
