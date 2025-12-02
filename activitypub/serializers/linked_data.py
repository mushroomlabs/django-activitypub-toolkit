from typing import Optional

from django.db import models
from rest_framework import serializers

from ..models.linked_data import Reference, ReferenceField
from ..settings import app_settings


class ContextModelSerializer(serializers.Serializer):
    """
    Generic serializer that converts any context model to expanded JSON-LD.

    Automatically uses LINKED_DATA_FIELDS from the context model.
    Handles access control via optional show_<field_name>() methods.
    """

    def __init__(self, instance, **kwargs):
        self.context_model_class = instance.__class__
        super().__init__(instance, **kwargs)

    def to_representation(self, instance):
        """
        Convert context model instance to expanded JSON-LD.

        Supports explicit field overrides - fields defined in the serializer
        class will be used instead of automatic introspection for those fields.

        Returns dict with full predicate URIs as keys.
        """
        viewer = self.context.get("viewer")
        data = {}

        # First, process explicit fields defined in the serializer
        # These override the automatic introspection
        for field_name, field in self.fields.items():
            # Skip if field not in LINKED_DATA_FIELDS (shouldn't happen, but be safe)
            if field_name not in self.context_model_class.LINKED_DATA_FIELDS:
                continue

            # Check access control
            if not self._can_view_field(instance, field_name, viewer):
                continue

            try:
                # Get the attribute using DRF's field logic
                attribute = field.get_attribute(instance)

                # Skip if None or empty sentinel
                if attribute is None or attribute is serializers.empty:
                    continue

                # Serialize using the field's to_representation
                value = field.to_representation(attribute)

                # Skip if field returns None (e.g., OmittedField)
                if value is None:
                    continue

                # Special handling for type field
                if field_name == "type":
                    data["@type"] = value
                    continue

                # Map to predicate URI
                predicate = self.context_model_class.LINKED_DATA_FIELDS[field_name]
                data[str(predicate)] = value
            except Exception:
                # If field processing fails, skip it
                continue

        # Then, introspect LINKED_DATA_FIELDS for fields not explicitly defined
        for field_name, predicate in self.context_model_class.LINKED_DATA_FIELDS.items():
            # Skip if this field is explicitly defined (already processed above)
            if field_name in self.fields:
                continue

            if not self._can_view_field(instance, field_name, viewer):
                continue

            value = getattr(instance, field_name, None)
            if value is None:
                continue

            # Special handling for type field - output as @type
            if field_name == "type":
                # For type field, output as @type with the compact type name
                data["@type"] = value
                continue

            predicate_uri = str(predicate)
            serialized_value = self._serialize_field(field_name, value)

            if serialized_value is not None:
                data[predicate_uri] = serialized_value

        return data

    def _can_view_field(self, instance, field_name: str, viewer: Optional[Reference]) -> bool:
        """
        Check if viewer can see this field.

        Looks for show_<field_name>() method on the serializer.
        If not found, defaults to showing the field.

        Args:
            instance: Context model instance
            field_name: Name of the field
            viewer: Reference of viewing user

        Returns:
            True if field should be included
        """
        method_name = f"show_{field_name}"
        if hasattr(self, method_name):
            method = getattr(self, method_name)
            return method(instance, viewer)

        return True

    def _serialize_field(self, field_name, value):
        """
        Serialize a field value to expanded JSON-LD format.

        Args:
            field_name: Django model field
            value: Field value

        Returns:
            List of dicts in expanded JSON-LD format, or None
        """

        try:
            field = self.context_model_class._meta.get_field(field_name)
        except Exception:
            field = None

        if isinstance(field, ReferenceField):
            refs = value.all()
            if refs:
                return [{"@id": ref.uri} for ref in refs]
            return None

        elif isinstance(field, models.ForeignKey) and field.related_model == Reference:
            return [{"@id": value.uri}]

        elif isinstance(field, (models.CharField, models.TextField)):
            return [{"@value": value}]

        elif isinstance(field, models.DateTimeField):
            return [
                {
                    "@value": value.isoformat(),
                    "@type": "http://www.w3.org/2001/XMLSchema#dateTime",
                }
            ]

        elif isinstance(field, models.IntegerField):
            return [{"@value": value, "@type": "http://www.w3.org/2001/XMLSchema#integer"}]

        elif isinstance(field, models.BooleanField):
            return [{"@value": value, "@type": "http://www.w3.org/2001/XMLSchema#boolean"}]
        else:
            # No field found (likely a property) - infer type from value
            if isinstance(value, bool):
                return [{"@value": value, "@type": "http://www.w3.org/2001/XMLSchema#boolean"}]
            elif isinstance(value, int):
                return [{"@value": value, "@type": "http://www.w3.org/2001/XMLSchema#integer"}]
            else:
                return [{"@value": str(value)}]


