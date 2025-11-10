---
title: References and Context Models
---

Django ActivityPub Toolkit bridges the gap between RDF's graph model and Django's relational database through a two-layer architecture: References and Context Models. This design lets you leverage Linked Data principles while working with familiar Django patterns.

## The Reference Layer

A `Reference` represents a node in the global social graph. Each reference has a URI that uniquely identifies a resource, whether that resource lives on your server or a remote server.

```python
from activitypub.models import Reference

# Reference to a local resource
local_ref = Reference.objects.get(uri='https://myserver.com/users/alice')

# Reference to a remote resource
remote_ref = Reference.objects.get(uri='https://other-server.com/posts/456')
```

References are intentionally minimal. They track the URI, which domain owns it, and whether the resource has been successfully resolved from its origin. This lightweight design means you can store references to millions of resources without significant overhead.

The reference layer serves several purposes. It provides a unified way to link between resources regardless of where they live. It prevents duplicate entries for the same URI. Most importantly, it separates graph navigation from vocabulary-specific data access.

When you navigate relationships in the Fediverse, you work primarily with references. A post's replies, an actor's followers, items in a collection—these are all stored as references. You don't need to fetch or parse the full data for each referenced resource unless your application needs that data.

## Context Models

Context models attach vocabulary-specific meaning to references. When you need to read or write attributes defined by a particular RDF namespace, you use the corresponding context model.

ActivityStreams 2.0, the core vocabulary for ActivityPub, maps to context models like `ObjectContext`, `ActorContext`, and `ActivityContext`. These models store properties such as `content`, `name`, `published`, and relationship pointers like `attributed_to` and `in_reply_to`.

```python
from activitypub.models import Reference, ObjectContext

ref = Reference.objects.get(uri='https://example.com/posts/123')

# Access AS2-specific attributes
obj = ref.get_by_context(ObjectContext)
print(obj.content)  # "Just learned about Linked Data"
print(obj.name)     # "My First Post"
```

A single reference can have multiple context models attached. An actor might have both `ActorContext` (for AS2 properties like `preferred_username` and `inbox`) and `SECv1Context` (for cryptographic key information). Extensions from platforms like Mastodon or Lemmy would add their own context models.

This separation means vocabulary extensions don't interfere with each other. Each context model extracts only the predicates it recognizes, storing them in its own database table. Applications choose which contexts matter for their use case.

## From JSON-LD to Context Models

When a remote JSON-LD document arrives, the toolkit processes it through a defined pipeline. First, the document is stored as a `LinkedDataDocument` associated with its reference. Then the document is parsed into an RDF graph using rdflib.

The toolkit walks through all subjects in the graph, creating or retrieving Reference instances for each. For each reference, it checks which context models should handle the data by calling their `should_handle_reference` method.

Context models that recognize the resource extract their relevant predicates from the graph and populate their fields. A `Note` object triggers `ObjectContext` to extract `content`, `published`, and `attributed_to`. If the note also includes Mastodon's `sensitive` flag, a Mastodon-specific context model could extract that separately.

This process happens only once when the document first arrives. After that, all data access goes through Django's ORM, querying the context model tables directly. Graph operations are expensive, so the toolkit converts the graph to relational form and then works relationally.

## The Repository Pattern

This architecture implements the repository pattern adapted for RDF data. Traditional repositories provide data access methods that abstract over a data store. Here, context models serve as repositories that translate between the RDF graph (the conceptual model) and Django models (the persistence layer).

When you query for posts by a particular author, you're not querying an RDF graph. You're using Django's ORM to filter ObjectContext instances. This is dramatically more efficient than graph traversal and integrates naturally with the rest of your Django application.

```python
# Efficient relational query
from activitypub.models import ObjectContext, Reference

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
from activitypub.models import Reference

class Post(models.Model):
    reference = models.ForeignKey(Reference, on_delete=models.CASCADE)
    author = models.ForeignKey('auth.User', on_delete=models.CASCADE)
    
    @property
    def AS2(self):
        from activitypub.models import ObjectContext
        return self.reference.get_by_context(ObjectContext)
    
    @property
    def title(self):
        return self.AS2.name
    
    @property
    def body(self):
        return self.AS2.content
```

This pattern keeps your application models focused on your business logic while delegating ActivityPub concerns to the context models. You can add methods that combine data from multiple contexts or compute derived values.

When creating a new local post, generate a reference first, then create both your application model and the appropriate context models.

```python
from activitypub.models import Domain, Reference, ObjectContext
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

Applications that work with specialized vocabularies create their own context models by extending `AbstractContextModel`. Each context model defines which predicates it handles and how to map them to Django fields.

```python
from rdflib import Namespace
from activitypub.models import AbstractContextModel
from django.db import models

LEMMY = Namespace('https://join-lemmy.org/ns#')

class LemmyContext(AbstractContextModel):
    NAMESPACE = str(LEMMY)
    LINKED_DATA_FIELDS = {
        'stickied': LEMMY.stickied,
        'locked': LEMMY.locked,
    }
    
    stickied = models.BooleanField(default=False)
    locked = models.BooleanField(default=False)
    
    @classmethod
    def should_handle_reference(cls, g, reference):
        # Check if the graph includes Lemmy-specific predicates
        stickied_val = reference.get_value(g, predicate=LEMMY.stickied)
        locked_val = reference.get_value(g, predicate=LEMMY.locked)
        return stickied_val is not None or locked_val is not None
```

Register custom contexts in settings to have them automatically process incoming documents:

```python
FEDERATION = {
    'AUTOLOADED_CONTEXT_MODELS': [
        'activitypub.models.ObjectContext',
        'activitypub.models.ActorContext',
        'activitypub.models.ActivityContext',
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

These principles guide how you build applications on the toolkit. Think in terms of references when navigating the graph. Think in terms of contexts when working with specific vocabularies. Think in terms of Django models when implementing your application logic.
