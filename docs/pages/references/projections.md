---
title: Projections Reference
---

Projections control how References are serialized to JSON-LD for external viewers. They provide declarative configuration for field inclusion, embedding, computed fields, and access control.

## ReferenceProjection

Base class for all projections. Handles the standard workflow of finding context models, building expanded JSON-LD, applying rules, and compacting output.

### Constructor

```python
ReferenceProjection(reference, scope=None, parent=None)
```

**Parameters:**

- `reference` (Reference) - The Reference instance to project
- `scope` (dict, optional) - Context information including viewer and request
- `parent` (ReferenceProjection, optional) - Parent projection for sharing context tracking

The `scope` dict typically contains:

- `viewer` (Reference, optional) - The Reference of the viewing actor (or None for anonymous)
- `request` (HttpRequest, optional) - The Django request object
- `view` (APIView, optional) - The view instance handling the request

### Meta Class Options

Configure projection behavior through the inner `Meta` class:

#### fields

Allowlist of predicates to include. Mutually exclusive with `omit`. When set, only these predicates appear in output.

```python
class MinimalActorProjection(ReferenceProjection):
    class Meta:
        fields = (AS2.name, AS2.preferredUsername, AS2.inbox, AS2.outbox)
```

#### omit

Denylist of predicates to exclude. All other fields are included.

```python
class PublicActorProjection(ReferenceProjection):
    class Meta:
        omit = (AS2.bcc, AS2.bto, SECv1.privateKeyPem)
```

#### embed

Set of predicates whose references should be recursively embedded using the same projection class.

```python
class QuestionProjection(ReferenceProjection):
    class Meta:
        embed = (AS2.oneOf, AS2.anyOf)
```

References in these fields are expanded to full objects rather than `{"@id": "uri"}`. The same projection class is used recursively.

#### overrides

Dict mapping predicates to specific projection classes for selective embedding.

```python
class NoteProjection(ReferenceProjection):
    class Meta:
        overrides = {
            AS2.replies: CollectionWithFirstPageProjection,
            AS2.likes: CollectionWithTotalProjection,
            AS2.shares: CollectionWithTotalProjection,
        }
```

Use this when different related fields need different projection behaviors.

#### extra

Dict mapping method names to predicates for computed fields.

```python
class ActorProjection(ReferenceProjection):
    @use_context(SEC_V1_CONTEXT.url)
    def get_public_key(self):
        # Compute and return public key data
        ...
    
    class Meta:
        extra = {"get_public_key": SECv1.publicKey}
```

The method is called during projection building. Return data in expanded JSON-LD format (dicts/lists with `@id`, `@value`, `@type` keys). Return `None` to omit the field.

### Methods

#### build()

```python
projection.build()
```

Build the expanded JSON-LD document by:

1. Finding all context models attached to the reference
2. Generating expanded document with full predicate URIs
3. Applying field filters (fields/omit)
4. Processing embed and overrides rules
5. Calling extra field methods
6. Checking show_<field>() methods on context models

Call this before accessing the projection data. It's safe to call multiple times (idempotent).

#### get_expanded()

```python
expanded = projection.get_expanded()
```

Returns the expanded JSON-LD document as a dict. All keys are full predicate URIs. All values are in expanded form with `@value`, `@type`, and `@id` keys.

Automatically calls `build()` if not already built.

#### get_compacted()

```python
compacted = projection.get_compacted()
```

Returns the compacted JSON-LD document using appropriate `@context` definitions. Short property names replace full URIs. The root projection includes the `@context` array; nested projections omit it.

Automatically calls `build()` if not already built.

### Attributes

#### reference

The Reference instance being projected.

#### scope

Dict containing viewer and request context. Access with `self.scope.get('viewer')` or `self.scope.get('request')`.

#### parent

Parent projection if this is a nested projection (when embedding). Used for sharing context tracking.

#### seen_contexts

Set of context URLs that have been used. Shared with parent if present. Used to build the `@context` array.

#### extra_context

Dict of additional context definitions needed. Shared with parent if present. Merged into `@context` when compacting.

## use_context Decorator

Register contexts needed by extra field methods.

```python
from activitypub.projections import use_context
from activitypub.contexts import SEC_V1_CONTEXT

class ActorProjection(ReferenceProjection):
    @use_context(SEC_V1_CONTEXT.url)
    def get_public_key(self):
        # This method requires the Security v1 context
        ...
```

**Parameters:**

- `context` (str or dict) - Context URL string or dict of additional context definitions

Can be stacked to register multiple contexts:

```python
@use_context("https://w3id.org/security/v1")
@use_context({"customProp": "https://example.com/customProp"})
def my_method(self):
    ...
```

The decorator ensures the context appears in the `@context` array when compacting the final document.

## Built-in Projections

### CollectionProjection

Projects collections with items and total count.

```python
from activitypub.projections import CollectionProjection

projection = CollectionProjection(collection_ref)
```

