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

This minimal configuration establishes your server's identity. The `DEFAULT_URL` must match your production domain. Additional settings control collection pagination and document resolvers. See the settings reference for details.

## Setting Up URL Patterns

The toolkit provides `ActivityPubObjectDetailView` as a universal handler for any local object reference. Configure it as a catch-all pattern to handle all federated content:

```python
# project/urls.py
from django.urls import path, include
from activitypub.views import (
    ActivityPubObjectDetailView,
    NodeInfo,
    NodeInfo2,
    Webfinger,
    HostMeta,
)

urlpatterns = [
    # Your existing URL patterns
    path('admin/', admin.site.urls),
    path('blog/', include('blog.urls')),

    # Discovery endpoints (required for federation)
    path('.well-known/nodeinfo', NodeInfo.as_view(), name='nodeinfo'),
    path('.well-known/webfinger', Webfinger.as_view(), name='webfinger'),
    path('.well-known/host-meta', HostMeta.as_view(), name='host-meta'),
    path('nodeinfo/2.0', NodeInfo2.as_view(), name='nodeinfo20'),

    # Catch-all pattern for all ActivityPub objects (must be last)
    path('<path:resource>', ActivityPubObjectDetailView.as_view(), name='activitypub-resource'),
]
```

The catch-all pattern handles GET requests for any local object (returning JSON-LD) and POST requests to inboxes and outboxes. This single view replaces the need for custom inbox views or object detail views.

## Create a Local Domain

The toolkit requires a local domain record. Create one using the Django shell or a management command:

```python
# In Django shell or a data migration
from activitypub.core.models import Domain

Domain.objects.get_or_create(
    name='yourblog.com',
    defaults={'local': True}
)
```

This domain represents your server in the federation network.

## Connecting Your Models to References

The toolkit uses `Reference` objects as bridge pointers between your application models and their federated representations. Add a nullable `OneToOneField` to models you want to federate:

```python
from django.db import models
from django.contrib.auth.models import User
from activitypub.core.models import Reference

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
        null=True,
        blank=True
    )
```

Run migrations to add the field:

```bash
python manage.py makemigrations
python manage.py migrate
```

The nullable reference field allows existing posts to coexist without requiring immediate federation. You'll backfill these references later.

## Linking Users to Actors

Users who create content need ActivityPub actor representations. The toolkit provides `ActorAccount`, which extends Django's `AbstractBaseUser` and directly links to an `ActorContext`. This eliminates the need for a separate Account model while providing authentication capabilities.

Create a signal to generate actors automatically for new users:

```python
# blog/signals.py
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from activitypub.core.models import ActorAccount, ActorContext, CollectionContext, Domain, Reference

@receiver(post_save, sender=User)
def create_user_actor(sender, instance, created, **kwargs):
    if not created:
        return

    # Check if user already has an actor account
    if ActorAccount.objects.filter(actor__preferred_username=instance.username).exists():
        return

    domain = Domain.objects.get(local=True)
    username = instance.username

    # Generate URIs using the domain
    actor_uri = f"https://{domain.name}/users/{username}"
    actor_ref = Reference.make(actor_uri)

    # Create actor context
    actor = ActorContext.make(
        reference=actor_ref,
        type=ActorContext.Types.PERSON,
        preferred_username=username,
        name=instance.get_full_name() or username,
    )

    # Create collections for the actor
    inbox_ref = CollectionContext.generate_reference(domain)
    outbox_ref = CollectionContext.generate_reference(domain)
    followers_ref = CollectionContext.generate_reference(domain)
    following_ref = CollectionContext.generate_reference(domain)

    CollectionContext.make(
        reference=inbox_ref,
        type=CollectionContext.Types.ORDERED_COLLECTION,
        name=f"Inbox for {username}"
    )
    CollectionContext.make(
        reference=outbox_ref,
        type=CollectionContext.Types.ORDERED_COLLECTION,
        name=f"Outbox for {username}"
    )
    CollectionContext.make(
        reference=followers_ref,
        type=CollectionContext.Types.COLLECTION,
        name=f"Followers of {username}"
    )
    CollectionContext.make(
        reference=following_ref,
        type=CollectionContext.Types.COLLECTION,
        name=f"Following for {username}"
    )

    # Attach collections to actor
    actor.inbox = inbox_ref
    actor.outbox = outbox_ref
    actor.followers = followers_ref
    actor.following = following_ref
    actor.save()

    # Create ActorAccount for authentication and WebFinger discovery
    ActorAccount.objects.create(actor=actor)
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

New users automatically receive ActivityPub actors. The `ActorAccount` model provides authentication capabilities and enables WebFinger discovery through the actor's `preferred_username` and domain information stored in the reference.

## Backfilling Actors for Existing Users

Create a management command to create actors for existing users:

```python
# blog/management/commands/backfill_actors.py
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from activitypub.core.models import ActorAccount

