---
title: Understanding Projections
---

Projections control how your application presents federated data to external viewers. They transform the comprehensive data stored in context models into focused JSON-LD documents tailored to specific use cases and audiences.

## The Presentation Problem

When a remote server requests your actor profile or fetches a post, your application faces several presentation challenges:

**Information overload.** Context models store every field extracted from incoming documents. An actor might have dozens of fields across multiple contexts—basic properties, cryptographic keys, platform extensions, custom vocabularies. Exposing everything creates bloated responses that waste bandwidth and expose implementation details.

**Access control.** Some fields should only be visible to specific viewers. An actor's inbox URL belongs to the owner. Follower lists might be private. Content warnings apply to certain posts. Your presentation layer must enforce these rules consistently.

**Relationship complexity.** Objects reference other objects. An actor has an inbox, outbox, followers collection, following collection. A note has replies, likes, shares. Each reference could be embedded (full object) or referenced (just URI). The choice affects performance and user experience.

**Context dependencies.** Different vocabulary extensions require different JSON-LD contexts. When you embed a public key, you need the Security v1 context. Custom fields need custom contexts. The presentation layer must track which contexts are needed and build the `@context` array correctly.

Projections solve these problems through declarative configuration. You specify what to include, what to omit, what to embed, and how to compute derived fields. The projection system handles the mechanics of building expanded JSON-LD, tracking contexts, and compacting output.

## Separation of Concerns

The toolkit maintains a clear boundary between data storage and data presentation:

**Context models** store comprehensive data extracted from incoming JSON-LD. When you receive an actor document, the context model saves all recognized fields. This preserves the complete information from the source server.

**Projections** present selective data when serving JSON-LD. When a remote server fetches that actor, the projection determines which fields to include. This optimizes the output for the requester's needs.

This separation means you can store everything while showing a subset. Remote servers send you comprehensive actor documents—you extract all the data. When other servers fetch that actor from you, you send them a focused response—just what they need.

The separation also means presentation logic lives independently from storage logic. You can change what you show without altering how you store data. Add a new computed field to your projection without touching context models. Implement viewer-specific access control in projections without complicating storage.

## The Projection Lifecycle

Understanding how projections work requires following a request through the system. When a remote server sends `GET https://yourserver.com/users/alice`, here's what happens:

### Request Handling

The URL routes to a view (typically `LinkedDataModelView` or a subclass). The view extracts the URI from the request path, queries for the corresponding Reference, and calls `get_projection_class(reference)` to determine which projection to use.

The projection selection typically examines the reference's context models. An actor reference (has `ActorContext`) gets `ActorProjection`. A collection reference (has `CollectionContext`) gets `CollectionProjection`. Application-specific types get application-specific projections.

### Projection Building

The view instantiates the projection with the reference and a scope dict containing viewer information and the request object. It calls `build()` to generate the document.

Building happens in phases:

**Context model discovery** - The projection queries for all context models attached to the reference. An actor might have `ActorContext` (ActivityStreams properties), `SecV1Context` (cryptographic keys), and custom context models for extensions.

**Field extraction** - For each context model, the projection walks through `LINKED_DATA_FIELDS` mappings. It queries field values from the context model instance and converts them to expanded JSON-LD format based on field type.

**Rule application** - The projection applies Meta rules. Fields in `omit` are skipped. Fields in `embed` or `overrides` trigger recursive projection of related references. Fields in `extra` call custom methods.

**Access control** - For each field, the projection checks for a `show_<field>()` method on the context model. If present and it returns `False`, the field is excluded entirely.

**Expansion** - All data is formatted as expanded JSON-LD. Keys are full predicate URIs (`https://www.w3.org/ns/activitystreams#name` not `name`). Values have explicit types (`{"@value": "Alice", "@type": "xsd:string"}` not just `"Alice"`).

### Context Tracking

As the projection processes context models and extra fields, it tracks which JSON-LD contexts are needed. When it processes `ActorContext`, it notes that the ActivityStreams context is required. When it embeds a public key, it notes that the Security v1 context is required.

