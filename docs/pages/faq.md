---
hide:
  - navigation
  - toc
---


# Frequently Asked Questions

## Installation and Setup

### What are the minimum Django and Python version requirements?

The toolkit requires:
- Python 3.9 or higher
- Django 4.2.23 or higher

It supports Django versions 4.2, 5.0, and 5.1.

## Architecture and Concepts

### What's the difference between References, Context Models, and my Django models?

- **References**: URI-based pointers to resources that work uniformly
  for local and remote content
- **Context Models**: Django models that store vocabulary-specific
  data (ActivityStreams, custom extensions) attached to references
- **Your Django models**: Application-specific business logic models
  that link to references

### Why does the toolkit use a reference-based architecture instead of storing everything directly?

The reference-based architecture enables:

- Uniform handling of local and remote resources
- Efficient storage by avoiding duplicate data
- Lazy resolution of remote content
- Clean separation between application logic and federation concerns

### How do I choose which context models to use for my application?

Use the standard ActivityStreams context models for basic federation:

- `ObjectContext` for content (notes, articles, etc.)
- `ActorContext` for users/actors
- `ActivityContext` for actions (create, like, follow, etc.)
- `CollectionContext` for lists and feeds

Add custom context models for specialized vocabularies or platform
extensions.

### What's the difference between push-based and pull-based federation?

- **Push-based**: Activities are delivered directly to recipient
  inboxes via HTTP POST
- **Pull-based**: Activities are stored in collections (like outboxes)
  that remote servers fetch on demand

The toolkit emphasizes pull-based federation for better scalability
and control over network requests.

## Integration with Existing Apps

## Federation Features

### What ActivityPub features does the toolkit support?

The toolkit supports:

- ActivityPub protocol implementation
- ActivityStreams 2.0 vocabulary
- JSON-LD serialization
- HTTP Signatures for authentication
- WebFinger for account discovery
- Collection pagination
- Inbox/outbox processing
- Activity handlers for custom logic

## Security and Authentication

### How does the toolkit handle HTTP signatures and authentication?

The toolkit automatically:

- Verifies HTTP signatures on incoming requests using actor public
  keys
- Signs outgoing requests with local actor private keys
- Supports multiple signature algorithms
- Caches public keys for performance

### What about authorization - how do I control who can interact with my content?

Implement authorization in your activity handlers:

- Check domain blocks
- Verify relationships (followers-only content)
- Validate content policies
- Rate limiting and spam detection

The toolkit provides the authentication foundation; your application
implements authorization policies.

### Does the toolkit support multi-tenant setups with separate keys per actor?

Yes, each actor can have its own cryptographic keypair stored in
`SecV1Context`. This provides better isolation and enables per-actor
key rotation.

## Performance and Scaling

### How does the toolkit handle large numbers of remote users/activities?

- Lazy resolution: Remote content is only fetched when needed
- Caching: Resolved content is cached with configurable TTL
- Rate limiting: Prevents excessive remote fetches
- Efficient queries: Context models use standard Django ORM
- Background processing: Activity processing happens asynchronously

### What's the performance impact on my Django application?

The toolkit is designed for good performance:

- Minimal overhead for local operations
- Efficient database queries using Django ORM
- Configurable caching and rate limiting
- Asynchronous processing for federation tasks

Performance depends on your usage patterns and federation volume.

### How much storage space do references and context models require?

Storage requirements depend on:
- Number of local and remote resources you interact with
- Amount of cached remote content
- Size of your collections (followers, activities, etc.)

References are lightweight (URI + metadata). Context models store
parsed JSON-LD data.

### Can I run multiple domains from one Django installation?

Yes, the toolkit supports multi-domain hosting. Configure multiple
`Domain` records and associate different actors/content with different
domains.



## Compatibility

### Which Fediverse software has been tested with this toolkit?

The toolkit is tested primarily against implementations of:

- Mastodon
- GoToSocial
- Takahe
- Lemmy

It should work however with any server that can send valid JSON-LD
document

### Does the toolkit support ActivityPub Client-to-Server (C2S) API?

Yes, the generic server tutorial demonstrates C2S support, allowing
multiple clients to use the same server for different purposes.

### Can I use this toolkit with existing ActivityPub servers?

Yes, the toolkit implements standard ActivityPub protocols and should
interoperate with any compliant server.

### What about custom vocabularies or extensions?

Create custom context models by extending `AbstractContextModel`.
Define the vocabulary namespace, field mappings, and processing logic.
Register custom models in your federation settings.