Adds `get_items()` and `get_total_items()` as extra fields. Items appear as an array of `{"@id": "uri"}` references.

### CollectionPageProjection

Projects collection pages with items.

```python
from activitypub.projections import CollectionPageProjection

projection = CollectionPageProjection(page_ref)
```

Includes items for the specific page.

### CollectionWithFirstPageProjection

Projects collections with the first page embedded.

```python
from activitypub.projections import CollectionWithFirstPageProjection

projection = CollectionWithFirstPageProjection(collection_ref)
```

**Meta configuration:**

- Omits: `items`, `orderedItems`, `last`
- Overrides: `first` with `CollectionPageProjection`
- Extra: `get_total_items`

Use for collection endpoints where you want viewers to see the first page immediately without a separate request.

### CollectionWithTotalProjection

Projects collections showing only the total count.

```python
from activitypub.projections import CollectionWithTotalProjection

projection = CollectionWithTotalProjection(collection_ref)
```

Only includes `totalItems`. Use for counts like likes and shares where the full list isn't needed.

### ActorProjection

Projects actors with embedded public keys.

```python
from activitypub.projections import ActorProjection

projection = ActorProjection(actor_ref)
```

Adds `get_public_key()` as an extra field that embeds the actor's public key using `PublicKeyProjection`. Requires the Security v1 context.

### QuestionProjection

Projects Question objects with embedded choices.

```python
from activitypub.projections import QuestionProjection

projection = QuestionProjection(question_ref)
```

**Meta configuration:**

- Embeds: `oneOf`, `anyOf`

Poll choices are embedded rather than referenced, so viewers see options without additional requests.

### NoteProjection

Projects Note objects with collection overrides.

```python
from activitypub.projections import NoteProjection

projection = NoteProjection(note_ref)
```

**Meta configuration:**

- Overrides:
  - `replies` with `CollectionWithFirstPageProjection`
  - `likes` with `CollectionWithTotalProjection`
  - `shares` with `CollectionWithTotalProjection`

Optimizes Note presentation by embedding the first page of replies and showing counts for likes/shares.

### PublicKeyProjection

Minimal projection for embedded public keys.

```python
from activitypub.projections import PublicKeyProjection

projection = PublicKeyProjection(key_ref, parent=actor_projection)
```

**Meta configuration:**

- Omits: `revoked`, `created`, `creator`, `signatureValue`, `signatureAlgorithm`

Only includes essential public key fields. Used by `ActorProjection` when embedding keys.

## Field Serialization

Projections automatically serialize Django fields to expanded JSON-LD based on field type:

### String Fields

CharField and TextField:

```python
{"@value": "the string value"}
```

### Numeric Fields

IntegerField, BigIntegerField, SmallIntegerField:

```python
{"@value": 42, "@type": "http://www.w3.org/2001/XMLSchema#integer"}
```

PositiveIntegerField:

```python
{"@value": 10, "@type": "http://www.w3.org/2001/XMLSchema#nonNegativeInteger"}
```

FloatField:

```python
{"@value": 3.14, "@type": "http://www.w3.org/2001/XMLSchema#double"}
```

DecimalField:

```python
{"@value": "99.99", "@type": "http://www.w3.org/2001/XMLSchema#decimal"}
```

### Temporal Fields

DateTimeField:

```python
{"@value": "2025-01-15T10:30:00Z", "@type": "http://www.w3.org/2001/XMLSchema#dateTime"}
```

DateField:

```python
{"@value": "2025-01-15", "@type": "http://www.w3.org/2001/XMLSchema#date"}
```

TimeField:

```python
{"@value": "10:30:00", "@type": "http://www.w3.org/2001/XMLSchema#time"}
```

### Boolean Fields

BooleanField:

```python
{"@value": true, "@type": "http://www.w3.org/2001/XMLSchema#boolean"}
```

### Reference Fields

ForeignKey to Reference (single):

```python
[{"@id": "https://example.com/resource"}]
```

ReferenceField (many-to-many):

```python
[
    {"@id": "https://example.com/resource1"},
    {"@id": "https://example.com/resource2"}
]
```

### URL Fields

URLField:

```python
{"@value": "https://example.com", "@type": "http://www.w3.org/2001/XMLSchema#anyURI"}
```

### Special: Type Field

The `type` field is serialized as `@type` without wrapping:

```python
{"@type": "Note"}  # Not {"@type": [{"@value": "Note"}]}
```

## Access Control

Control field visibility through `show_<field>()` methods on context models or extra field methods on projections.

### Context Model Methods

```python
class MoodContext(AbstractContextModel):
    mood_notes = models.TextField()
    
    def show_mood_notes(self, scope):
        """Only show notes to the entry author."""
        viewer = scope.get('viewer')
        obj = self.reference.get_by_context(ObjectContext)
        
        if obj and obj.attributed_to.all():
            author = obj.attributed_to.first()
            return viewer and viewer.uri == author.uri
        
        return False
```

