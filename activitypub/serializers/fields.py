from rest_framework import serializers

from activitypub.models import ObjectContext, SecV1Context


class ContextField(serializers.Field):
    DEFAULT_CONTEXT_TYPES = {"as2": ObjectContext, "secv1": SecV1Context}

    """
    A field that maps to attributes on ActivityPub context models using configurable context types.

    Context types are defined in the serializer's Meta class with context_types dict.
    Supports source syntax: "context_type.field_path"

    Examples:
        source="as2.name"        # ObjectContext.name
        source="as2.icon.url"  # ObjectContext.icon.url (nested access)

    Read path: instance.reference → ContextClass → field_path
    Write path: validated_data → creates/updates ContextClass.field_path
    """

    def __init__(self, allow_create=True, **kwargs):
        """
        Args:
            allow_create: Whether to create context if it doesn't exist (default: True)
        """
        self.allow_create = allow_create
        super().__init__(**kwargs)

    def _get_context_types(self):
        """Get context type mappings from serializer Meta, with fallbacks to defaults"""
        if hasattr(self.parent, "Meta") and hasattr(self.parent.Meta, "context_types"):
            # Merge serializer-specific mappings with defaults
            return {**self.DEFAULT_CONTEXT_TYPES, **self.parent.Meta.context_types}
        return self.DEFAULT_CONTEXT_TYPES

    def _parse_source(self):
        """Parse source string into context_type and field_path"""
        if not self.source or "." not in self.source:
            return  # Not a context field

        context_type, field_path = self.source.split(".", 1)
        self.context_type = context_type
        self.field_path = field_path

        # Resolve context class from mappings
        context_types = self._get_context_types()
        if context_type not in context_types:
            available = list(context_types.keys())
            raise ValueError(
                f"Unknown context type '{context_type}' in {self.parent.__class__.__name__}. "
                f"Available: {available}"
            )

        self.context_class = context_types[context_type]

    def bind(self, field_name, parent):
        """Called when field is bound to serializer - resolve context mappings"""
        super().bind(field_name, parent)
        self._parse_source()

    def get_attribute(self, instance):
        """
        Extract the value from the context model.

        For a Lemmy model instance:
        1. Get the reference
        2. Get the context from the reference
        3. Extract the field value (with support for dotted notation)
        """
        if not hasattr(self, "context_class"):
            # Fall back to standard Field behavior
            return super().get_attribute(instance)

        # Get reference from the instance
        reference = getattr(instance, "reference", None)
        if reference is None:
            return None

        # Get context instance
        context = reference.get_by_context(self.context_class)
        if context is None:
            return None

        # Handle nested field access (e.g., 'icon.url')
        return self._get_nested_value(context, self.field_path)

    def _get_nested_value(self, obj, path):
        """Get nested attribute value (e.g., 'icon.url')"""
        parts = path.split(".")
        value = obj
        for part in parts:
            if value is None:
                return None
            value = getattr(value, part, None)
        return value

    def to_representation(self, value):
        """
        Convert the context field value to its serialized form.
        Value is already the extracted field value from get_attribute().
        """
        return value

    def to_internal_value(self, data):
        """
        Store the data for later saving.
        Returns a dict with context information that will be processed
        in the serializer's create/update methods.
        """
        if not hasattr(self, "context_class"):
            # Fall back to standard Field behavior
            return super().to_internal_value(data)

        # Return a special marker dict that the serializer will recognize
        return {
            "_context_update": True,
            "context_class": self.context_class,
            "field": self.field_path,
            "value": data,
            "allow_create": self.allow_create,
        }

    def display_value(self, instance):
        """For HTML form rendering in browsable API"""
        value = self.get_attribute(instance)
        return str(value) if value is not None else ""


