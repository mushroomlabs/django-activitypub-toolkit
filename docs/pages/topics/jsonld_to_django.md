---
title: From JSON-LD to Django Models
---

The transformation from JSON-LD documents to Django models—and back
again—is central to how Django ActivityPub Toolkit operates.
Understanding this bidirectional flow helps you work effectively with
federated data and design applications that integrate cleanly with the
toolkit's architecture.

## Receiving a JSON-LD Document

When your server receives a JSON-LD document, whether through an inbox
POST or by fetching a remote resource, the toolkit processes it
through a defined pipeline. The document arrives as a Python
dictionary representing JSON data. It must have an `id` field
containing the URI that identifies the resource.

The first step creates or retrieves a `LinkedDataDocument` instance.
This model stores the raw JSON data and associates it with a Reference
for the document's URI. The document is persisted before any parsing
happens, ensuring you retain the original data even if processing
fails.

```python
from activitypub.models import LinkedDataDocument

document_data = {
    "id": "https://remote.example/posts/123",
    "type": "Note",
    "content": "Hello from the Fediverse",
    "attributedTo": "https://remote.example/users/alice"
}

doc = LinkedDataDocument.make(document_data)
```

The `make()` method handles the Reference creation internally. If a
document with that URI already exists, it updates the stored data
rather than creating a duplicate. This idempotent behavior means you
can safely reprocess documents without accumulating redundant records.

## Parsing the RDF Graph

The stored document must be transformed into an RDF graph so the
toolkit can extract structured data. The `load()` method triggers this
transformation using the rdflib library. It parses the JSON-LD into a
graph of triples, each representing a subject-predicate-object
statement.

```python
doc.load()
```

This single method call orchestrates several complex operations.
First, it converts the JSON-LD document into an RDF graph. The graph
represents every statement in the document as triples. A note's
content becomes a triple with the note's URI as subject, the content
predicate as relation, and the content text as object.

The toolkit then handles blank nodes—unnamed resources that JSON-LD
uses for embedding. Blank nodes receive skolemized URIs, converting
them to proper Reference instances. This ensures every resource in the
graph has a stable identifier that can be referenced and queried.

After processing blank nodes, the toolkit extracts all unique subject
URIs from the graph and creates Reference instances for each. These
references serve as anchors that context models attach to. A single
document might introduce multiple references if it includes embedded
objects or arrays of resources.

## Populating Context Models

With the graph parsed and references created, the toolkit walks
through each reference and determines which context models should
extract data from it. This happens through the autoloaded context
models configured in your settings.

For each reference, the toolkit asks each context model whether it
should handle that reference. The `should_handle_reference()` method
examines the graph to see if relevant predicates exist.
`ObjectContext` might look for an `as:content` predicate.
`ActorContext` might look for `as:inbox` and `as:outbox` predicates.

Context models that recognize the reference call `load_from_graph()`
to extract their data. This method walks through the model's
`LINKED_DATA_FIELDS` mapping, which associates Django field names with
RDF predicates.

```python
# Simplified extraction logic
class ObjectContext(AbstractContextModel):
    LINKED_DATA_FIELDS = {
        'content': AS2.content,
        'name': AS2.name,
        'attributed_to': AS2.attributedTo,
        'published': AS2.published,
    }
```

For each field, the context model queries the graph for triples with
that predicate. Scalar values like strings and dates are extracted
directly. Reference fields are resolved to Reference instances. The
extracted data populates the context model through Django's ORM,
creating or updating the record.

The separation between field types matters. String fields extract
literal values. ForeignKey fields extract URIs and convert them to
Reference instances. ReferenceField (many-to-many relations) extract
multiple URIs and create a set of related references.

This extraction is purely mechanical. The context model doesn't
interpret the data or enforce complex validation. It serves as a
structured storage mechanism for data that was already validated by
its source. Applications implement their own validation when using
this data.

