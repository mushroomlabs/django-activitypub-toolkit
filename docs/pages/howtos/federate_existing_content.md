# Federate Existing Content

This guide shows you how to add federation support to content that already exists in your Django application.

## When You Need This

You have an existing Django application with content (posts, articles, comments, etc.) that you want to make available on the Fediverse. You want existing content to be discoverable and interactable by other ActivityPub servers.

## Prerequisites

- Django ActivityPub Toolkit installed and configured
- Database migrations run
- Existing Django models with content you want to federate

## Add Reference Fields

Add a `reference` field to your existing content models:

```python
from django.db import models
from activitypub.models import Reference

class Post(models.Model):
    title = models.CharField(max_length=200)
    content = models.TextField()
    author = models.ForeignKey('auth.User', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    # Add federation support
    reference = models.OneToOneField(
        Reference,
        on_delete=models.CASCADE,
        related_name='blog_post',
        null=True,  # Allow existing records without references
        blank=True
    )
```

Create and run the migration:

```bash
python manage.py makemigrations
python manage.py migrate
```

## Create Backfill Command

Create a management command to add references to existing content:

```python
# yourapp/management/commands/backfill_references.py
from django.core.management.base import BaseCommand
from activitypub.models import Reference, ObjectContext, Domain
from yourapp.models import Post

class Command(BaseCommand):
    help = 'Create references for existing posts'

    def handle(self, *args, **options):
        domain = Domain.get_default()
        posts_without_refs = Post.objects.filter(reference__isnull=True)

        for post in posts_without_refs:
            # Generate URI for this post
            uri = f"https://{domain.name}/posts/{post.id}"

            # Create reference
            reference = Reference.make(uri)

            # Create ActivityPub context
            context = ObjectContext.make(
                reference=reference,
                type=ObjectContext.Types.ARTICLE,
                name=post.title,
                content=post.content,
                published=post.created_at,
                attributed_to=post.author.actor.reference,  # Assumes user has actor
            )

            # Link to existing post
            post.reference = reference
            post.save()

            self.stdout.write(f'Created reference for post {post.id}')

        self.stdout.write(
            self.style.SUCCESS(f'Backfilled {posts_without_refs.count()} posts')
        )
```

## Handle New Content

Update your content creation to automatically create references:

```python
from activitypub.models import Reference, ObjectContext, Domain

class Post(models.Model):
    # ... existing fields ...

    @classmethod
    def create_post(cls, author, title, content):
        """Create a post with federation support."""
        domain = Domain.get_default()

        # Generate URI
        post_id = generate_unique_id()  # Your ID generation
        uri = f"https://{domain.name}/posts/{post_id}"

        # Create reference and context
        reference = Reference.make(uri)
        context = ObjectContext.make(
            reference=reference,
            type=ObjectContext.Types.ARTICLE,
            name=title,
            content=content,
            published=timezone.now(),
            attributed_to=author.actor.reference,
        )

        # Create Django model
        post = cls.objects.create(
            title=title,
            content=content,
            author=author,
            reference=reference
        )

        return post
```

## Update Views

Ensure your content views serve ActivityPub representations:

```python
from activitypub.views import LinkedDataModelView

class PostDetailView(LinkedDataModelView):
    """Serve posts as ActivityPub objects."""

    def get_object(self):
        post_id = self.kwargs['post_id']
        post = get_object_or_404(Post, id=post_id)
        return post.reference
```

Add URL patterns:

```python
urlpatterns = [
    path('posts/<int:post_id>', PostDetailView.as_view(), name='post-detail'),
]
```

## Handle Interactions

Create handlers for federated interactions with your existing content:

```python
from activitypub.signals import activity_processed
from django.dispatch import receiver

@receiver(activity_processed)
def handle_post_interactions(sender, activity, **kwargs):
    """Handle likes, shares, and replies to existing posts."""
    activity_ctx = activity.get_by_context(ActivityContext)

    if activity_ctx.type == ActivityContext.Types.LIKE:
        # Handle likes on existing posts
        obj_ref = activity_ctx.object
        try:
            post = Post.objects.get(reference=obj_ref)
            # Record the like in your existing like system
            Like.objects.create(post=post, actor=activity_ctx.actor, ...)
        except Post.DoesNotExist:
            pass  # Not one of our posts

    # Handle other activity types...
```

## Migration Strategy

For large datasets, consider a phased approach:

1. **Phase 1**: Add reference fields (nullable)
2. **Phase 2**: Backfill recent content (last 30 days)
3. **Phase 3**: Gradually backfill older content
4. **Phase 4**: Make reference field required for new content

This prevents long-running migrations and allows gradual rollout.

## Testing

Test that existing content is now federated:

```bash
# Check ActivityPub representation
curl -H "Accept: application/activity+json" \
     http://localhost:8000/posts/123

# Verify reference creation
python manage.py shell
from yourapp.models import Post
post = Post.objects.get(id=123)
print(post.reference.uri)  # Should show federation URI
```

## Considerations

- **Performance**: Backfilling large datasets may be slow
- **URIs**: Ensure URIs are stable and won't change
- **Privacy**: Consider which existing content should be public
- **Interactions**: Handle federated interactions with existing content appropriately

## Next Steps

With existing content federated, you can:

- [Handle incoming activities](handle_incoming_activities.md) from other servers
- [Send activities](send_activities.md) to publish new content
- Review the [integration tutorial](../tutorials/integration_with_existing_project.md#webfinger-discovery) for WebFinger discovery setup
