---
title: Working with Reference-Based Relationships
---

# Working with Reference-Based Relationships

This how-to guide shows you how to use `ReferenceField` and `RelatedContextField` in your Django ActivityPub applications to work with federated data structures without requiring immediate persistence.

## Prerequisites

- Complete the [Getting Started](../tutorials/getting_started.md) tutorial
- Understand Django models and relationships
- Familiarity with ActivityPub concepts

## Adding ReferenceField to Models

`ReferenceField` creates many-to-many relationships that work on unsaved model instances:

```python
from activitypub.core.models import ReferenceField

class ObjectContext(models.Model):
    reference = models.OneToOneField(Reference, on_delete=models.CASCADE)
    tags = ReferenceField()  # Many-to-many with Reference objects
    attachments = ReferenceField()

    class Meta:
        abstract = True
```

## Using RelatedContextField for Navigation

`RelatedContextField` provides lazy access to ActivityStreams contexts:

```python
from activitypub.core.models import RelatedContextField

class Site(models.Model):
    reference = models.ForeignKey(Reference, on_delete=models.CASCADE)

    # Lazy access to contexts
    as2 = RelatedContextField(ObjectContext)
    actor = RelatedContextField(ActorContext)
```

## Working with Unsaved Instances

### Creating Context Relationships Before Persistence

```python
from activitypub.core.models import Reference

# Create references for federated content
post_ref = Reference.make("https://example.com/posts/123")
tag_ref = Reference.make("https://example.com/tags/python")

# Work with context before saving
post = ObjectContext(reference=post_ref)
post.name = "My Python Post"
post.content = "Learning Python is fun!"

# Add relationships immediately - no database save required
post.tags.add(tag_ref)

# Query relationships on unsaved instances
tag_count = post.tags.count()  # Works!
tags = post.tags.all()          # Works!

# Persist when ready
if should_save:
    post.save()
```

### Navigating Complex Structures

```python
# Get a site with its reference
site = Site.objects.get(pk=1)

# Access ActivityStreams context lazily
site.as2.name = "My Blog"  # Creates ObjectContext if needed

# Navigate through relationships
first_tag = site.as2.tags.first()
if first_tag:
    tag_context = first_tag.get_by_context(ObjectContext)
    print(f"Tag: {tag_context.name}")

# Add more relationships
new_tag_ref = Reference.make("https://example.com/tags/django")
site.as2.tags.add(new_tag_ref)
```

## Managing Relationships

### Adding and Removing References

```python
# Add multiple references
tag_refs = [
    Reference.make("https://example.com/tags/python"),
    Reference.make("https://example.com/tags/django"),
    Reference.make("https://example.com/tags/activitypub"),
]

post.tags.add(*tag_refs)

# Remove specific references
post.tags.remove(tag_refs[0])

# Clear all relationships
post.tags.clear()

# Replace all relationships
post.tags.set(tag_refs[1:])  # Keep only django and activitypub
```

### Querying Relationships

```python
# Filter related references
python_tags = post.tags.filter(uri__icontains="python")

# Check existence
has_tags = post.tags.exists()

# Count relationships
tag_count = post.tags.count()

# Get first/last
first_tag = post.tags.first()
last_tag = post.tags.last()
```

## ContextProxy Behavior

### Lazy Loading

`RelatedContextField` returns a `ContextProxy` that loads contexts on-demand:

```python
# No database queries yet
proxy = site.as2  # Just creates proxy object

# First access loads the context
name = proxy.name  # ← Database query happens here

# Subsequent access reuses loaded context
content = proxy.content  # ← No additional query
```

### Automatic Context Creation

If a context doesn't exist, `ContextProxy` creates it automatically:

```python
# Context doesn't exist in database
site.as2  # Proxy created

# Setting attributes creates the context
site.as2.name = "New Site"  # ← ObjectContext created and cached

# Context is now available for relationships
site.as2.tags.add(tag_ref)  # Works on the created context
```