class LinkedDataSerializer(serializers.BaseSerializer):
    """
    Serializer for linked data models. Given a reference, find all
    the associated context models that have data and produces the merged JSON-LD.

    Supports embedded mode for simplified representation when referenced
    from other documents.
    """

    def __init__(self, instance, embedded=False, **kwargs):
        """
        Initialize the serializer.

        Args:
            instance: Reference object to serialize
            embedded: If True, uses simplified embedded serializers
            **kwargs: Additional arguments passed to parent
        """
        self.is_embedded = embedded
        super().__init__(instance, **kwargs)

    def get_context_models(self):
        # TODO: improve this so that it we get this from the context models which has data
        return app_settings.CONTEXT_MODELS

    def get_compact_context(self, instance):
        """
        Build the @context array for JSON-LD compaction.

        Collects context URLs and EXTRA_CONTEXT from context models that have data.
        Orders contexts as: AS2 first, other contexts, then extensions dict.

        Returns:
            List representing the @context array
        """
        contexts = set()
        extra_context = {}

        # Collect contexts and extra_context from models that have data
        for context_model_class in self.get_context_models():
            context_obj = instance.get_by_context(context_model_class)
            if not context_obj:
                continue

            # Get context URL
            ctx = context_model_class.CONTEXT
            if ctx is not None:
                contexts.add(ctx.url)

            # Merge extra context if present
            if hasattr(context_model_class, "EXTRA_CONTEXT"):
                extra_context.update(context_model_class.EXTRA_CONTEXT)

        # Build the final context array according to AS2 spec. AS2
        # first, then security/other contexts, then extensions

        # TODO: make this less dependent on AS2 and find a way to make a
        # consistent ordering method.

        compact_context = []
        as2_context = "https://www.w3.org/ns/activitystreams"

        # Add AS2 context first
        if as2_context in contexts:
            compact_context.append(as2_context)

        # Add other contexts (e.g., security)
        for ctx in sorted(contexts):
            if ctx != as2_context:
                compact_context.append(ctx)

        # Add extra context definitions last
        if extra_context:
            compact_context.append(extra_context)

        return compact_context

    def _get_serializer_for_context(self, context_model_class):
        """
        Get appropriate serializer class for a context model.

        When embedded=True, checks EMBEDDED_CONTEXT_SERIALIZERS first,
        then falls back to CUSTOM_CONTEXT_SERIALIZERS, then default.

        Args:
            context_model_class: The context model class to serialize

        Returns:
            Serializer class to use
        """
        # If embedded, check for embedded-specific serializer first
        if self.is_embedded:
            embedded_serializers = app_settings.EMBEDDED_CONTEXT_SERIALIZERS
            if context_model_class in embedded_serializers:
                return embedded_serializers[context_model_class]

        # Fall back to custom serializers
        custom_serializers = app_settings.CUSTOM_CONTEXT_SERIALIZERS
        if context_model_class in custom_serializers:
            return custom_serializers[context_model_class]

        # Default
        return ContextModelSerializer

    def to_representation(self, instance):
        # Get expanded JSON-LD data
        data = {"@id": instance.uri}

        for context_model_class in self.get_context_models():
            context_obj = instance.get_by_context(context_model_class)
            if not context_obj:
                continue

            # Get appropriate serializer class
            serializer_class = self._get_serializer_for_context(context_model_class)

            serializer = serializer_class(context_obj, context=self.context)
            context_data = serializer.data

            data.update(context_data)
        return data


__all__ = ("ContextModelSerializer", "LinkedDataSerializer")