class Command(BaseCommand):
    help = 'Create ActivityPub actors for existing users'

    def handle(self, *args, **options):
        # Find users without actor accounts
        existing_usernames = ActorAccount.objects.values_list(
            'actor__preferred_username', flat=True
        )
        users_without_accounts = User.objects.exclude(
            username__in=existing_usernames
        )

        count = 0
        for user in users_without_accounts:
            # The signal will handle creation
            from blog.signals import create_user_actor
            create_user_actor(User, user, created=True)
            count += 1

        self.stdout.write(
            self.style.SUCCESS(f'Created actors for {count} users')
        )
```

Run the command:

```bash
python manage.py backfill_actors
```

## Creating Federated References for New Content

When creating new posts, generate a reference and attach ActivityPub context:

```python
from django.utils import timezone
from activitypub.core.models import ObjectContext, Reference, Domain, ActorAccount

def create_post(user, title, content):
    # Get the local domain
    domain = Domain.objects.get(local=True)

    # Generate a reference for this post
    post_ref = ObjectContext.generate_reference(domain)

    # Create application model
    post = Post.objects.create(
        title=title,
        content=content,
        author=user,
        reference=post_ref
    )

    # Get the user's actor account
    actor_account = ActorAccount.objects.get(actor__preferred_username=user.username)

    # Create ActivityPub context for the post
    obj_context = ObjectContext.make(
        reference=post_ref,
        type=ObjectContext.Types.ARTICLE,
        name=title,
        content=content,
        published=post.published_at,
        attributed_to=actor_account.actor.reference
    )

    return post
```

The reference connects your Post model to its federated ObjectContext. The catch-all URL pattern automatically serves the JSON-LD representation when other servers request the post's URI.

## Backfilling References for Existing Content

Create a management command to generate references for existing posts:

```python
# blog/management/commands/backfill_post_references.py
from django.core.management.base import BaseCommand
from activitypub.core.models import ObjectContext, Reference, Domain, ActorAccount
from blog.models import Post

class Command(BaseCommand):
    help = 'Create ActivityPub references for existing posts'

    def handle(self, *args, **options):
        domain = Domain.objects.get(local=True)
        posts_without_refs = Post.objects.filter(reference__isnull=True)
        count = 0

        for post in posts_without_refs:
            # Generate reference
            post_ref = ObjectContext.generate_reference(domain)

            # Get author's actor account
            try:
                actor_account = ActorAccount.objects.get(
                    actor__preferred_username=post.author.username
                )
            except ActorAccount.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(f'No actor account for user {post.author.username}')
                )
                continue

            # Create context
            ObjectContext.make(
                reference=post_ref,
                type=ObjectContext.Types.ARTICLE,
                name=post.title,
                content=post.content,
                published=post.published_at,
                attributed_to=actor_account.actor.reference
            )

            # Link to post
            post.reference = post_ref
            post.save()
            count += 1

        self.stdout.write(
            self.style.SUCCESS(f'Created {count} references')
        )
```

Run the command:

```bash
python manage.py backfill_post_references
```

All posts now have federated representations accessible via the catch-all view.

## Publishing Activities to Followers

When creating new posts, publish Create activities to followers' inboxes:

```python
from activitypub.core.models import ActivityContext, Notification, ActorAccount, Domain

def publish_post_to_followers(post):
    # Get the author's actor account
    actor_account = ActorAccount.objects.get(actor__preferred_username=post.author.username)
    actor = actor_account.actor

    # Generate activity reference
    domain = Domain.objects.get(local=True)
    activity_ref = ActivityContext.generate_reference(domain)

    # Create the Create activity
    activity = ActivityContext.make(
        reference=activity_ref,
        type=ActivityContext.Types.CREATE,
        actor=actor.reference,
        object=post.reference,
        published=timezone.now()
    )

    # Send to all follower inboxes
    for inbox_ref in actor.followers_inboxes:
        Notification.objects.create(
            resource=activity.reference,
            sender=actor.reference,
            target=inbox_ref
        )
