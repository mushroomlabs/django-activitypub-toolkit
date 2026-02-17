---
title: Query Context Data Efficiently
---

# Query Context Data Efficiently

Models that use `RelatedContextField` store their ActivityPub properties in separate context model instances linked through a shared `Reference`. This design cleanly separates concerns but creates two challenges when querying: verbose join paths and N+1 query problems.

The `ContextAwareQuerySet` solves both by transparently rewriting lookups and providing batch prefetching.

## Prerequisites

- Complete the [Getting Started](../tutorials/getting_started.md) tutorial
- Understand [References and Context Models](../topics/reference_context_architecture.md)
- Familiarity with Django's ORM and querysets

## Integration

Replace your model's default manager with the context-aware variant:

```python
from django.db import models
from activitypub.core.models import Reference, RelatedContextField, ObjectContext
from activitypub.core.models.managers import ContextAwareManager

class Post(models.Model):
    reference = models.ForeignKey(Reference, on_delete=models.CASCADE)
    as2 = RelatedContextField(ObjectContext)
    
    objects = ContextAwareManager()  # Enable lookup rewriting
```

For models using Django's model-utils `InheritanceManager` for multi-table inheritance, use the combined variant:

```python
from activitypub.core.models.managers import ContextAwareInheritanceManager

class LemmyObject(models.Model):
    reference = models.ForeignKey(Reference, on_delete=models.CASCADE)
    as2 = RelatedContextField(ObjectContext)
    
    objects = ContextAwareInheritanceManager()  # MTI + context awareness
```

## Simplified Filtering

Without `ContextAwareQuerySet`, filtering by context fields requires spelling out the full ORM join path:

```python
# Verbose: internal table names exposed
Post.objects.filter(
    reference__activitypub_baseas2objectcontext_context__objectcontext__name="Hello"
)
```

The queryset rewrites lookups automatically when the leading segment matches a `RelatedContextField` name:

```python
# Clean: use the field name you declared
Post.objects.filter(as2__name="Hello")
Post.objects.filter(as2__published__gt=timezone.now())
Post.objects.exclude(as2__content="")
```

This works for multi-table inheritance contexts too. If your model's `as2` field points to `ActorContext` (which inherits from `ObjectContext`), the rewrite includes the necessary MTI join:

```python
class Community(models.Model):
    as2 = RelatedContextField(ActorContext)  # ActorContext extends ObjectContext

# Query by ActorContext's fields
Community.objects.filter(as2__preferred_username="mycommunity")

# Query by inherited ObjectContext fields
Community.objects.filter(as2__name="My Community")
```

## Ordering by Context Fields

The same rewriting applies to `order_by()`:

```python
# Ascending order
Community.objects.order_by("as2__preferred_username")

# Descending order (the - prefix is preserved)
Community.objects.order_by("-lemmy__posting_restricted_to_mods")

# Mixed: regular fields and context fields
Post.objects.order_by("created_at", "-as2__published")
```

## Annotations and Values

Use context fields in `annotate()`, `values()`, and `values_list()`:

```python
from django.db.models import F, Count

# Annotate with context field values
Community.objects.annotate(
    community_name=F("as2__preferred_username"),
    is_restricted=F("lemmy__posting_restricted_to_mods"),
)

# Extract context fields as dictionaries
for row in Post.objects.values("as2__name", "as2__published"):
    print(row)

# Flat values list
titles = Post.objects.values_list("as2__name", flat=True)
```

`F()` expressions nested inside other expressions are also rewritten:

```python
from django.db.models import Value
from django.db.models.functions import Concat

Post.objects.annotate(
    display_name=Concat(F("as2__name"), Value(" - "), F("as2__content"))
)
```

## Batch Prefetching with with_contexts

Accessing context fields on each instance in a loop causes N+1 queries:

```python
# BAD: 1 query + N queries (one per post)
posts = Post.objects.filter(community=community)
for post in posts:
    print(post.as2.name)  # Triggers a query each iteration
```

The `with_contexts()` method batches context loading into a single query:

```python
# GOOD: exactly 1 query with all context data
posts = Post.objects.with_contexts("as2").filter(community=community)
for post in posts:
    print(post.as2.name)  # No additional queries
```

Prefetch multiple context fields:

```python
# Load AS2 and Lemmy contexts in one query
communities = Community.objects.with_contexts("as2", "lemmy").all()
for community in communities:
    print(community.as2.preferred_username)
    print(community.lemmy.posting_restricted_to_mods)
```

Chain `with_contexts()` with other queryset methods:

```python
Post.objects.with_contexts("as2", "lemmy").filter(
    as2__published__year=2024
).order_by("-as2__published")
```

## How It Works

### Lookup Rewriting

When you call `filter(as2__name="Hello")` on a model with `as2 = RelatedContextField(ObjectContext)`, the queryset:

1. Detects that `as2` is a `RelatedContextField`
2. Computes the full ORM join path: `reference__activitypub_baseas2objectcontext_context__objectcontext__name`
3. Rewrites the lookup before SQL generation

The join path includes:

- The `reference` foreign key from your model to the `Reference` table
- The related name from `Reference` back to the context base class
- Any MTI subclass segments (e.g., `objectcontext` for `ObjectContext`)

### Prefetch Caching

