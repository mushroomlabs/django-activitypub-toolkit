from rest_framework import serializers


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
        if hasattr(value, "all"):
            refs = value.all()
            if not refs:
                return None
            return [{"@id": ref.uri} for ref in refs]

        # Handle ForeignKey to Reference
        return [{"@id": value.uri}]


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

        depth = self.context.get("depth", 0)

        # At max depth, just output @id
        if depth >= self.max_depth:
            return ReferenceField().to_representation(value)

        # Build context for nested serialization
        viewer = self.context.get("viewer")
        new_context = {
            "viewer": viewer,
            "depth": depth + 1,
        }

        # Copy other context keys if needed
        for key in ["request", "view"]:
            if key in self.context:
                new_context[key] = self.context[key]

        # Embed full document(s)
        if hasattr(value, "all"):  # ReferenceField (M2M)
            refs = value.all()
            if not refs:
                return None
            return [
                LinkedDataSerializer(ref, embedded=True, context=new_context).data for ref in refs
            ]

        # ForeignKey to Reference
        return [LinkedDataSerializer(value, embedded=True, context=new_context).data]


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
    "ReferenceField",
    "EmbeddedReferenceField",
    "OmittedField",
)