The method receives the `scope` dict and returns `True` to include the field or `False` to omit it.

### Projection Extra Methods

```python
class JournalEntryProjection(ReferenceProjection):
    def get_private_data(self):
        viewer = self.scope.get('viewer')
        
        # Check authorization
        if not self._is_authorized(viewer):
            return None  # Omit field
        
        # Return data in expanded format
        return [{"@value": "secret data"}]
```

Return `None` to omit the field from output. Return expanded JSON-LD to include it.

## Context Tracking

Projections automatically track which contexts are used and build appropriate `@context` arrays.

### Seen Contexts

The `seen_contexts` set accumulates context URLs as context models are processed. When compacting, these become the `@context` array.

```python
projection.build()
print(projection.seen_contexts)
# {'https://www.w3.org/ns/activitystreams', 'https://w3id.org/security/v1'}
```

### Extra Context

The `extra_context` dict accumulates additional context definitions not available in standard context documents.

```python
EXTRA_CONTEXT = {
    "sensitive": {"@id": "as:sensitive", "@type": "xsd:boolean"},
    "Hashtag": "as:Hashtag"
}
```

These get merged into the `@context` array when compacting.

### Shared Tracking

When projections are nested (embedding), the child shares `seen_contexts` and `extra_context` with the parent. This ensures the root projection has complete context information.

```python
parent = ActorProjection(actor_ref)
child = PublicKeyProjection(key_ref, parent=parent)

# child.seen_contexts is parent.seen_contexts (same object)
# child.extra_context is parent.extra_context (same object)
```

## Embedding Behavior

When embedding references, projections have special handling for blank nodes (skolemized references).

### Named Nodes

Named nodes (references with proper URIs) are embedded with `@id`:

```python
{
    "@id": "https://example.com/key/1",
    "publicKeyPem": "-----BEGIN PUBLIC KEY-----..."
}
```

### Blank Nodes

Blank nodes (skolemized references starting with `.well-known/skolem/`) omit `@id`:

```python
{
    "publicKeyPem": "-----BEGIN PUBLIC KEY-----...",
    "owner": "https://example.com/users/alice"
}
```

This creates proper blank node representation in JSON-LD. The projection automatically detects and handles this based on `reference.is_named_node`.

## Compaction

The `get_compacted()` method builds the `@context` array and compacts the expanded document using pyld.

### Context Array Construction

1. ActivityStreams context (if used) appears first
2. Other seen contexts in sorted order
3. Extra context dict (if present) appears last

```python
{
    "@context": [
        "https://www.w3.org/ns/activitystreams",
        "https://w3id.org/security/v1",
        {"sensitive": {"@id": "as:sensitive", "@type": "xsd:boolean"}}
    ],
    ...
}
```

### Single Context Optimization

If only one context is used, it appears as a string rather than an array:

```python
{
    "@context": "https://www.w3.org/ns/activitystreams",
    ...
}
```

### Nested Projections

Only the root projection includes `@context`. Nested projections (embedded objects) omit it since context is established at the root level.

## Best Practices

**Use `omit` for sensitive fields.** Always omit BCC recipients, private keys, and other sensitive data:

```python
class Meta:
    omit = (AS2.bcc, AS2.bto, SECv1.privateKeyPem)
```

**Use `overrides` for selective embedding.** Different related fields often need different projection strategies:

```python
class Meta:
    overrides = {
        AS2.replies: CollectionWithFirstPageProjection,  # First page
        AS2.likes: CollectionWithTotalProjection,        # Just count
    }
```

**Implement access control in extra methods.** Keep authorization logic in projections, not context models:

```python
def get_private_field(self):
    if not self._is_authorized(self.scope.get('viewer')):
        return None
    return [{"@value": self._get_private_data()}]
```

**Use `@use_context` for vocabulary extensions.** Register contexts needed by computed fields:

```python
@use_context("https://example.com/context.jsonld")
def get_custom_field(self):
    ...
```

**Test with different viewers.** Verify access control works for authorized, unauthorized, and anonymous viewers:

```python
# Test as owner
projection = MyProjection(ref, scope={'viewer': owner_ref})
assert 'privateProp' in projection.get_compacted()

# Test as stranger
projection = MyProjection(ref, scope={'viewer': other_ref})
assert 'privateProp' not in projection.get_compacted()

# Test anonymous
projection = MyProjection(ref, scope={'viewer': None})
assert 'privateProp' not in projection.get_compacted()
```

**Extend built-in projections.** Inherit from existing projections rather than starting from scratch:

```python
class MyNoteProjection(NoteProjection):
    def get_custom_field(self):
        ...
    
    class Meta(NoteProjection.Meta):
        extra = {
            **NoteProjection.Meta.extra,
            "get_custom_field": CUSTOM.customField
        }
```

This inherits the existing configuration and adds your customizations.