Custom fields can register additional contexts using the `@use_context` decorator. This ensures all necessary vocabularies appear in the final `@context` array.

### Compaction

Once building completes, the view calls `get_compacted()` to produce human-readable JSON-LD. The projection constructs a `@context` array from the tracked contexts and uses pyld to compact the expanded document.

Compaction replaces full predicate URIs with short names (`name` instead of `https://www.w3.org/ns/activitystreams#name`). It removes explicit type annotations where the context defines them. The result is idiomatic JSON-LD that follows ActivityPub conventions.

### Response

The view returns the compacted document in the HTTP response with appropriate `Content-Type` headers. The remote server receives valid JSON-LD representing the requested resource.

## Declarative Configuration

Projections use a `Meta` inner class for declarative configuration. This design pattern separates configuration from behavior and makes projection classes easy to understand at a glance.

### The Fields Allowlist

When you set `Meta.fields`, you're creating an allowlist. Only the specified predicates appear in output:

```python
class MinimalActorProjection(ReferenceProjection):
    class Meta:
        fields = (AS2.name, AS2.preferredUsername, AS2.inbox, AS2.outbox)
```

This projection shows only four actor properties. Everything else—icon, summary, endpoints, followers—is excluded. Use this for lightweight responses where you only need identifying information.

The allowlist is absolute. Even if a context model has data for other fields, they won't appear. The projection only processes the specified predicates.

### The Omit Denylist

When you set `Meta.omit`, you're creating a denylist. All fields except those specified appear in output:

```python
class PublicActorProjection(ReferenceProjection):
    class Meta:
        omit = (AS2.bcc, AS2.bto, SECv1.privateKeyPem)
```

This shows everything except sensitive fields. Use this for public-facing projections where you want comprehensive output with specific exclusions.

The denylist is subtractive. Start with all fields, remove the denylisted ones, show the rest. This handles new fields gracefully—add a field to a context model, and it automatically appears in projections that use `omit`.

### Embedding Strategies

The `embed` and `overrides` options control how related references appear. By default, references serialize as `{"@id": "uri"}`. You retrieve the URI but not the object's data.

Embedding changes this. The related reference is projected recursively and its full data appears inline:

```python
class QuestionProjection(ReferenceProjection):
    class Meta:
        embed = (AS2.oneOf, AS2.anyOf)
```

When you project a Question (poll), the choice options are embedded. Remote servers see the full option data without making additional requests. This improves user experience for polls—the viewer shows all choices immediately.

The `overrides` option allows per-field projection classes:

```python
class NoteProjection(ReferenceProjection):
    class Meta:
        overrides = {
            AS2.replies: CollectionWithFirstPageProjection,
            AS2.likes: CollectionWithTotalProjection,
            AS2.shares: CollectionWithTotalProjection,
        }
```