## Multiple Contexts on One Reference

A reference can have multiple context models attached. An actor
reference might have both `ActorContext` (for ActivityStreams
properties) and `SecV1Context` (for cryptographic keys). A note might
have both `ObjectContext` (standard properties) and a custom context
for application-specific extensions.

Each context model extracts only its own predicates. `ActorContext`
ignores security predicates. `SecV1Context` ignores ActivityStreams
predicates. This isolation means vocabularies can coexist without
interference. Extensions don't break core functionality because they
occupy separate context models.

When the graph contains predicates that no context model recognizes,
those predicates are ignored during the current processing. If you
later add a context model that handles those predicates, you would
need to reprocess the document. The toolkit doesn't automatically
reprocess old documents when you add new context models.

This design trades completeness for predictability. You control
exactly what data gets extracted by controlling which context models
are registered. Unrecognized data doesn't cause errors; it simply
remains in the raw document.

## The Opposite Direction: Serialization

Creating JSON-LD documents from Django models reverses the process.
When your server needs to serve a resource to a remote requester, it
serializes the relevant context models back into JSON-LD.

The `LinkedDataSerializer` handles this transformation. Given a
reference, it walks through all context models attached to that
reference and merges their data into a single expanded JSON-LD
document.

```python
from activitypub.serializers import LinkedDataSerializer

ref = Reference.objects.get(uri='https://myserver.com/posts/456')
serializer = LinkedDataSerializer(
    instance=ref,
    context={'viewer': viewer_ref, 'request': request}
)
expanded_data = serializer.data
```

Each context model uses its `LINKED_DATA_FIELDS` mapping in reverse.
Django field names map back to predicate URIs. String values become
literal objects. References become URI objects with `@id` keys. The
result is an expanded JSON-LD document where every key is a full
predicate URI.

The serializer respects access control through optional methods. If a
context model's serializer defines a `show_content()` method, that
method determines whether the content field appears in the output.
This allows fine-grained control over what data gets exposed to
different viewers without changing the underlying context models.

## Framing for Structure

Expanded JSON-LD is precise but verbose. Applications typically serve
compacted JSON-LD where keys use short names and the `@context`
provides namespace mappings. Before compaction, framing provides
control over document structure.

The toolkit's framing system solves a fundamental challenge: the same
resource needs different representations depending on context. An
actor embedded in an activity should show minimal information. The
same actor, when requested directly, should include full details with
collection references. A collection should embed its first page when
requested directly but only show a reference when embedded elsewhere.

Consider a note with a replies collection. When you fetch the note
directly:

```json
{
  "@id": "https://example.com/notes/123",
  "type": "Note",
  "content": "Hello World",
  "replies": "https://example.com/notes/123/replies"
}
```

The replies collection appears as a simple reference. But when you
fetch the collection directly, it embeds its first page:

```json
{
  "@id": "https://example.com/notes/123/replies",
  "type": "OrderedCollection",
  "totalItems": 42,
  "first": {
    "@id": "https://example.com/notes/123/replies?page=1",
    "type": "OrderedCollectionPage",
    "items": ["https://example.com/notes/456", ...]
  }
}
```

This context-aware framing happens automatically. The toolkit selects
the appropriate frame based on which context model has data for the
reference. Frames define rules that apply differently based on whether
the resource is the main subject or embedded within another resource.

The `LinkedDataFrame` class provides the core framing logic:

```python
from activitypub.frames import LinkedDataFrame, FramingRule
from activitypub.schemas import AS2

class ObjectFrame(LinkedDataFrame):
    context_model_class = ObjectContext  # Ties frame to model
    priority = 0  # Used when multiple frames could apply

    rules = {
        str(AS2.replies): [
            # Show collection reference when note is main subject
            FramingRule(
                str(AS2.replies),
                action=FramingRule.REFERENCE,
                when=lambda ctx: ctx.is_main_subject
            ),
            # Omit collection when note is embedded elsewhere
            FramingRule(
                str(AS2.replies),
                action=FramingRule.OMIT,
                when=lambda ctx: ctx.is_embedded
            ),
        ],
    }
```

