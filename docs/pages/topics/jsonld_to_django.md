---
title: Parsing JSON-LD Documents
---

The transformation from JSON-LD documents into Django models is central to how Django ActivityPub Toolkit processes incoming federated data. Understanding this parsing flow helps you work effectively with remote resources and design applications that integrate cleanly with the toolkit's architecture.

## Receiving a JSON-LD Document

When your server receives a JSON-LD document, whether through an inbox POST or by fetching a remote resource, the toolkit processes it through a defined pipeline. The document arrives as a Python dictionary representing JSON data. It must have an `id` field containing the URI that identifies the resource.

The first step creates or retrieves a `LinkedDataDocument` instance. This model stores the raw JSON data and associates it with a Reference for the document's URI. The document is persisted before any parsing happens, ensuring you retain the original data even if processing fails.

```python
from activitypub.core.models import LinkedDataDocument

document_data = {
    "id": "https://remote.example/posts/123",
    "type": "Note",
    "content": "Hello from the Fediverse",
    "attributedTo": "https://remote.example/users/alice"
}

doc = LinkedDataDocument.make(document_data)
    # Load the document, passing the source Reference that performed the request
    # (Inbox: remote actor; Outbox: local actor). This triggers sanitisation,
    # validation, and finally type‑matching.
    doc.load(sender)

```

This single method call orchestrates several complex operations. First, it converts the JSON-LD document into an RDF graph. The graph represents every statement in the document as triples. A note's content becomes a triple with the note's URI as subject, the content predicate as relation, and the content text as object.

The toolkit then handles blank nodes—unnamed resources that JSON-LD uses for embedding. Blank nodes receive skolemized URIs, converting them to proper Reference instances. This ensures every resource in the graph has a stable identifier that can be referenced and queried.

After processing blank nodes, the toolkit extracts all unique subject URIs from the graph and creates Reference instances for each. These references serve as anchors that context models attach to. A single document might introduce multiple references if it includes embedded objects or arrays of resources.

## Populating Context Models

With the graph parsed and references created, the toolkit walks through each reference and determines which context models should extract data from it. This happens through the autoloaded context models configured in your settings.

For each reference, the toolkit asks each context model whether it should handle that reference. The `should_handle_reference()` method examines the graph to see if relevant predicates exist and receives the `source` reference that initiated the load, enabling authority checks.

Context models that recognize the reference call `load_from_graph()` to extract their data. This method walks through the model's `LINKED_DATA_FIELDS` mapping, which associates Django field names with RDF predicates.

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

For each field, the context model queries the graph for triples with that predicate. Scalar values like strings and dates are extracted directly. Reference fields are resolved to Reference instances. The extracted data populates the context model through Django's ORM, creating or updating the record.

The separation between field types matters. String fields extract literal values. ForeignKey fields extract URIs and convert them to Reference instances. ReferenceField (many-to-many relations) extract multiple URIs and create a set of related references.

This extraction is purely mechanical. The context model doesn't interpret the data or enforce complex validation. It serves as a structured storage mechanism for data that was already validated by its source. Applications implement their own validation when using this data.

## Multiple Contexts on One Reference

A reference can have multiple context models attached. An actor reference might have both `ActorContext` (for ActivityStreams properties) and `SecV1Context` (for cryptographic keys). A note might have both `ObjectContext` (standard properties) and a custom context for application-specific extensions.

Each context model extracts only its own predicates. `ActorContext` ignores security predicates. `SecV1Context` ignores ActivityStreams predicates. This isolation means vocabularies can coexist without interference. Extensions don't break core functionality because they occupy separate context models.

When the graph contains predicates that no context model recognizes, those predicates are ignored during the current processing. If you later add a context model that handles those predicates, you would need to reprocess the document. The toolkit doesn't automatically reprocess old documents when you add new context models.

This design trades completeness for predictability. You control exactly what data gets extracted by controlling which context models are registered. Unrecognized data doesn't cause errors; it simply remains in the raw document.