Replies get the first page embedded (so viewers see recent replies immediately). Likes and shares get just the count (because the full list isn't usually needed). Different fields get different treatment based on their semantics.

### Computed Fields

The `extra` option maps methods to predicates. The method computes a value at projection time:

```python
from activitypub.projections import PublicKeyProjection

class ActorProjection(ReferenceProjection):
    @use_context(SEC_V1_CONTEXT.url)
    def get_public_key(self):
        references = Reference.objects.filter(
            activitypub_secv1context_context__owner=self.reference
        )
        projections = [PublicKeyProjection(reference=ref, parent=self) for ref in references]
        return [p.get_expanded() for p in projections]
    
    class Meta:
        extra = {"get_public_key": SECv1.publicKey}
```

This doesn't read from a context model field. It performs a query, creates child projections, and returns their expanded output. The method has full access to Django's ORM and can implement arbitrarily complex logic.

Computed fields enable denormalization. The public key data exists in `SecV1Context`, but actors need it embedded. The computed field performs the join at projection time.

## Access Control Architecture

Projections implement two patterns for access control: field-level methods on context models and conditional logic in extra field methods.

### Context Model Methods

A context model can define `show_<field>()` methods that receive the scope and return boolean values:

```python
class ActorContext(AbstractContextModel):
    followers = models.OneToOneField(Reference, ...)
    
    def show_followers(self, scope):
        viewer = scope.get('viewer')
        if not viewer:
            return False  # Anonymous can't see
        return viewer.uri == self.reference.uri  # Owner can see
```

The projection automatically checks for these methods during field extraction. If `show_followers()` returns `False`, the `followers` field doesn't appear in output. The projection skips it entirely during building.

This pattern keeps authorization logic with the data. The context model owns the field and defines its visibility rules. The projection respects those rules without knowing their internals.

### Projection Methods

Computed fields can implement their own access control by returning `None`:

```python
class JournalEntryProjection(ReferenceProjection):
    def get_private_notes(self):
        viewer = self.scope.get('viewer')
        obj = self.reference.get_by_context(ObjectContext)
        
        if obj and obj.attributed_to.all():
            author = obj.attributed_to.first()
            if viewer and viewer.uri == author.uri:
                mood = self.reference.get_by_context(MoodContext)
                if mood:
                    return [{"@value": mood.mood_notes}]
        
        return None  # Unauthorized - omit field
```

Returning `None` excludes the field. Returning data includes it. The method has complete control.

This pattern suits computed fields that aggregate data from multiple sources. The projection logic is complex enough that putting it in a context model would be awkward.

### The Scope Dict

Both patterns receive a `scope` dict. The view populates this when creating the projection:

```python
projection = ActorProjection(
    reference=actor_ref,
    scope={
        'viewer': requesting_actor_ref,  # Who's viewing
        'request': request,                # HTTP request object
        'view': self,                      # View instance
    }
)
```

The `viewer` is typically the authenticated actor making the request. For anonymous requests, it's `None`. Access control methods can compare `viewer.uri` to `instance.reference.uri` to determine ownership.

The `request` object provides access to HTTP headers, query parameters, and other request context. Some authorization decisions might depend on request properties beyond just the viewer identity.

## Embedding and Recursion

When a projection embeds a related reference, it creates a child projection and includes its output. This can recurse—the child might embed its own references, creating grandchildren.

### Parent-Child Relationships

Child projections receive a `parent` parameter. This establishes a hierarchy:

```python
parent = ActorProjection(actor_ref)
child = PublicKeyProjection(key_ref, parent=parent)
```

The child shares `seen_contexts` and `extra_context` with its parent. When the child processes a context model, it adds to the parent's context tracking. When the parent compacts, it has complete context information from the entire tree.

This sharing is critical. If child projections tracked contexts independently, the root wouldn't know which contexts its descendants needed. The `@context` array would be incomplete.

### Blank Node Handling

Skolemized references (blank nodes with generated URIs like `/.well-known/skolem/...`) receive special handling during embedding. Named references are embedded with `@id`:

```python
{
    "@id": "https://example.com/keys/1",
    "owner": "https://example.com/users/alice",
    "publicKeyPem": "..."
}
```

Blank nodes are embedded without `@id`:

```python
{
    "owner": "https://example.com/users/alice",
    "publicKeyPem": "..."
}
```

This produces proper JSON-LD blank node representation. The projection detects blank nodes via `reference.is_named_node` and omits `@id` accordingly.

### Preventing Infinite Recursion

Projections don't implement automatic recursion limiting. If you configure circular embedding (A embeds B embeds A), you'll get infinite recursion errors.

Avoid this through careful design. Collections should not embed their items if items might reference the collection. Actors should not embed their outbox if activities might reference the actor.

Built-in projections avoid these issues. `CollectionWithFirstPageProjection` embeds the first page, but `CollectionPageProjection` doesn't embed parent collections. The hierarchy terminates.

## Context Management

JSON-LD contexts are critical to interoperability. The `@context` array tells remote servers how to interpret property names and value types. Projections must build correct context arrays.

### Automatic Context Discovery

As projections process context models, they examine each model's `CONTEXT` attribute. If present, the context URL is added to `seen_contexts`:

```python
class ActorContext(AbstractContextModel):
    CONTEXT = AS2_CONTEXT  # URLs "https://www.w3.org/ns/activitystreams"
```

The projection processes `ActorContext` and notes that `https://www.w3.org/ns/activitystreams` is required. Multiple context models might reference the same context—the set deduplicates automatically.

### Explicit Context Registration

Computed fields can register contexts via the `@use_context` decorator:

```python
@use_context(SEC_V1_CONTEXT.url)
def get_public_key(self):
    ...
```

The decorator adds `https://w3id.org/security/v1` to `seen_contexts` when the method executes. The final `@context` array includes it.

You can also register custom context definitions:

```python
@use_context({"customProp": "https://example.com/ns#customProp"})
def get_custom_field(self):
    ...
```

The dict is added to `extra_context`. During compaction, it appears in the `@context` array alongside URL contexts.

### Context Array Construction

When compacting, the projection builds the `@context` array following ActivityPub conventions:

1. ActivityStreams context (if used) appears first
2. Other contexts in sorted order
3. Extra context dict (if present) appears last

For a single context, the array is optimized to a string:

```python
{"@context": "https://www.w3.org/ns/activitystreams"}
```

For multiple contexts:

```python
{
    "@context": [
        "https://www.w3.org/ns/activitystreams",
        "https://w3id.org/security/v1",
        {"sensitive": {"@id": "as:sensitive", "@type": "xsd:boolean"}}
    ]
}
```

## Field Serialization

Projections automatically serialize Django field values to expanded JSON-LD based on field type. This happens during field extraction when building the expanded document.

### Scalar Values

String fields (CharField, TextField) become JSON-LD string literals:

```python
{"@value": "the string value"}
```

No type annotation because JSON-LD defaults to string for plain literals.

### Numeric Values

Integer fields become typed literals with XSD types:

```python
{"@value": 42, "@type": "http://www.w3.org/2001/XMLSchema#integer"}
```

The type annotation is explicit because JSON numbers are ambiguous in JSON-LD.

### Temporal Values

DateTime fields become ISO 8601 strings with XSD types:

```python
{"@value": "2025-01-15T10:30:00Z", "@type": "http://www.w3.org/2001/XMLSchema#dateTime"}
```

The ISO format is compatible with ActivityPub's timestamp expectations.

### Reference Values

Foreign keys and ReferenceFields become URI references:

```python
[{"@id": "https://example.com/users/alice"}]
```

Note the array wrapper—JSON-LD requires arrays for multi-valued properties. The projection serializes all field values as arrays for consistency, even single values.

### The Type Field Exception

The `type` field (RDF type) receives special handling. Instead of wrapping in an array with `@value`, it becomes `@type` directly:

```python
{"@type": "Note"}
```

Not:

```python
{"@type": [{"@value": "Note"}]}
```

This special case produces idiomatic JSON-LD. The `@type` keyword expects an IRI or array of IRIs, not a typed literal.

## Performance Characteristics

Projections involve computational work. Understanding the costs helps you optimize performance.

### Building Costs

Building a projection requires:

- Querying context models (typically 1-3 database queries)
- Walking LINKED_DATA_FIELDS mappings (Python dictionary operations)
- Serializing field values (type introspection and formatting)
- For embedded fields, recursive projection building

The dominant cost is database queries. Each context model requires a query. Embedded references require additional queries for their context models.

Optimize by using Django's `select_related()` and `prefetch_related()` when querying the initial reference. This reduces query count for foreign key and many-to-many access.

### Compaction Costs

Compaction uses pyld to transform expanded JSON-LD. This is a pure Python operation with no database access. The cost scales with document size.

For typical ActivityPub documents (actors, notes, activities), compaction takes a few milliseconds. For large collections with many embedded items, it can reach tens of milliseconds.

### Caching Strategies

Projections generate the same output for the same input. For public resources (actors, public posts), the output is deterministic and cacheable.

Consider caching projected output at the view level:

```python
cache_key = f"projection:{reference.uri}:{viewer.uri if viewer else 'anon'}"
cached = cache.get(cache_key)
if cached:
    return Response(cached)

projection = ActorProjection(reference, scope={'viewer': viewer})
data = projection.get_compacted()
cache.set(cache_key, data, timeout=3600)
return Response(data)
```

The cache key includes the viewer because projections might produce different output for different viewers. Cache separately for each viewer or cache only anonymous views.

Invalidate caches when the underlying data changes. A signal handler can clear the cache when context models update.

## Design Patterns

Several patterns emerge when working with projections at scale.

### Projection Inheritance

Extend existing projections rather than creating from scratch:

```python
class ExtendedActorProjection(ActorProjection):
    def get_custom_field(self):
        ...
    
    class Meta(ActorProjection.Meta):
        extra = {
            **ActorProjection.Meta.extra,
            "get_custom_field": CUSTOM.customField
        }
```

This inherits `ActorProjection`'s public key embedding and adds your custom field. The `Meta` inheritance merges the parent's `extra` dict with yours.

### Viewer-Specific Projections

Create projection variants for different viewer contexts:

```python
class OwnerActorProjection(ActorProjection):
    # Shows everything, including private collections
    pass

class PublicActorProjection(ActorProjection):
    class Meta(ActorProjection.Meta):
        omit = ActorProjection.Meta.omit + (AS2.inbox, AS2.followers, AS2.following)
```

Select in the view based on viewer:

```python
def get_projection_class(self, reference):
    viewer = self.request.scope.get('viewer')
    if viewer and viewer.uri == reference.uri:
        return OwnerActorProjection
    return PublicActorProjection
```

This provides coarse-grained access control at the projection level. Combine with field-level control for fine-grained rules.

### Minimal Projections

Create lightweight projections for embedded contexts:

```python
class EmbeddedActorProjection(ReferenceProjection):
    class Meta:
        fields = (AS2.name, AS2.preferredUsername, AS2.icon)
```

Use these in overrides to prevent bloat:

```python
class NoteProjection(ReferenceProjection):
    class Meta:
        overrides = {
            AS2.attributedTo: EmbeddedActorProjection,  # Just name and icon
        }
```

Notes show author information without embedding the entire actor document.

## Integration with Views

Projections integrate with Django REST Framework views through the `LinkedDataModelView` base class.

The view provides `get_projection_class(reference)` which subclasses override to select projections. The default implementation returns `ReferenceProjection`. The `ActivityPubObjectDetailView` subclass implements smart selection based on context types.

When you create application-specific views, override `get_projection_class()` to return application-specific projections:

```python
class JournalEntryView(LinkedDataModelView):
    def get_projection_class(self, reference):
        if hasattr(reference, 'journal_entry'):
            return JournalEntryProjection
        return super().get_projection_class(reference)
```

The view handles the projection lifecycle—instantiation with scope, building, compaction, and response serialization. Your projection focuses on configuration.

## Summary

Projections separate data presentation from data storage. Context models store comprehensive data from incoming JSON-LD. Projections present selective data when serving JSON-LD.

The projection lifecycle involves discovery (finding context models), extraction (reading field values), rule application (omit/embed/overrides/extra), access control (show_ methods), and compaction (producing readable JSON-LD).

Configuration happens declaratively through the Meta class. You specify what to include, what to omit, what to embed, and what to compute. The projection system handles the mechanics.

Access control happens through context model methods and projection methods. Both receive viewer context and can conditionally include or exclude fields.

Embedding creates hierarchies. Child projections share context tracking with parents. The root projection compacts with complete context information.

The design prioritizes correctness over performance. Projections generate correct JSON-LD with proper contexts. Optimize performance through caching and query optimization rather than compromising correctness.