Frames register with the `FrameRegistry`, which automatically selects
the right frame when serializing. Views and tasks use automatic frame
selection:

```python
from activitypub.frames import FrameRegistry
from activitypub.serializers import LinkedDataSerializer

# Automatic frame selection based on context model
serializer = LinkedDataSerializer(instance=reference, context={'viewer': viewer})
frame = FrameRegistry.auto_frame(serializer)
document = frame.to_framed_document()
```

Frames support three actions for each predicate:

- **OMIT** - Exclude the predicate entirely
- **REFERENCE** - Include as `{"@id": "..."}` only
- **EMBED** - Fully serialize the referenced object

Rules can include conditions that check the framing context. The
context tracks whether the resource is the main subject (depth 0),
embedded (depth > 0), and the current nesting level. This allows
sophisticated behavior like "embed up to depth 2, then show only
references."

The toolkit includes frames for common ActivityPub patterns:
`ActorFrame` for actors, `CollectionFrame` for collections,
`QuestionFrame` for polls with embedded choices, and `ActivityFrame`
for activities. Custom frames extend these base classes and register
with the system.

After framing shapes the document structure, compaction makes it
readable. The serializer builds a `@context` array from the relevant
context models. `ObjectContext` contributes the ActivityStreams
context. `SecV1Context` contributes the security context. Compaction
replaces full predicate URIs with short names, producing readable
JSON-LD that follows protocol conventions.

## Access Control During Serialization

Serialization happens in the context of a request from a specific
viewer. The viewer might be authenticated (a known actor) or
anonymous. The serializer passes viewer information to context model
serializers, which can use it to filter data.

Consider an actor's followers collection. The full list should only be
visible to the actor themselves. Other viewers might see a count but
not the actual list. The context serializer implements this through a
method:

```python
class ActorContextSerializer(ContextModelSerializer):
    def show_followers(self, instance, viewer):
        # Only show followers to the actor themselves
        return viewer and viewer.uri == instance.reference.uri
```

When the serializer processes the actor context, it checks this method
before including the followers field. If the method returns False, the
field is omitted entirely. The JSON-LD document adapts to the viewer's
permissions without requiring separate models or complex query logic.

This pattern extends to any field. Application-specific access rules
live in serializer methods rather than in the context models
themselves. Context models remain focused on data storage and
extraction. Serializers handle presentation and access control.

## Custom Serializers

Applications can register custom serializers for specific context
models. If the default `ContextModelSerializer` doesn't provide enough
control, create a subclass that implements your requirements and
register it in settings.

```python
FEDERATION = {
    'CUSTOM_SERIALIZERS': {
        ObjectContext: 'myapp.serializers.CustomObjectSerializer',
    }
}
```

The custom serializer receives the context model instance and produces
expanded JSON-LD. It has full control over what fields to include, how
to format values, and what access control to apply. The
`LinkedDataSerializer` uses the custom serializer when processing that
context type.

This extension point lets you adapt serialization without modifying
toolkit code. Add computed fields, transform data, integrate with
external services—anything you can express in a serializer method.

## Performance Considerations

The JSON-LD to model pipeline involves several expensive operations.
Parsing RDF graphs is slower than parsing plain JSON. Walking through
context models and extracting data requires multiple database queries.
These costs are why the toolkit parses once and then works with
relational data.

After processing a document, subsequent access goes through Django's
ORM. Fetching a note's content queries the `ObjectContext` table
directly. No graph parsing happens. No JSON-LD processing happens. The
data lives in a relational form optimized for queries.

This design assumes that reading data is far more common than writing
data. You parse each remote document once when it arrives. You might
serialize local data occasionally when responding to remote requests.
But you query and filter data constantly when building timelines,
searching, or displaying profiles.