class ContextAwareSerializerMixin:
    """
    Mixin for serializers that use ContextField.
    Handles saving context updates during create/update operations.

    Note: If this pattern proves useful for other ActivityPub implementations,
    consider moving a generic version to the toolkit.
    """

    def _process_context_updates(self, instance, validated_data):
        """
        Extract and process context field updates from validated_data.
        Returns the cleaned validated_data without context markers.

        Args:
            instance: The model instance to update contexts on
            validated_data: The validated data from the serializer

        Returns:
            dict: validated_data with context update markers removed
        """
        context_updates = {}
        regular_data = {}

        for field_name, field_value in validated_data.items():
            if isinstance(field_value, dict) and field_value.get("_context_update"):
                context_updates[field_name] = field_value
            else:
                regular_data[field_name] = field_value

        for field_name, update_info in context_updates.items():
            context_class = update_info["context_class"]
            field = update_info["field"]
            value = update_info["value"]
            allow_create = update_info["allow_create"]

            context = instance.reference.get_by_context(context_class)
            if context is None:
                if allow_create:
                    context = context_class.make(reference=instance.reference)
                else:
                    continue

            # Handle nested field setting (e.g., 'icon.url')
            field_parts = field.split(".")
            if len(field_parts) == 1:
                # Simple field assignment
                setattr(context, field, value)
            else:
                # Navigate to the nested object
                obj = context
                for part in field_parts[:-1]:
                    obj = getattr(obj, part, None)
                    if obj is None:
                        break
                if obj is not None:
                    setattr(obj, field_parts[-1], value)

            context.save()

        return regular_data

    def create(self, validated_data):
        """
        Create a new instance, handling context field updates.
        """
        return super().create(validated_data)

    def update(self, instance, validated_data):
        """
        Update an instance, handling context field updates.
        """
        validated_data = self._process_context_updates(instance, validated_data)
        return super().update(instance, validated_data)


class ReferenceField(serializers.Field):
    """
    Serializes Reference/ReferenceField as @id only.
    Used for fields that should not be embedded.

    Produces expanded JSON-LD format: [{"@id": "uri"}]
    """

    def to_representation(self, value):
        if value is None:
            return None

        # Handle ReferenceField (M2M)
        if hasattr(value, 'all'):
            refs = value.all()
            if not refs:
                return None
            return [{'@id': ref.uri} for ref in refs]

        # Handle ForeignKey to Reference
        return [{'@id': value.uri}]


class EmbeddedReferenceField(serializers.Field):
    """
    Serializes Reference by embedding full document.
    Recursively uses LinkedDataSerializer with embedded=True.

    Respects depth limits to prevent infinite recursion.
    At max depth, falls back to ReferenceField behavior.
    """

    def __init__(self, max_depth=2, **kwargs):
        self.max_depth = max_depth
        super().__init__(**kwargs)

    def to_representation(self, value):
        if value is None:
            return None

        from .linked_data import LinkedDataSerializer

        depth = self.context.get('depth', 0)

        # At max depth, just output @id
        if depth >= self.max_depth:
            return ReferenceField().to_representation(value)

        # Build context for nested serialization
        viewer = self.context.get('viewer')
        new_context = {
            'viewer': viewer,
            'depth': depth + 1,
        }

        # Copy other context keys if needed
        for key in ['request', 'view']:
            if key in self.context:
                new_context[key] = self.context[key]

        # Embed full document(s)
        if hasattr(value, 'all'):  # ReferenceField (M2M)
            refs = value.all()
            if not refs:
                return None
            return [
                LinkedDataSerializer(ref, embedded=True, context=new_context).data
                for ref in refs
            ]

        # ForeignKey to Reference
        return [
            LinkedDataSerializer(value, embedded=True, context=new_context).data
        ]


class OmittedField(serializers.Field):
    """
    Field that is completely omitted from output.
    Used in embedded serializers to exclude fields.

    The field will not appear in the serialized output at all.
    """

    def get_attribute(self, instance):
        # Signal to DRF that this field should be skipped
        # Returning None would still process the field
        # We need to prevent it from being included at all
        return None

    def to_representation(self, value):
        # This should rarely be called, but handle it gracefully
        return None


__all__ = (
    "ContextField",
    "ContextAwareSerializerMixin",
    "ReferenceField",
    "EmbeddedReferenceField",
    "OmittedField",
)
