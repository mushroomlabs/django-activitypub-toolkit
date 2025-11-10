---
title: Understanding Linked Data and RDF
---

The power of the Fediverse comes from its foundation in Linked Data principles. While you can build ActivityPub applications without deeply understanding these concepts, grasping the fundamentals will help you design more flexible and interoperable systems.

## The Web as a Graph

Traditional web applications treat data as isolated records in databases. Each application maintains its own copy of user profiles, posts, and relationships. When applications need to share data, they typically use custom APIs that map their internal database structures to JSON responses.

Linked Data takes a different approach. Instead of thinking about isolated records, it models all information as a directed graph of statements. Each statement is a triple consisting of a subject, predicate, and object. This simple structure can express any relationship between resources.

Consider a social media post. In a traditional database, you might have a `posts` table with columns for `id`, `author_id`, `content`, and `published_at`. In Linked Data, the same information becomes a set of statements:

```
<https://example.com/posts/123> <http://purl.org/dc/terms/creator> <https://example.com/users/alice>
<https://example.com/posts/123> <https://www.w3.org/ns/activitystreams#content> "Just learned about Linked Data"
<https://example.com/posts/123> <https://www.w3.org/ns/activitystreams#published> "2025-01-15T10:30:00Z"
```

Each line is a statement. The subject identifies the resource being described. The predicate specifies what attribute or relationship is being expressed. The object provides the value or points to another resource.

This graph structure has significant advantages. Resources can be extended with new predicates without breaking existing software. Multiple applications can describe the same resource using different vocabularies. Most importantly, resources from different servers can reference each other directly, creating a unified graph that spans the entire network.

## RDF: The Resource Description Framework

RDF formalizes the graph model into a standard that machines can process reliably. It specifies how to identify resources, how to represent different types of values, and how to combine statements from multiple sources.

Resources in RDF are identified by IRIs (Internationalized Resource Identifiers), which are essentially URLs that uniquely identify things. When you see `https://www.w3.org/ns/activitystreams#content`, that's an IRI identifying the concept of "content" in the ActivityStreams vocabulary.

RDF supports literals for simple values like strings, numbers, and dates. These are typed according to XML Schema datatypes, so "2025-01-15T10:30:00Z" is understood as a datetime value, not just a string.

The graph model is agnostic about serialization format. The same set of triples can be expressed in Turtle, N-Triples, RDF/XML, or JSON-LD. Different formats serve different purposes, but they all represent the same underlying graph.

## JSON-LD: Linked Data for JSON

ActivityPub uses JSON-LD as its serialization format because it bridges the gap between traditional JSON APIs and Linked Data principles. A JSON-LD document looks like ordinary JSON but includes special keywords that give it precise semantic meaning.

Here's the same post expressed in JSON-LD:

```json
{
  "@context": "https://www.w3.org/ns/activitystreams",
  "id": "https://example.com/posts/123",
  "type": "Note",
  "attributedTo": "https://example.com/users/alice",
  "content": "Just learned about Linked Data",
  "published": "2025-01-15T10:30:00Z"
}
```

The `@context` maps short property names to full IRIs. When you write `"content"`, the context expands it to `"https://www.w3.org/ns/activitystreams#content"`. This makes JSON-LD documents readable while maintaining semantic precision.

The same document can be expressed in expanded form, where all IRIs are explicit:

```json
{
  "@id": "https://example.com/posts/123",
  "@type": ["https://www.w3.org/ns/activitystreams#Note"],
  "https://www.w3.org/ns/activitystreams#attributedTo": [
    {"@id": "https://example.com/users/alice"}
  ],
  "https://www.w3.org/ns/activitystreams#content": [
    {"@value": "Just learned about Linked Data"}
  ],
  "https://www.w3.org/ns/activitystreams#published": [
    {
      "@value": "2025-01-15T10:30:00Z",
      "@type": "http://www.w3.org/2001/XMLSchema#dateTime"
    }
  ]
}
```

This expanded form reveals the underlying RDF structure. Every property is fully qualified. Values are wrapped in objects that specify whether they're IRIs or literals. Properties are arrays because RDF allows multiple values for the same predicate.

JSON-LD processors can convert between compact and expanded forms automatically. They can also convert JSON-LD to and from other RDF formats. This flexibility means you can work with readable JSON while retaining all the benefits of Linked Data.

## Vocabularies and Interoperability

A vocabulary defines the predicates and types used in a domain. ActivityStreams 2.0 is the core vocabulary for social networking, defining types like `Note`, `Person`, and `Follow`, along with predicates like `actor`, `object`, and `published`.

Different applications can extend the base vocabulary with their own terms. Mastodon adds `featured` collections and `sensitive` flags. Lemmy defines `stickied` posts. These extensions don't conflict because each term has a unique IRI.

When an application encounters unfamiliar predicates, it can simply ignore them or store them for later processing. This extensibility is fundamental to how the Fediverse evolves. New features can be deployed incrementally without requiring coordinated upgrades across all servers.

## Why This Matters for ActivityPub

ActivityPub servers exchange JSON-LD documents representing activities, actors, and objects. Each server maintains its own database but shares a subset of that data through a common graph model.

When a user on your server follows someone on a remote server, both servers store information about that relationship using their own data structures. But when they communicate, they use the shared ActivityStreams vocabulary to express that relationship in a way both can understand.

This separation between internal representation and external protocol is what Django ActivityPub Toolkit leverages. You model your application's data using Django models optimized for your use case. The toolkit handles translating between those models and the JSON-LD documents that ActivityPub requires.

Understanding the graph model helps you reason about what data exists in the Fediverse, how it relates to your application's data, and what operations make sense when building on top of this shared infrastructure.