## Signal Integration

`ReferenceField` maintains full compatibility with Django's signal system:

```python
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

@receiver(m2m_changed, sender=ObjectContext.tags.through)
def handle_tag_changes(sender, instance, action, pk_set, **kwargs):
    if action == "post_add":
        # Handle new tags added
        for tag_id in pk_set:
            tag_ref = Reference.objects.get(pk=tag_id)
            print(f"Tag {tag_ref.uri} added to {instance}")

    elif action == "post_remove":
        # Handle tags removed
        print(f"Tags removed from {instance}")
```

## Performance Optimization

### Prefetching Related References

```python
# Prefetch related references to avoid N+1 queries
sites = Site.objects.prefetch_related(
    'reference__objectcontext_tags__target_reference'
).all()

for site in sites:
    # This won't trigger additional queries
    for tag in site.as2.tags.all():
        print(tag.uri)
```

### Selective Persistence

Defer saving contexts until necessary:

```python
def process_federated_content(activity_data):
    # Create references and contexts
    activity_ref = Reference.make(activity_data['id'])
    activity = ActivityContext(reference=activity_ref)

    # Process relationships without saving
    for tag_uri in activity_data.get('tags', []):
        tag_ref = Reference.make(tag_uri)
        activity.tags.add(tag_ref)

    # Validate and decide whether to persist
    if is_valid_activity(activity):
        activity.save()  # Persist everything at once
        return activity

    # Don't save invalid content
    return None
```

## Common Patterns

### Processing Incoming Activities

```python
def handle_create_activity(activity_data):
    # Create activity context
    activity_ref = Reference.make(activity_data['id'])
    activity = ActivityContext(reference=activity_ref)
    activity.type = activity_data['type']

    # Process object
    object_ref = Reference.make(activity_data['object']['id'])
    activity.object = object_ref

    # Add tags if present
    if 'tags' in activity_data['object']:
        for tag_data in activity_data['object']['tags']:
            tag_ref = Reference.make(tag_data['id'])
            activity.object.get_by_context(ObjectContext).tags.add(tag_ref)

    # Persist based on business logic
    if should_federate(activity):
        activity.save()
        return activity

    return None
```

### Building Response Activities

```python
def create_like_activity(post_ref, actor_ref):
    # Create activity reference
    activity_ref = Reference.make(f"{actor_ref.uri}/likes/{post_ref.uri.split('/')[-1]}")
    activity = ActivityContext(reference=activity_ref)
    activity.type = "Like"
    activity.actor = actor_ref
    activity.object = post_ref

    # Add to actor's outbox collection
    actor = actor_ref.get_by_context(ActorContext)
    if actor.outbox:
        outbox = actor.outbox.get_by_context(CollectionContext)
        outbox.items.add(activity_ref)

    return activity
```

## Troubleshooting

### "Cannot resolve keyword 'source_reference' into field"

This error occurs when through tables weren't created properly. Ensure:

1. The model containing `ReferenceField` is not abstract
2. Migrations have been run after adding the field
3. The through model was registered correctly

### ContextProxy Not Loading Contexts

If `RelatedContextField` doesn't load contexts:

1. Check that the reference exists
2. Verify the context class inherits from `AbstractContextModel`
3. Ensure the context class has the correct `LINKED_DATA_FIELDS`

### Signal Handlers Not Triggering

Signal handlers use `sender=Model.field.through`. With `ReferenceField`:

```python
# Correct - use the through model
@receiver(m2m_changed, sender=MyModel.relationships.through)

# Incorrect - won't work with ReferenceField
@receiver(m2m_changed, sender=MyModel.relationships)
```

## Next Steps

- Read the [Reference-Based Relationships](../topics/reference_based_relationships.md) topic guide for deeper understanding
- Explore [Handling Incoming Activities](handle_incoming_activities.md) for processing federated content
- Learn about [Sending Activities](send_activities.md) to publish content to the Fediverse
