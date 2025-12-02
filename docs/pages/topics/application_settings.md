---
title: Configuration and Customization
---

Django ActivityPub Toolkit provides extensive configuration options
that control how your application integrates with the Fediverse.
Understanding these settings helps you adapt the toolkit to your
specific requirements while maintaining compatibility with the broader
ecosystem.

## Configuration Structure

All toolkit settings live under a single `FEDERATION` key in your
Django settings. This namespacing prevents conflicts with other
packages and keeps federation-related configuration organized.

```python
# settings.py
FEDERATION = {
    'DEFAULT_URL': 'https://myapp.example.com',
    'SOFTWARE_NAME': 'MyFedApp',
    'SOFTWARE_VERSION': '1.0.0',
    'EXTRA_CONTEXT_MODELS': [
        'myapp.models.CustomContext',
    ],
}
```

The toolkit loads these settings at startup and makes them available
through the `app_settings` object. Settings are organized into logical
groups: instance configuration, NodeInfo metadata, rate limiting,
middleware processors, and linked data handling.

## Instance Configuration

Instance settings define how your server presents itself and where
resources live.

**DEFAULT_URL** specifies the base URL for your instance. This becomes
the default domain when creating local resources. The toolkit uses
this to generate URIs for actors, objects, and activities. Set this to
your server's canonical URL including the protocol.

**FORCE_INSECURE_HTTP** overrides the protocol to HTTP instead of
HTTPS. This exists for development and testing. Production deployments
should use HTTPS and leave this setting at its default false value.

**OPEN_REGISTRATIONS** indicates whether your instance accepts new
user registrations. This appears in NodeInfo responses and helps other
servers understand your registration policy. It does not implement
registration logic—your application handles that.

**COLLECTION_PAGE_SIZE** controls how many items appear in each page
of paginated collections. Smaller values reduce payload size but
require more requests to traverse large collections. The default of 25
balances efficiency and responsiveness.

These settings shape your instance's identity in the Fediverse. Choose
values that accurately represent your service and align with your
operational model.

## View Name Configuration

The toolkit generates URIs for different resource types using Django's
URL routing system. Instead of hardcoding URL patterns, you specify
view names and the toolkit uses `reverse()` to generate URIs.

**ACTOR_VIEW** names the view that serves actor documents. When
generating an actor URI, the toolkit reverses this view name with the
actor's primary key. Your URLconf must include a route with this name
that accepts a `pk` parameter.

**OBJECT_VIEW** names the view for generic objects like notes,
articles, and images. Object URIs use this view.

**ACTIVITY_VIEW** names the view for activities. Create, Update,
Delete, and other activity types use this view.

**COLLECTION_VIEW** names the view for collections like inboxes,
outboxes, and followers lists.

**COLLECTION_PAGE_VIEW** names the view for individual pages within
collections.

**KEYPAIR_VIEW** names the view for serving public keys. If not set,
keys use fragment identifiers on the actor URI instead of separate
URLs.

**SHARED_INBOX_VIEW** names the view for the shared inbox endpoint.
This optional optimization allows remote servers to deliver to
multiple recipients with a single request.

**SYSTEM_ACTOR_VIEW** names the view for the instance's system actor.
Some ActivityPub operations require an actor representing the server
itself rather than any particular user.

Setting these view names connects the toolkit to your URL structure.
The toolkit generates URIs, but your views handle the HTTP layer and
render responses.

## NodeInfo Metadata

NodeInfo is a protocol for discovering metadata about Fediverse
instances. Two settings control what your instance advertises.

**SOFTWARE_NAME** identifies your application in NodeInfo responses.
Use a short, descriptive name that distinguishes your software from
other ActivityPub implementations.

**SOFTWARE_VERSION** indicates your application's version. Follow
semantic versioning conventions. Other instances and monitoring tools
use this for compatibility checks and statistics.

These values appear in responses to `/.well-known/nodeinfo` requests.
They help the broader Fediverse ecosystem understand what software
powers different instances.

## Rate Limiting

**RATE_LIMIT_REMOTE_FETCH** controls how frequently the toolkit
refetches remote resources. When resolving a reference that has been
previously resolved, the toolkit checks when it was last fetched. If
less time has passed than this limit, it uses the cached data instead
of making a new HTTP request.