## Performance Considerations

The JSON-LD to model pipeline involves several expensive operations. Parsing RDF graphs is slower than parsing plain JSON. Walking through context models and extracting data requires multiple database queries. These costs are why the toolkit parses once and then works with relational data.

After processing a document, subsequent access goes through Django's ORM. Fetching a note's content queries the `ObjectContext` table directly. No graph parsing happens. No JSON-LD processing happens. The data lives in a relational form optimized for queries.

This design assumes that reading data is far more common than writing data. You parse each remote document once when it arrives. But you query and filter data constantly when building timelines, searching, or displaying profiles.

The tradeoff is that the initial processing has significant overhead. For high-volume inboxes, consider processing notifications asynchronously through background tasks. The inbox view accepts the document, creates the notification record, and returns immediately. A worker process handles the parsing and context model population.

### Error handling

When validation fails the toolkit raises ``DocumentValidationError``.  Views should catch this exception and return the appropriate HTTP status:

```python
from activitypub.core.models import DocumentValidationError

def inbox_view(request):
    try:
        # …parse and load the document, passing the sender Reference…
        doc.load(sender)
    except DocumentValidationError as exc:
        # S2S: always return 202 Accepted; the error is logged internally
        return HttpResponse(status=202)
    # Normal processing continues here …
```

The same pattern is used for outbox handling, but the view should return ``400`` or ``403`` when validation fails because the request originates from a client.


## Security Validation Overview

The toolkit validates incoming JSON‑LD documents using a layered approach:

* **Document loading flow** – `LinkedDataDocument.load(sender)` creates the document, then `Reference.load_context_models(g, source)` calls each context model’s `should_handle_reference(g, reference, source)`. `clean_graph(g, reference, source)` performs skolemisation of blank nodes and local URIs before `load_from_graph` extracts fields.
* **Authority model** – `Reference.has_authority_over(other)` defines when a source can act on a target (blank nodes, self, local vs remote authority). Context models use this to enforce that the actor sending the activity controls any `as:attributedTo` claims.
* **S2S vs C2S** – In server‑to‑server (Inbox) the toolkit accepts the request (`202 Accepted`) but filters out unauthorized data. In client‑to‑server (Outbox) a validation failure results in a rejection (`400/403`).
* **Attack vectors prevented** – actor spoofing, attributedTo impersonation, object ID squatting, and unauthorized update/delete.
* **Validation layers** – view‑level checks (domain block, HTTP signatures), `should_handle_reference` authority checks, `clean_graph` transformations, and business‑logic checks in `Activity.do()`.

These safeguards ensure only well‑formed, authorised data is persisted while allowing graceful handling of malformed activity streams.

## Designing Your Context Models

When building applications on the toolkit, you might create custom context models for specialized vocabularies. The JSON-LD to model pipeline will process these just like the built-in context models.

Design your `LINKED_DATA_FIELDS` mapping carefully. Each field name should map to exactly one predicate. The field type should match the predicate's expected range. String predicates map to CharField or TextField. URI predicates map to ForeignKey or ReferenceField. Date predicates map to DateTimeField.

Implement `should_handle_reference()` to identify when your context applies. Check for the presence of predicates that only your vocabulary uses. Don't claim references that other context models might handle better. When in doubt, be conservative—it's better to skip a reference than to populate incorrect data.

Remember that your context model coexists with others on the same reference. An object might have both ActivityStreams properties and your custom properties. Design for composition, not replacement. Your context model adds information; it doesn't replace the standard contexts.

## Integration Points

Your application models integrate at the deserialization boundary. When processing incoming activities, you access context models to read vocabulary-specific data and then create or update your application models.

The toolkit handles the vocabulary translation from JSON-LD to context models. You handle the application semantics—converting context model data into your domain objects, enforcing business rules, and maintaining application state. The separation keeps concerns cleanly divided and makes the system easier to reason about.
