# Serializers Reference

Serializers handle conversion between Django model instances and
JSON-LD representations for ActivityPub federation. They work in
conjunction with the framing system to produce context-appropriate
output.

## Core Serializer Classes

### ContextModelSerializer

::: activitypub.serializers.linked_data.ContextModelSerializer
    heading_level: 3

Serializes individual context model instances to expanded JSON-LD.
Uses the model's `LINKED_DATA_FIELDS` mapping to convert Django fields
to RDF predicates.

**Access Control:**

Serializers support optional `show_<field_name>()` methods for
field-level access control:

```python
class ActorContextSerializer(ContextModelSerializer):
    def show_followers(self, instance, viewer):
        # Only show followers to the actor themselves
        return viewer and viewer.uri == instance.reference.uri
```

### LinkedDataSerializer

::: activitypub.serializers.linked_data.LinkedDataSerializer
    heading_level: 3

Main serializer that coordinates multiple context models for a
reference. Automatically discovers which context models have data and
merges their output.

**Usage:**

```python
from activitypub.serializers import LinkedDataSerializer

serializer = LinkedDataSerializer(
    instance=reference,
    context={'viewer': viewer, 'request': request}
)
expanded_data = serializer.data
```

**Integration with Framing:**

The serializer produces expanded JSON-LD, which the framing system
then shapes based on context:

```python
from activitypub.frames import FrameRegistry

serializer = LinkedDataSerializer(instance=reference, context={'viewer': viewer})
frame = FrameRegistry.auto_frame(serializer)  # Automatic frame selection
document = frame.to_framed_document()  # Apply context-aware shaping
```

## Collection Serializers

### CollectionContextSerializer

::: activitypub.serializers.collections.CollectionContextSerializer
    heading_level: 3

Specialized serializer for collection contexts. Handles pagination and
item serialization.

## NodeInfo Serializer

::: activitypub.serializers.nodeinfo.NodeInfoSerializer
    heading_level: 3

Serializes server metadata for the NodeInfo protocol.

## Custom Serialization

The toolkit supports custom serializers for specific context models:

```python
FEDERATION = {
    'CUSTOM_SERIALIZERS': {
        ObjectContext: CustomObjectSerializer,
    }
}
```

Custom serializers must inherit from `ContextModelSerializer` and
implement the same interface:

```python
from activitypub.serializers import ContextModelSerializer

class CustomObjectSerializer(ContextModelSerializer):
    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Add custom fields or transformations
        return data

    def show_sensitive_field(self, instance, viewer):
        # Custom access control
        return viewer and self.can_view(viewer, instance)
```

## Serialization Pipeline

The complete serialization pipeline involves three stages:

1. **Serialization** - `LinkedDataSerializer` produces expanded
   JSON-LD with full predicate URIs
2. **Framing** - Frames shape the structure based on context
   (omit/reference/embed decisions)
3. **Compaction** - JSON-LD compaction produces readable output with
   short keys and `@context`

```python
# In a view
serializer = LinkedDataSerializer(instance=reference, context={'viewer': viewer})
frame = FrameRegistry.auto_frame(serializer)
expanded_framed = frame.to_framed_document()

# Get compact context and compact the document
context = serializer.get_compact_context(reference)
compacted = jsonld.compact(expanded_framed, context)
```

This separation of concerns allows each stage to focus on its
responsibility:
- Serializers extract and convert data
- Frames shape structure based on context
- Compaction provides readability

## Access Control Patterns

### Field-Level Control

```python
def show_inbox(self, instance, viewer):
    # Only show inbox URL to owner
    return viewer and viewer.uri == instance.reference.uri
```

### Viewer-Aware Serialization

The `viewer` parameter in the context represents the authenticated
actor viewing the resource:

```python
serializer = LinkedDataSerializer(
    instance=actor_ref,
    context={'viewer': requesting_actor_ref}
)
```

Serializers can use this to filter fields:

```python
def show_followers(self, instance, viewer):
    if not viewer:
        return False  # Anonymous viewers can't see followers
    if viewer.uri == instance.reference.uri:
        return True  # Actor can see their own followers
    return False  # Others can't see followers
```

### Combined with Framing

Access control happens at serialization time. Framing happens
afterward and only sees fields that passed access control. This means
sensitive fields are completely excluded from the document, not just
hidden by framing.

## Performance Considerations

Serialization involves:
- Querying context models for a reference
- Walking through `LINKED_DATA_FIELDS` mappings
- Resolving references for foreign keys
- Potentially recursing for embedded objects (via framing)

For high-traffic endpoints, consider:

1. **Caching** - Cache serialized output for public resources
2. **Selective Loading** - Use `select_related` and `prefetch_related`
   when querying references
3. **Depth Limits** - Frame configuration controls embedding depth to
   prevent expensive recursion
4. **Lazy Evaluation** - Serializers evaluate lazily; access `.data`
   only when needed
