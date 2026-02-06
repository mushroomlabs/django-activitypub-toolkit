from decimal import Decimal
from typing import Dict, Set
from uuid import UUID

from django.core.exceptions import FieldDoesNotExist
from django.db import models
from pyld import jsonld

from ..models.fields import ReferenceField
from ..models.linked_data import Reference
from ..settings import app_settings


def use_context(context):
    """
    Decorator to register contexts needed by an extra field method.

    Args:
        context: Either a string (context URL) or dict (extra context definitions)

    Can be stacked to add multiple contexts:
        @use_context("https://w3id.org/security/v1")
        @use_context({"myProp": "https://example.com/myProp"})
        def my_method(self):
            ...
    """

    def decorator(func):
        def wrapper(self):
            # Add to appropriate registry
            if isinstance(context, str):
                self.seen_contexts.add(context)
            elif isinstance(context, dict):
                self.extra_context.update(context)
            # Call the original method
            return func(self)

        return wrapper

    return decorator


class ProjectionMeta(type):
    def __new__(mcs, name, bases, attrs):
        # Collect Meta from bases
        meta_fields = set()
        meta_omit = set()
        meta_embed = set()
        meta_overrides = {}
        meta_extra = {}

        for base in reversed(bases):
            if hasattr(base, "_meta_fields"):
                meta_fields.update(base._meta_fields)
            if hasattr(base, "_meta_omit"):
                meta_omit.update(base._meta_omit)
            if hasattr(base, "_meta_embed"):
                meta_embed.update(base._meta_embed)
            if hasattr(base, "_meta_overrides"):
                meta_overrides.update(base._meta_overrides)
            if hasattr(base, "_meta_extra"):
                meta_extra.update(base._meta_extra)

        # Get Meta from current class
        if "Meta" in attrs:
            meta = attrs["Meta"]
            if hasattr(meta, "fields"):
                meta_fields = set(meta.fields)
            if hasattr(meta, "omit"):
                meta_omit.update(meta.omit)
            if hasattr(meta, "embed"):
                meta_embed.update(meta.embed)
            if hasattr(meta, "overrides"):
                meta_overrides.update(meta.overrides)
            if hasattr(meta, "extra"):
                meta_extra.update(meta.extra)

        attrs["_meta_fields"] = meta_fields
        attrs["_meta_omit"] = meta_omit
        attrs["_meta_embed"] = meta_embed
        attrs["_meta_overrides"] = meta_overrides
        attrs["_meta_extra"] = meta_extra

        return super().__new__(mcs, name, bases, attrs)


