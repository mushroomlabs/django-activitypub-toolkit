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

        Returns dict with full predicate URIs as keys.
        """
        viewer = self.context.get("viewer")
        data = {}

        for field_name, predicate in self.context_model_class.LINKED_DATA_FIELDS.items():
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
    """

    def get_context_models(self):
        # TODO: improve this so that it we get this from the context models which has data
        return app_settings.AUTOLOADED_CONTEXT_MODELS

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
            ctx = context_model_class.get_context()
            if ctx is not None:
                contexts.add(ctx)

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

    def to_representation(self, instance):
        # Get expanded JSON-LD data
        data = {"@id": instance.uri}
        custom_serializers = app_settings.CUSTOM_SERIALIZERS

        for context_model_class in self.get_context_models():
            context_obj = instance.get_by_context(context_model_class)
            if not context_obj:
                continue

            # Get serializer - use custom if registered, otherwise default
            if context_model_class in custom_serializers:
                serializer_class = custom_serializers[context_model_class]
            else:
                serializer_class = ContextModelSerializer

            serializer = serializer_class(context_obj, context=self.context)
            context_data = serializer.data

            data.update(context_data)
        return data


__all__ = ("ContextModelSerializer", "LinkedDataSerializer")
