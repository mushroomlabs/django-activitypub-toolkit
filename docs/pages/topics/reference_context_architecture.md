---
title: References and Context Models
---

Django ActivityPub Toolkit bridges the gap between RDF's graph model and Django's relational database through a two-layer architecture: References and Context Models. This design lets you leverage Linked Data principles while working with familiar Django patterns.

## The Reference Layer

A `Reference` represents a node in the global social graph. Each reference has a URI that uniquely identifies a resource, whether that resource lives on your server or a remote server.

```python
from activitypub.core.models import Reference

# Reference to a local resource
local_ref = Reference.objects.get(uri='https://myserver.com/users/alice')

# Reference to a remote resource
remote_ref = Reference.objects.get(uri='https://other-server.com/posts/456')
```

References are intentionally minimal. They track the URI, which domain owns it, and whether the resource has been successfully resolved from its origin. This lightweight design means you can store references to millions of resources without significant overhead.

The reference layer serves several purposes. It provides a unified way to link between resources regardless of where they live. It prevents duplicate entries for the same URI. Most importantly, it separates graph navigation from vocabulary-specific data access.

When you navigate relationships in the Fediverse, you work primarily with references. A post's replies, an actor's followers, items in a collection—these are all stored as references. You don't need to fetch or parse the full data for each referenced resource unless your application needs that data.

## Context Models

Context models attach application-specific meaning to references for particular object types. When you need to read or write attributes for a specific kind of object (like "Lemmy Community" or "Mastodon Status"), you use the corresponding context model.

Context models are composable and organized by "what kind of thing is this?" rather than "which namespace prefix does it use?" Each context model handles only its specific fields without overlapping with other contexts. Multiple context models can process the same reference, each extracting their respective fields.

ActivityStreams 2.0, the core vocabulary for ActivityPub, maps to context models like `ObjectContext`, `ActorContext`, and `ActivityContext`. These models store properties such as `content`, `name`, `published`, and relationship pointers like `attributed_to` and `in_reply_to`.

```python
from activitypub.core.models import Reference, ObjectContext

ref = Reference.objects.get(uri='https://example.com/posts/123')

# Access AS2-specific attributes
obj = ref.get_by_context(ObjectContext)
print(obj.content)  # "Just learned about Linked Data"
print(obj.name)     # "My First Post"
```

A single reference can have multiple context models attached. An actor might have both `ActorContext` (for AS2 properties like `preferred_username` and `inbox`) and `SECv1Context` (for cryptographic key information). Extensions from platforms like Mastodon or Lemmy would add their own context models.

Context models discriminate by object type and application identity, not just namespace presence. A Lemmy community context model would check both that the object is a Group type AND that it has Lemmy-specific properties, ensuring it only processes objects from the expected application.

## Reference-Based Relationships

Traditional Django many-to-many relationships require both sides of the relationship to have primary keys. This creates a chicken-and-egg problem when working with federated content that may not be persisted immediately. The toolkit solves this with **reference-based relationships** that link via `Reference` objects instead of model primary keys.

### ReferenceField: Many-to-Many Without Persistence

The `ReferenceField` is a specialized many-to-many field that creates relationships between `Reference` objects rather than model instances. This enables several key capabilities:

- **Query relationships on unsaved instances** - Access related data before saving the model
- **Lazy context loading** - Load ActivityStreams contexts only when needed
- **Federation-first design** - Work with references before resolving their content

Instead of creating through tables with `source_model_id → target_model_id`, `ReferenceField` creates tables with `source_reference_id → target_reference_id`:

```sql
-- Traditional M2M through table
CREATE TABLE app_model_tags (
    id INTEGER PRIMARY KEY,
    model_id INTEGER REFERENCES app_model(id),
    tag_id INTEGER REFERENCES app_tag(id)
);

-- ReferenceField through table
CREATE TABLE app_model_tags (
    id INTEGER PRIMARY KEY,
    source_reference_id INTEGER REFERENCES activitypub_reference(id),
    target_reference_id INTEGER REFERENCES activitypub_reference(id)
);
```

Usage example:

```python
from activitypub.core.models import ReferenceField

class ObjectContext(models.Model):
    reference = models.OneToOneField(Reference, on_delete=models.CASCADE)
    tags = ReferenceField()  # Links to Reference objects

    class Meta:
        abstract = True

# Works even on unsaved instances
obj = ObjectContext(reference=some_ref)
obj.tags.add(tag_ref1, tag_ref2)  # Works immediately
related_tags = obj.tags.all()     # Queries work
```