`with_contexts()` uses `select_related()` to join the context tables, loading everything in one SQL query. During iteration, the queryset copies context instances from Django's internal field cache into a dedicated `_ctx_prefetch` dictionary on each `Reference` object.

When `ContextProxy` accesses a context field (`post.as2.name`), it checks `_ctx_prefetch` first. A cache hit means no database query. A cache miss falls back to the normal `get_by_context()` lookup.

The separate `_ctx_prefetch` dict avoids stale data issues. Django's `_state.fields_cache` is populated both by `select_related` and by `objects.create()`, which means a newly created context could leave stale cached values. The `_ctx_prefetch` dict is only written during queryset iteration, making it a reliable signal for prefetched data.

### Queryset Cloning

The `_with_contexts_names` attribute (tracking which fields were prefetched) is preserved across queryset clones. This means method chains work correctly:

```python
# The prefetch setting survives filter()
qs = Post.objects.with_contexts("as2")
qs = qs.filter(as2__published__year=2024)  # _with_contexts_names preserved
qs = qs.order_by("-as2__published")        # Still preserved

for post in qs:  # Batch loading happens here
    print(post.as2.name)  # No extra queries
```

## Class Reference

| Class | Base | Use Case |
|-------|------|----------|
| `ContextAwareQuerySet` | `QuerySet` | Any model with `RelatedContextField` |
| `ContextAwareInheritanceQuerySet` | `ContextAwareQuerySet`, `InheritanceQuerySet` | MTI models needing `select_subclasses()` |
| `ContextAwareManager` | `Manager` | Any model with `RelatedContextField` |
| `ContextAwareInheritanceManager` | `ContextAwareManager`, `InheritanceManager` | MTI models |

Both inheritance variants pass `isinstance` checks against the base classes:

```python
from activitypub.core.models.managers import ContextAwareQuerySet

qs = LemmyObject.objects.all()  # Returns ContextAwareInheritanceQuerySet
isinstance(qs, ContextAwareQuerySet)  # True
```

## Common Patterns

### List Views with Context Data

```python
def community_list(request):
    communities = Community.objects.with_contexts("as2", "lemmy").order_by(
        "-as2__followers_count"
    )
    return render(request, "communities/list.html", {"communities": communities})
```

### API Serializers with Prefetching

```python
from rest_framework import serializers

class PostSerializer(serializers.ModelSerializer):
    title = serializers.CharField(source="as2.name")
    content = serializers.CharField(source="as2.content")
    
    class Meta:
        model = Post
        fields = ["id", "title", "content"]

# ViewSet with optimized queryset
class PostViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PostSerializer
    
    def get_queryset(self):
        return Post.objects.with_contexts("as2").filter(
            as2__published__lte=timezone.now()
        )
```

### Search with Context Fields

```python
from django.db.models import Q

def search_posts(query):
    return Post.objects.with_contexts("as2").filter(
        Q(as2__name__icontains=query) | 
        Q(as2__content__icontains=query)
    ).order_by("-as2__published")
```

### Aggregations with Context Fields

```python
from django.db.models import Count

# Count posts by publication month using context field
Post.objects.annotate(
    month=F("as2__published__month")
).values("month").annotate(
    count=Count("id")
).order_by("month")
```

## Troubleshooting

### "Cannot resolve keyword" Errors

If filtering raises `Cannot resolve keyword 'as2__name'`:

1. Verify the model uses `ContextAwareManager` or `ContextAwareInheritanceManager`
2. Check that `as2` is declared as a `RelatedContextField`, not a regular field
3. Ensure the context class (e.g., `ObjectContext`) inherits from `AbstractContextModel`

### N+1 Queries Still Occurring

If prefetching doesn't reduce queries:

1. Confirm `with_contexts()` is called with the correct field names
2. Check that the field name matches the `RelatedContextField` attribute name
3. Verify iteration happens on the queryset returned by `with_contexts()`, not a clone that lost the setting

```python
# WRONG: filter() before with_contexts() loses the setting
Post.objects.filter(community=community).with_contexts("as2")  # OK
Post.objects.with_contexts("as2").filter(community=community)  # Also OK

# WRONG: accessing unfetched context
Post.objects.with_contexts("as2")  # Only AS2 prefetched
for post in posts:
    print(post.lemmy.locked)  # Still queries - lemmy wasn't prefetched
```

### Incorrect Results with MTI Contexts

If queries return unexpected results when the context model uses multi-table inheritance (like `ActorContext` extending `ObjectContext`):

The join path automatically includes the MTI subclass segment. When you query `ActorContext` fields through an `as2` field pointing to `ActorContext`, the rewrite adds `__actorcontext` to the path. For inherited fields from `ObjectContext`, the path includes `__objectcontext`.

```python
class Community(models.Model):
    as2 = RelatedContextField(ActorContext)

# ActorContext's own field
Community.objects.filter(as2__preferred_username="test")
# Rewrites to: reference__..__actorcontext__preferred_username

# Inherited ObjectContext field  
Community.objects.filter(as2__name="Test")
# Rewrites to: reference__..__objectcontext__name
```

## Next Steps

- Read the [References and Context Models](../topics/reference_context_architecture.md) topic for architectural background
- See [Federate Existing Content](federate_existing_content.md) for integrating with your models
- Explore the [Model Reference](../references/models.md) for detailed API documentation