```

The toolkit's background tasks handle delivery, HTTP signature signing, and retry logic automatically. You just create the Notification records.

## Receiving Federated Activities

The catch-all `ActivityPubObjectDetailView` handles incoming POST requests to inbox URIs automatically. When a remote server POSTs an activity to your user's inbox:

1. The view creates a Notification
2. HTTP signatures are verified
3. The activity document is stored
4. Standard flows (Follow, Like, Announce) are processed automatically
5. Collections are updated automatically

You don't need custom inbox views. The automatic processing handles standard ActivityPub semantics.

## Adding Custom Logic for Incoming Activities

If you need application-specific behavior beyond standard ActivityPub flows, connect to signals:

```python
# blog/handlers.py
import logging
from django.dispatch import receiver
from django.core.mail import send_mail
from activitypub.core.signals import activity_done
from activitypub.core.models import ActivityContext, ObjectContext
from blog.models import Post

logger = logging.getLogger(__name__)

@receiver(activity_done)
def notify_author_of_reply(sender, activity, **kwargs):
    """Email post authors when someone replies to their post."""

    if activity.type != ActivityContext.Types.CREATE:
        return

    # Get the created object
    obj_ref = activity.object
    if not obj_ref:
        return

    obj = obj_ref.get_by_context(ObjectContext)
    if not obj or not obj.in_reply_to.exists():
        return

    # Check if replying to one of our posts
    for parent_ref in obj.in_reply_to.all():
        try:
            post = Post.objects.get(reference=parent_ref)

            # Send notification to author
            send_mail(
                subject=f'New reply to your post: {post.title}',
                message=f'Someone replied to your post.\n\n{obj.content}',
                from_email='noreply@yourblog.com',
                recipient_list=[post.author.email],
            )

            logger.info(f"Sent reply notification for post {post.id}")

        except Post.DoesNotExist:
            continue
```

Register handlers in your app's ready() method:

```python
# blog/apps.py
class BlogConfig(AppConfig):
    # ...

    def ready(self):
        from . import signals
        from . import handlers  # Import to register signal handlers
```

The handler runs after the toolkit has already added the reply to the parent post's `replies` collection. Your code adds email notifications on top of the standard protocol handling.

## WebFinger Discovery

The WebFinger view enables account discovery across the Fediverse. With the discovery URLs configured earlier and `ActorAccount` records created for your users, actors are automatically discoverable at `@username@yourblog.com`. The toolkit resolves the username and domain from the actor's `preferred_username` field and the reference's domain.

You can customize the WebFinger response by subclassing the view:

```python
from activitypub.views import Webfinger

class CustomWebfinger(Webfinger):
    def get_profile_page_url(self, request, actor_account):
        """Add a link to the user's HTML profile page."""
        return f"https://yourblog.com/@{actor_account.actor.preferred_username}"
```

Update your URLs:

```python
path('.well-known/webfinger', CustomWebfinger.as_view(), name='webfinger'),
```

## Maintaining Separation of Concerns

The integration pattern maintains clear architectural boundaries:

- **Application models** (`Post`, `Comment`, `User`) handle your business logic, validation, and application-specific features
- **Context models** (`ObjectContext`, `ActorContext`, `ActivityContext`) provide ActivityPub vocabulary translation
- **References** connect the two layers
- **The catch-all view** serves everything automatically

This separation allows evolution in both directions. Change your Post model schema without affecting federated representations. Update ActivityPub vocabulary without touching application code. The reference layer bridges the two worlds.

Your existing views, templates, and business logic remain unchanged. Federation is added alongside your application, not intertwined with it.

## Testing Federation

Test that your integration works by checking a few key endpoints:

**Test WebFinger discovery:**
```bash
curl "https://yourblog.com/.well-known/webfinger?resource=acct:alice@yourblog.com"
```

**Test actor JSON:**
```bash
curl -H "Accept: application/activity+json" https://yourblog.com/users/alice
```

**Test post JSON:**
```bash
curl -H "Accept: application/activity+json" https://yourblog.com/posts/some-post-id
```

**Test inbox (requires authentication):**
```bash
curl -X POST https://yourblog.com/users/alice/inbox \
  -H "Content-Type: application/activity+json" \
  -d '{"type": "Follow", ...}'
```

The catch-all view automatically handles all these requests based on the URI and the Reference objects in your database.

## Next Steps

Your existing application now federates with minimal changes to your core models and logic. To extend functionality:

- **Content updates**: Send Update activities when posts are edited
- **Content deletion**: Send Delete activities and tombstone content
- **Custom context models**: Create application-specific ActivityPub vocabulary (see [Creating Custom Context Models](creating_custom_context_models.md))
- **Moderation**: Implement domain blocking and content filtering
- **Collections**: Expose custom collections (tags, categories) as ActivityPub collections

The toolkit provides the infrastructure. Your application provides the content and business logic. Together they create a federated experience without architectural compromises.