The default is 10 minutes. Lower values mean fresher data but more
network traffic. Higher values reduce load but increase staleness.
Tune this based on your traffic patterns and how important data
freshness is for your application.

This setting applies only to explicit resolution requests, not to
inbox deliveries. When a remote server pushes an activity to your
inbox, you receive it immediately regardless of rate limits.

## Document Resolvers

Document resolvers fetch remote resources when you call `resolve()` on
a reference. The toolkit tries each resolver in sequence until one
successfully returns a document.

**DOCUMENT_RESOLVERS** lists resolver class paths in priority order:

```python
FEDERATION = {
    'DOCUMENT_RESOLVERS': [
        'activitypub.resolvers.ConstantDocumentResolver',
        'activitypub.resolvers.HttpDocumentResolver',
        'myapp.resolvers.CachedDocumentResolver',
    ],
}
```

`ConstantDocumentResolver` handles test fixtures and hardcoded
documents. Useful for development and testing but typically not needed
in production.

`HttpDocumentResolver` fetches documents via HTTP GET with proper
ActivityPub content negotiation. This is the standard mechanism for
retrieving remote resources. It automatically signs requests using
your instance's keypair.

You can implement custom resolvers for specialized needs. A resolver
might query a local cache, integrate with a CDN, or fetch from
alternative protocols. Resolvers implement a simple interface:
`can_resolve(uri)` returns whether the resolver handles a given URI,
and `resolve(uri)` returns the JSON-LD document.

## Context Definitions

**EXTRA_CONTEXTS** lists additional Context definitions to include during JSON-LD serialization. The toolkit includes standard ActivityPub contexts by default, but you can add custom vocabularies:

```python
FEDERATION = {
    'EXTRA_CONTEXTS': [
        'myapp.contexts.MY_CUSTOM_CONTEXT',
    ],
}
```

## Context Models

**EXTRA_CONTEXT_MODELS** lists which context models automatically
process incoming JSON-LD documents. When `LinkedDataDocument.load()`
parses a document, it walks through these models and calls
`load_from_graph()` on each.

The default list includes all ActivityStreams 2.0 and Security
Vocabulary context models. Add your custom context models to have them automatically
extract data:

```python
FEDERATION = {
    'EXTRA_CONTEXT_MODELS': [
        'myapp.models.CustomContextModel',
    ],
}
```

Add your custom context models to this list to have them automatically
extract data:

```python
FEDERATION = {
    'EXTRA_CONTEXT_MODELS': [
        'myapp.models.MastodonContext',
        'myapp.models.LemmyContext',
    ],
}
```

The order matters if models might claim the same references. Models
earlier in the list process references first. Generally, place more
specific models before generic ones.

Removing standard models from this list prevents them from processing
incoming data. This makes sense only if you're replacing them with
custom implementations or intentionally ignoring certain vocabularies.

## Custom Serializers

**CUSTOM_SERIALIZERS** maps context model classes to custom serializer
classes. When `LinkedDataSerializer` processes a context model, it
checks this mapping and uses your custom serializer instead of the
default `ContextModelSerializer`.

```python
FEDERATION = {
    'CUSTOM_SERIALIZERS': {
        'activitypub.models.CollectionContext': 'activitypub.serializers.CollectionContextSerializer',
        'myapp.models.CustomContext': 'myapp.serializers.CustomContextSerializer',
    },
}
```

Custom serializers give you control over how context models transform
to JSON-LD. You might add computed fields, implement complex access
control, or integrate with external services. The serializer receives
the context model instance and returns expanded JSON-LD.

The toolkit includes custom serializers for collection contexts
because they have unique pagination requirements. Your application
might need custom serializers for contexts with special presentation
logic.

## Document Processors

Document processors intercept and transform documents before they're
processed (incoming) or delivered (outgoing). **DOCUMENT_PROCESSORS**
lists processor class paths:

```python
FEDERATION = {
    'DOCUMENT_PROCESSORS': [
        'activitypub.processors.ActorDeletionDocumentProcessor',
        'activitypub.processors.CompactJsonLdDocumentProcessor',
        'myapp.processors.SpamFilterProcessor',
    ],
}
```