### RelatedContextField: Lazy Context Navigation

The `RelatedContextField` provides lazy access to ActivityStreams contexts through a `ContextProxy`. This allows you to navigate and modify context data without loading it from the database until necessary.

```python
from activitypub.core.models import RelatedContextField

class Site(models.Model):
    reference = models.ForeignKey(Reference, on_delete=models.CASCADE)
    as2 = RelatedContextField(ObjectContext)

# Navigate contexts without database hits
site = Site.objects.get(pk=1)
site.as2.name = "My Site"           # Creates context if needed
sidebar_ref = site.as2.source.first()  # ReferenceField works on proxy
site.as2.tags.add(tag_ref)          # Relationships work

# Persist when ready
if should_save:
    site.as2.save()
```

### Benefits of Reference-Based Relationships

**Deferred Persistence** - Work with federated data structures before deciding what to persist:

```python
# Process incoming activity without saving anything
activity = ActivityContext(reference=activity_ref)
actor = activity.actor.get_by_context(ActorContext)

# Only save what matters for your application
if activity.type == 'Create' and actor.is_local:
    activity.save()
    actor.save()
```

**Memory Efficient** - Load context data only when accessed:

```python
# No database queries until actually needed
site.as2.name  # ← First access loads ObjectContext
site.as2.tags.all()  # ← Subsequent access reuses loaded context
```

**DRF Integration** - Enable complex serializer traversals on unsaved data:

```python
class ActivitySerializer(serializers.Serializer):
    actor_name = serializers.CharField(source="as2.actor.name")
    object_content = serializers.CharField(source="as2.object.content")
    tags = serializers.SerializerMethodField()

    def get_tags(self, obj):
        return [tag.uri for tag in obj.as2.tags.all()]
```

**Signal Compatibility** - ReferenceField maintains full compatibility with Django's signal system:

```python
@receiver(m2m_changed, sender=ObjectContext.tags.through)
def on_tags_changed(sender, instance, action, pk_set, **kwargs):
    if action == 'post_add':
        # Handle tag additions
        pass
```

## From JSON-LD to Context Models

When a remote JSON-LD document arrives, the toolkit processes it through a defined pipeline. First, the document is stored as a `LinkedDataDocument` associated with its reference. Then the document is parsed into an RDF graph using rdflib.

The toolkit walks through all subjects in the graph, creating or retrieving Reference instances for each. For each reference, it checks which context models should handle the data by calling their `should_handle_reference` method.

Context models discriminate by object type and application identity. A `LemmyCommunityContext` would check that the object is a Group type AND has Lemmy-specific properties before processing it. Multiple context models can process the same reference if they match different criteria - they extract their respective fields independently without conflict.

This process happens only once when the document first arrives. After that, all data access goes through Django's ORM, querying the context model tables directly. Graph operations are expensive, so the toolkit converts the graph to relational form and then works relationally.

## The Repository Pattern

This architecture implements the repository pattern adapted for RDF data. Traditional repositories provide data access methods that abstract over a data store. Here, context models serve as repositories that translate between the RDF graph (the conceptual model) and Django models (the persistence layer).

When you query for posts by a particular author, you're not querying an RDF graph. You're using Django's ORM to filter ObjectContext instances. This is dramatically more efficient than graph traversal and integrates naturally with the rest of your Django application.

```python
# Efficient relational query
from activitypub.core.models import ObjectContext, Reference

author_ref = Reference.objects.get(uri='https://example.com/users/alice')
posts = ObjectContext.objects.filter(
    attributed_to=author_ref,
    type=ObjectContext.Types.NOTE
).order_by('-published')
```

The tradeoff is that you need to resolve references before accessing their attributes. If you have a reference to a remote actor, you can't read their name until you've resolved that reference, triggering a fetch of their Actor document.

## Application Integration

Your application models should link to references, not directly to context models. This gives you flexibility to access whatever contexts are relevant while avoiding conflicts between multiple contexts.

```python
from django.db import models
from activitypub.core.models import Reference, RelatedContextField

class Post(models.Model):
    reference = models.ForeignKey(Reference, on_delete=models.CASCADE)
    author = models.ForeignKey('auth.User', on_delete=models.CASCADE)

    # Use RelatedContextField for convenient access
    as2 = RelatedContextField(ObjectContext)

    @property
    def title(self):
        return self.as2.name

    @property
    def body(self):
        return self.as2.content
```