The tradeoff is that the initial processing has significant overhead.
For high-volume inboxes, consider processing notifications
asynchronously through background tasks. The inbox view accepts the
document, creates the notification record, and returns immediately. A
worker process handles the parsing and context model population.

Serialization performance matters less because it typically happens
for single resources rather than bulk operations. Serving an actor
profile or a post serializes one reference with its contexts. The
overhead is acceptable for request-response cycles.

## When Things Go Wrong

Not all JSON-LD documents are well-formed. Remote servers might send
invalid data, missing required fields, or references to nonexistent
resources. The toolkit handles common failure modes gracefully.

If a document lacks an `id` field, `LinkedDataDocument.make()` raises
a ValueError. The document cannot be stored because there's no URI to
associate it with. The calling code should catch this and respond
appropriately, typically by rejecting the request.

If parsing into an RDF graph fails, `load()` raises a ValueError. This
might happen with malformed JSON-LD or documents that violate JSON-LD
syntax rules. The document record persists with its raw data, allowing
manual inspection, but no context models get populated.

If `should_handle_reference()` determines that a reference doesn't
match a context model's criteria, that context model simply doesn't
process the reference. Other context models might still process it. A
resource that looks like an Actor but lacks required fields might fail
to create an `ActorContext` but successfully create a basic
`ObjectContext`.

These failures are localized. One context model's failure doesn't
prevent other context models from processing their data. One
document's failure doesn't affect other documents. The system degrades
gracefully, storing what it can and skipping what it can't interpret.

## The Round-Trip Guarantee

An important property of this architecture is round-trip consistency
for local data. If you create a context model with certain field
values, serialize it to JSON-LD, parse that JSON-LD back into a graph,
and extract context models from the graph, you should get equivalent
data.

This guarantee doesn't hold for remote data. Remote servers might use
different vocabularies, structure data differently, or omit fields
that your application considers essential. Round-trip consistency
applies only to data you control.

For local data, the guarantee means you can confidently serialize your
models for federation. The recipient parses your JSON-LD using their
toolkit. Even if they use different application models or business
logic, they can extract and store your ActivityStreams data. Your
note's content, attribution, and publication date survive the journey
to their database.

This consistency is why the `LINKED_DATA_FIELDS` mapping is central to
the design. It defines the contract between your Django models and the
RDF graph. As long as you maintain that mapping correctly,
serialization and parsing remain inverse operations.

## Designing Your Context Models

When building applications on the toolkit, you might create custom
context models for specialized vocabularies. The JSON-LD to model
pipeline will process these just like the built-in context models.

Design your `LINKED_DATA_FIELDS` mapping carefully. Each field name
should map to exactly one predicate. The field type should match the
predicate's expected range. String predicates map to CharField or
TextField. URI predicates map to ForeignKey or ReferenceField. Date
predicates map to DateTimeField.

Implement `should_handle_reference()` to identify when your context
applies. Check for the presence of predicates that only your
vocabulary uses. Don't claim references that other context models
might handle better. When in doubt, be conservative—it's better to
skip a reference than to populate incorrect data.

Remember that your context model coexists with others on the same
reference. An object might have both ActivityStreams properties and
your custom properties. Design for composition, not replacement. Your
context model adds information; it doesn't replace the standard
contexts.

## Integration Points

Your application models integrate at the serialization and
deserialization boundaries. When processing incoming activities, you
access context models to read vocabulary-specific data and then create
or update your application models.

When serving resources, your application models provide the data that
gets written to context models, which then get serialized to JSON-LD.
You're responsible for keeping your application models synchronized
with the relevant context models.

This bidirectional flow—JSON-LD to context models to application
models, and back again—is where your business logic lives. The toolkit
handles the vocabulary translation. You handle the application
semantics. The separation keeps concerns cleanly divided and makes the
system easier to reason about.