Processors implement two methods: `process_incoming(document)` and
`process_outgoing(document)`. Each receives a document dictionary and
can modify it or raise exceptions to block processing.

`ActorDeletionDocumentProcessor` drops Delete activities for actors
your instance has never seen. Mastodon broadcasts deletion activities
widely, including to servers that never interacted with the deleted
actor. This processor prevents wasting resources processing irrelevant
deletions.

`CompactJsonLdDocumentProcessor` strips namespace prefixes from
outgoing documents. Some Fediverse servers don't properly handle
JSON-LD and expect unprefixed attribute names. This processor ensures
compatibility by transforming `as:name` to `name` in outgoing
documents.

Custom processors implement application-specific logic. Filter spam
before processing incoming activities. Add tracking metadata to
outgoing activities. Transform proprietary extensions to standard
vocabulary. Processors operate on raw JSON-LD before graph parsing or
after serialization, giving you hooks at the protocol boundary.

A processor can raise `DropMessage` to abort processing entirely. This
prevents the document from being stored or parsed. Use this for
notifications that fail validation or policy checks.

## Access Pattern Settings

The settings described control the toolkit's behavior but don't
implement business logic. Your application code decides when to call
`resolve()`, which activities to process, and what data to expose.

Settings establish the framework within which your application
operates. They configure technical details like URL generation,
document fetching, and data parsing. Application logic—authorization
policies, content filtering, UI presentation—lives in your views,
models, and business logic layer.

This separation means you can adjust technical configuration without
changing application behavior. Switch from HTTP resolution to cached
resolution by changing a setting. Add a new vocabulary by adding a
context model. These changes don't require modifying views or business
logic.

## Development vs Production

Some settings have different appropriate values for development and
production environments. Django's standard approaches for
environment-specific settings work with federation configuration.

Development might use:
- `DEFAULT_URL = 'http://localhost:8000'`
- `FORCE_INSECURE_HTTP = True`
- `OPEN_REGISTRATIONS = True`
- Reduced `RATE_LIMIT_REMOTE_FETCH` for faster iteration
- Constant resolver included for test fixtures

Production should use:
- `DEFAULT_URL` with your actual domain
- `FORCE_INSECURE_HTTP = False` (default)
- `OPEN_REGISTRATIONS` based on your policy
- Appropriate rate limiting for your scale
- Only HTTP resolver in typical cases

Structure your settings to accommodate both environments. Django's
settings patterns—base settings with environment overlays, environment
variables, separate files—all work normally.

## Extending the Configuration System

The toolkit's configuration system is itself extensible. If you need
settings beyond what the toolkit provides, you can follow similar
patterns in your application.

Access toolkit settings through the `app_settings` object:

```python
from activitypub.settings import app_settings

default_domain = app_settings.Instance.default_url
page_size = app_settings.Instance.collection_page_size
```

Settings are organized in nested classes (`Instance`, `NodeInfo`,
`LinkedData`, etc.) for clarity. Some properties like
`EXTRA_CONTEXT_MODELS` perform lazy import of string paths to
actual classes.

The configuration system loads settings once at startup and caches the
imported classes. Changes to Django settings after startup require
application restart. The toolkit connects to Django's
`setting_changed` signal for test environments where settings change
dynamically.

## Configuration Best Practices

Keep federation configuration consistent with your application's
purpose. A private community might disable open registrations and
restrict which context models process data. A public instance might
enable broader processing and advertise open registrations.

Document your configuration choices, especially custom resolvers,
processors, or context models. Future maintainers need to understand
why certain components are configured the way they are.

Test configuration changes in a development environment before
deploying to production. Misconfigured view names break URI
generation. Missing context models silently ignore vocabulary.
Incorrect processor ordering causes unexpected behavior.

Start with default settings and customize only what your application
requires. The defaults work for typical ActivityPub deployments.
Override specific settings as you discover needs rather than
preemptively customizing everything.

Configuration connects the toolkit to your application's specifics—URL
structure, domain, vocabulary extensions—while preserving the
toolkit's ability to handle standard ActivityPub operations. Get the
configuration right and the toolkit becomes a natural part of your
Django application.