This pattern keeps your application models focused on your business logic while delegating ActivityPub concerns to the context models. You can add methods that combine data from multiple contexts or compute derived values.

When creating a new local post, generate a reference first, then create both your application model and the appropriate context models.

```python
from activitypub.core.models import Domain, Reference, ObjectContext
from myapp.models import Post

# Generate URI for the new post
domain = Domain.get_default()
ref = ObjectContext.generate_reference(domain)

# Create the AS2 context
obj = ObjectContext.make(
    reference=ref,
    type=ObjectContext.Types.ARTICLE,
    name="Understanding References",
    content="<p>This is the post body...</p>",
    published=timezone.now()
)

# Create your application model
post = Post.objects.create(
    reference=ref,
    author=request.user
)
```

The reference links everything together. The context model handles federation. Your application model handles your specific business logic.

## Custom Vocabularies

Applications that work with specialized object types create their own context models by extending `AbstractContextModel`. Each context model handles only its specific fields without overlapping with other contexts. The `should_handle_reference` method discriminates by object type and application identity.

```python
from rdflib import Namespace
from activitypub.core.models import AbstractContextModel, ReferenceField
from activitypub.contexts import AS2, LEMMY, SCHEMA, LEMMY_CONTEXT
from django.db import models

class LemmyCommunityContext(AbstractContextModel):
    """Handles Lemmy-specific fields for Lemmy Community objects."""

    CONTEXT = LEMMY_CONTEXT  # Required for proper serialization
    LINKED_DATA_FIELDS = {
        # Only Lemmy-specific fields (AS2 fields handled by other contexts)
        'stickied': LEMMY.stickied,
        'locked': LEMMY.locked,
        'posting_restricted_to_mods': LEMMY.postingRestrictedToMods,

        # Schema.org fields not covered by other contexts
        'language': SCHEMA.inLanguage,

        # Use ReferenceField for relationships
        'moderators': LEMMY.moderators,
    }

    # Only fields specific to this context
    stickied = models.BooleanField(default=False)
    locked = models.BooleanField(default=False)
    posting_restricted_to_mods = models.BooleanField(default=False)
    language = models.CharField(max_length=10, null=True, blank=True)

    # ReferenceField works on unsaved instances
    moderators = ReferenceField()

    @classmethod
    def should_handle_reference(cls, g: rdflib.Graph, reference: Reference, source: Reference):
        """Check if this is a Lemmy Community by type + Lemmy-specific properties."""
        subject_uri = rdflib.URIRef(reference.uri)

        # Must be a Group type (handled by AS2 context)
        type_val = g.value(subject=subject_uri, predicate=AS2.type)
        if type_val != AS2.Group:
            return False

        # Must have Lemmy-specific properties to confirm it's from Lemmy
        lemmy_fields = (
            g.value(subject=subject_uri, predicate=LEMMY.stickied) or
            g.value(subject=subject_uri, predicate=LEMMY.postingRestrictedToMods) or
            g.value(subject=subject_uri, predicate=LEMMY.locked)
        )

        return lemmy_fields is not None
```

Register custom context models in settings to have them automatically process incoming documents:

```python
FEDERATION = {
    'EXTRA_CONTEXT_MODELS': [
        'myapp.models.LemmyContext',
    ],
}
```

This extensibility lets you adapt the toolkit to any vocabulary without modifying its core. As the Fediverse evolves and platforms add new extensions, your application can incorporate those extensions by adding new context models.

## Design Principles

The reference-context architecture embodies several key principles:

**Separation of concerns.** Graph navigation happens at the reference layer. Vocabulary-specific operations happen at the context layer. Your application logic happens in your models.

**Performance.** Parse the RDF graph once, then work with relational data. Avoid graph operations during normal application flow.

**Extensibility.** New vocabularies add new context models without affecting existing ones. Multiple contexts coexist on the same reference.

**Explicit resolution.** You control when to fetch remote data. References can exist without resolved data until you need it.

**Federation-first relationships.** ReferenceField and RelatedContextField enable working with federated data structures before deciding what to persist, supporting lazy loading and deferred persistence patterns.

These principles guide how you build applications on the toolkit. Think in terms of references when navigating the graph. Think in terms of contexts when working with specific vocabularies. Think in terms of Django models when implementing your application logic.
