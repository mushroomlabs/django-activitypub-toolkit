from django.db.models import F, Manager, QuerySet
from model_utils.managers import InheritanceManager, InheritanceQuerySet

from .fields import _get_from_fields_cache, get_context_join_path


class ContextAwareQuerySet(QuerySet):
    """QuerySet that transparently rewrites RelatedContextField lookups into ORM joins.

    Field names declared via RelatedContextField (e.g. ``as2``, ``lemmy``) can be used
    directly in filter/exclude/order_by as if they were real FK fields::

        Community.objects.filter(as2__name="My Community")
        Community.objects.order_by("-lemmy__distinguished")

    These are rewritten to the correct ``reference__<related_name>__<field>`` paths before
    hitting the database.  Use ``with_contexts()`` to batch-prefetch context rows and avoid
    N+1 queries when iterating over a queryset.
    """

    # Tracks which RelatedContextField names were prefetched via with_contexts().
    # Preserved across queryset clones so filters/annotations don't lose it.
    _with_contexts_names = frozenset()

    def _clone(self):
        clone = super()._clone()
        clone._with_contexts_names = self._with_contexts_names
        return clone

    def __iter__(self):
        """Populate a dedicated prefetch cache on each instance's reference.

        When with_contexts() was used, the join path data is already in
        _state.fields_cache from select_related.  We copy it into a separate
        ``_ctx_prefetch`` dict on the reference object so ContextProxy can
        use it without risk of stale data from Django's normal field cache.
        """
        names = self._with_contexts_names
        rcfs = getattr(self.model, "_related_context_fields", {}) if names else {}

        for obj in super().__iter__():
            if names:
                prefetched = {}
                ref = obj.reference
                for name in names:
                    rcf = rcfs.get(name)
                    if rcf is None:
                        continue
                    cached = _get_from_fields_cache(ref, rcf.context_class)
                    if cached is not None:
                        prefetched[rcf.context_class] = cached
                ref._ctx_prefetch = prefetched
            yield obj

    def _rewrite_lookup(self, key):
        """Rewrite a single lookup key if its leading segment names a RelatedContextField."""
        parts = key.split("__")
        field_name = parts[0]

        rcf = getattr(self.model, "_related_context_fields", {}).get(field_name)
        if rcf is None:
            return key

        join_path = get_context_join_path(rcf.context_class)
        # join_path is e.g. "reference__activitypub_objectcontext_context"
        # Append the remaining lookup segments (field name and optional transforms).
        suffix = "__".join(parts[1:])
        if suffix:
            return f"{join_path}__{suffix}"
        return join_path

    def _rewrite_expression(self, expr):
        """Rewrite F() references inside an arbitrary expression tree."""
        if isinstance(expr, F):
            return F(self._rewrite_lookup(expr.name))
        if hasattr(expr, "source_expressions"):
            clone = expr.copy()
            clone.source_expressions = [
                self._rewrite_expression(e) if hasattr(e, "resolve_expression") else e
                for e in clone.source_expressions
            ]
            return clone
        return expr

    def filter(self, *args, **kwargs):
        rewritten = {self._rewrite_lookup(k): v for k, v in kwargs.items()}
        return super().filter(*args, **rewritten)

    def exclude(self, *args, **kwargs):
        rewritten = {self._rewrite_lookup(k): v for k, v in kwargs.items()}
        return super().exclude(*args, **rewritten)

    def order_by(self, *fields):
        rewritten = []
        for f in fields:
            descending = f.startswith("-")
            base = f[1:] if descending else f
            base = self._rewrite_lookup(base)
            rewritten.append(f"-{base}" if descending else base)
        return super().order_by(*rewritten)

    def annotate(self, *args, **kwargs):
        rewritten_args = tuple(self._rewrite_expression(a) for a in args)
        rewritten_kwargs = {k: self._rewrite_expression(v) for k, v in kwargs.items()}
        return super().annotate(*rewritten_args, **rewritten_kwargs)

    def values(self, *fields, **expressions):
        rewritten_fields = tuple(self._rewrite_lookup(f) for f in fields)
        rewritten_exprs = {k: self._rewrite_expression(v) for k, v in expressions.items()}
        return super().values(*rewritten_fields, **rewritten_exprs)

    def values_list(self, *fields, **kwargs):
        rewritten = tuple(self._rewrite_lookup(f) for f in fields)
        return super().values_list(*rewritten, **kwargs)

    def with_contexts(self, *field_names):
        """Prefetch context rows for the named RelatedContextFields via select_related.

        Call this when you know you'll access context data on every result row::

            Community.objects.with_contexts("as2", "lemmy").filter(...)

        Each name must correspond to a RelatedContextField on the model.
        """
        rcfs = getattr(self.model, "_related_context_fields", {})
        paths = []
        for name in field_names:
            rcf = rcfs.get(name)
            if rcf is None:
                raise ValueError(
                    f"{self.model.__name__} has no RelatedContextField named {name!r}. "
                    f"Available: {list(rcfs)}"
                )
            paths.append(get_context_join_path(rcf.context_class))
        qs = self.select_related(*paths)
        qs._with_contexts_names = frozenset(field_names)
        return qs


class ContextAwareInheritanceQuerySet(ContextAwareQuerySet, InheritanceQuerySet):
    """ContextAwareQuerySet with select_subclasses() support for MTI models."""


class ContextAwareManager(Manager):
    def get_queryset(self):
        return ContextAwareQuerySet(self.model, using=self._db)

    def with_contexts(self, *field_names):
        return self.get_queryset().with_contexts(*field_names)


class ContextAwareInheritanceManager(ContextAwareManager, InheritanceManager):
    """ContextAwareManager with select_subclasses() support for MTI models."""

    def get_queryset(self):
        return ContextAwareInheritanceQuerySet(self.model, using=self._db)


__all__ = (
    "ContextAwareQuerySet",
    "ContextAwareInheritanceQuerySet",
    "ContextAwareManager",
    "ContextAwareInheritanceManager",
)