class ReferenceProjection(metaclass=ProjectionMeta):
    """
    Base projection class for rendering References as JSON-LD.

    By default, all Reference fields output only @id.
    Use Meta to control what gets embedded, omitted, or which fields to include.

    Meta options:
        fields: Set of predicates to include (allowlist, mutually exclusive with omit)
        omit: Set of predicates to exclude (denylist)
        embed: Set of predicates to embed using the same projection class
        overrides: Dict mapping predicates to specific projection classes
        extra: Dict mapping method names to predicates for computed fields

    Args:
        reference: The Reference instance to project
        scope: Optional dict containing extra information.
        parent: Optional parent projection for sharing context tracking
    """

    def __init__(self, reference, scope=None, parent=None):
        self.reference = reference
        self.scope = scope or {}
        self.parent = parent
        self.seen_contexts: Set[str] = set() if parent is None else parent.seen_contexts
        self.extra_context: Dict = {} if parent is None else parent.extra_context
        self._expanded = None
        self._built = False

    def build(self):
        """
        Build the expanded JSON-LD document.

        1. Find all context models for this reference
        2. Generate expanded document (all references as @id by default)
        3. Apply embed rules from Meta
        4. Apply omit rules from Meta
        5. Add extra fields from Meta.extra
        """
        if self._built:
            return

        data = {"@id": self.reference.uri}

        context_models = self._get_context_models_with_data()

        if self._meta_fields:
            data.update(self._build_with_fields_filter(context_models))
        else:
            data.update(self._build_all_fields(context_models))

        # Add extra fields
        data.update(self._build_extra_fields())

        self._expanded = data
        self._built = True

    def _get_context_models_with_data(self):
        models_with_data = []

        for context_model_class in app_settings.CONTEXT_MODELS:
            context_obj = self.reference.get_by_context(context_model_class)
            if context_obj:
                # Register context
                if context_model_class.CONTEXT:
                    self.seen_contexts.add(context_model_class.CONTEXT.url)
                if hasattr(context_model_class, "EXTRA_CONTEXT"):
                    self.extra_context.update(context_model_class.EXTRA_CONTEXT)

                models_with_data.append((context_model_class, context_obj))

        return models_with_data

    def _build_with_fields_filter(self, context_models):
        data = {}

        for context_model_class, context_obj in context_models:
            for field_name, predicate in context_model_class.LINKED_DATA_FIELDS.items():
                # Skip if not in fields list
                if predicate not in self._meta_fields:
                    continue

                if not self._should_include(context_obj, field_name):
                    continue

                value = getattr(context_obj, field_name, None)
                if value is None:
                    continue

                serialized = self._serialize_field(predicate, field_name, value, context_obj)
                if serialized is not None:
                    if field_name == "type":
                        # @type should be a plain string in expanded JSON-LD, not wrapped
                        # Extract the value if it's in expanded form
                        if isinstance(serialized, list) and len(serialized) > 0:
                            if isinstance(serialized[0], dict) and "@value" in serialized[0]:
                                data["@type"] = serialized[0]["@value"]
                            else:
                                data["@type"] = serialized[0]
                        else:
                            data["@type"] = serialized
                    else:
                        data[str(predicate)] = serialized

        return data

    def _build_all_fields(self, context_models):
        data = {}

        for context_model_class, context_obj in context_models:
            for field_name, predicate in context_model_class.LINKED_DATA_FIELDS.items():
                # Skip omitted fields
                if predicate in self._meta_omit:
                    continue

                if not self._should_include(context_obj, field_name):
                    continue

                value = getattr(context_obj, field_name, None)
                if value is None:
                    continue

                serialized = self._serialize_field(predicate, field_name, value, context_obj)
                if serialized is not None:
                    if field_name == "type":
                        # @type should be a plain string in expanded JSON-LD, not wrapped
                        # Extract the value if it's in expanded form
                        if isinstance(serialized, list) and len(serialized) > 0:
                            if isinstance(serialized[0], dict) and "@value" in serialized[0]:
                                data["@type"] = serialized[0]["@value"]
                            else:
                                data["@type"] = serialized[0]
                        else:
                            data["@type"] = serialized
                    else:
                        data[str(predicate)] = serialized

        return data

    def _serialize_field(self, predicate, field_name, value, context_obj):
        """
        Serialize a field value.

        Checks Meta.overrides and Meta.embed to determine if we should:
        - Use a custom projection (overrides)
        - Embed with default projection (embed)
        - Just output @id (default)
        """
        # Check for override projection
        if predicate in self._meta_overrides:
            projection_class = self._meta_overrides[predicate]
            return self._embed_with_projection(value, projection_class)

        # Check if should be embedded with default projection
        if predicate in self._meta_embed:
            return self._embed_with_projection(value, self.__class__)

        # Default: serialize based on field type
        return self._default_serialize(context_obj, field_name, value)

    def _embed_with_projection(self, value, projection_class):
        if value is None:
            return None

        # Handle M2M fields or queryset
        if hasattr(value, "all"):
            refs = value.all()
            if not refs:
                return None

            result = []
            for ref in refs:
                projection = projection_class(ref, scope=self.scope, parent=self)
                projection.build()
                expanded = projection.get_expanded()

                # Remove @id for skolemized references (blank nodes)
                if not ref.is_named_node:
                    expanded.pop("@id", None)

                result.append(expanded)
            return result

        # Handle ForeignKey to Reference
        if isinstance(value, Reference):
            projection = projection_class(value, scope=self.scope, parent=self)
            projection.build()
            expanded = projection.get_expanded()

            # Remove @id for skolemized references (blank nodes)
            if not value.is_named_node:
                expanded.pop("@id", None)

            return [expanded]

        # Handle context objects with .reference attribute
        if hasattr(value, "reference"):
            projection = projection_class(value.reference, scope=self.scope, parent=self)
            projection.build()
            expanded = projection.get_expanded()

            # Remove @id for skolemized references (blank nodes)
            if not value.reference.is_named_node:
                expanded.pop("@id", None)

            return [expanded]

        return None

    def _default_serialize(self, context_obj, field_name, value):
        try:
            field = context_obj._meta.get_field(field_name)
        except (AttributeError, FieldDoesNotExist):
            # Field doesn't exist (might be a property or computed field)
            # Try to infer from value type

            match value:
                case bool():
                    return [{"@value": value, "@type": "http://www.w3.org/2001/XMLSchema#boolean"}]
                case int():
                    return [{"@value": value, "@type": "http://www.w3.org/2001/XMLSchema#integer"}]
                case float():
                    return [{"@value": value, "@type": "http://www.w3.org/2001/XMLSchema#double"}]
                case Decimal():
                    return [
                        {"@value": str(value), "@type": "http://www.w3.org/2001/XMLSchema#decimal"}
                    ]
                case UUID():
                    return [
                        {"@value": str(value), "@type": "http://www.w3.org/2001/XMLSchema#string"}
                    ]
                case str():
                    return [{"@value": value}]
                case _:
                    return None

        if isinstance(field, ReferenceField):
            refs = value.all()
            return [{"@id": ref.uri} for ref in refs] if refs else None

        if field.related_model == Reference:
            return [{"@id": value.uri}]

        match field:
            case models.CharField() | models.TextField():
                return [{"@value": value}]

            case models.DateTimeField():
                return [
                    {
                        "@value": value.isoformat(),
                        "@type": "http://www.w3.org/2001/XMLSchema#dateTime",
                    }
                ]

            case models.DateField():
                return [
                    {"@value": value.isoformat(), "@type": "http://www.w3.org/2001/XMLSchema#date"}
                ]

            case models.TimeField():
                return [
                    {"@value": value.isoformat(), "@type": "http://www.w3.org/2001/XMLSchema#time"}
                ]

            case models.PositiveIntegerField():
                return [
                    {
                        "@value": value,
                        "@type": "http://www.w3.org/2001/XMLSchema#nonNegativeInteger",
                    }
                ]

            case models.IntegerField() | models.SmallIntegerField() | models.BigIntegerField():
                return [{"@value": value, "@type": "http://www.w3.org/2001/XMLSchema#integer"}]

            case models.FloatField():
                return [{"@value": value, "@type": "http://www.w3.org/2001/XMLSchema#double"}]

            case models.DecimalField():
                return [
                    {"@value": str(value), "@type": "http://www.w3.org/2001/XMLSchema#decimal"}
                ]

            case models.BooleanField():
                return [{"@value": value, "@type": "http://www.w3.org/2001/XMLSchema#boolean"}]

            case models.UUIDField():
                return [{"@value": str(value), "@type": "http://www.w3.org/2001/XMLSchema#string"}]

            case models.URLField():
                return [{"@value": value, "@type": "http://www.w3.org/2001/XMLSchema#anyURI"}]

            case _:
                return None

    def _build_extra_fields(self):
        data = {}

        for method_name, predicate in self._meta_extra.items():
            if not hasattr(self, method_name):
                continue

            method = getattr(self, method_name)
            result = method()

            if result is not None:
                data[str(predicate)] = result

        return data

    def _should_include(self, context_obj, field_name):
        method_name = f"show_{field_name}"
        if hasattr(context_obj, method_name):
            return getattr(context_obj, method_name)(self.scope)
        return True

    def get_expanded(self):
        if not self._built:
            self.build()
        return self._expanded

    def get_compacted(self):
        if not self._built:
            self.build()

        # Build @context array
        context_array = self._build_context_array()

        # Compact using pyld
        compacted = jsonld.compact(self._expanded, context_array)

        # Only root adds @context
        if self.parent is None:
            # If only one context, use it directly instead of array
            if len(context_array) == 1:
                compacted["@context"] = context_array[0]
            else:
                compacted["@context"] = context_array

        return compacted

    def _build_context_array(self):
        result = []
        as2 = "https://www.w3.org/ns/activitystreams"

        if as2 in self.seen_contexts:
            result.append(as2)

        for ctx in sorted(self.seen_contexts):
            if ctx != as2:
                result.append(ctx)

        if self.extra_context:
            result.append(self.extra_context)

        return result


class EmbeddedDocumentProjection(ReferenceProjection):
    def get_compacted(self):
        data = super().get_compacted()
        data.pop("id", None)
        return data


__all__ = ("ReferenceProjection", "EmbeddedDocumentProjection", "use_context")
