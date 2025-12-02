from .fields import EmbeddedReferenceField, OmittedField
from .linked_data import ContextModelSerializer


class CollectionContextSerializer(ContextModelSerializer):
    """
    Collection serializer that embeds the first page.

    When viewing a collection, the first page is embedded so clients
    can immediately see some items without an additional request.
    """

    first = EmbeddedReferenceField()

    def _serialize_field(self, field_name, value):
        if field_name in ["items", "ordered_items"]:
            return [{"@id": ci.item.uri} for ci in value]

        if field_name == "total_items":
            # totalItems in AS2 context expects xsd:nonNegativeInteger
            return [
                {"@value": value, "@type": "http://www.w3.org/2001/XMLSchema#nonNegativeInteger"}
            ]

        return super()._serialize_field(field_name, value)


class CollectionPageContextSerializer(CollectionContextSerializer):
    """
    Collection page serializer - shows items when it's the main subject.

    Unlike CollectionContext, pages should always show their items
    (that's their whole purpose).
    """

    pass  # Inherits from CollectionContextSerializer, keeps all fields


class EmbeddedCollectionContextSerializer(CollectionContextSerializer):
    """
    Simplified collection serializer for embedding in other documents.

    Omits items, orderedItems, and first to keep embedded representation compact.
    Still includes totalItems and @id.
    """

    items = OmittedField()
    ordered_items = OmittedField()
    first = OmittedField()


class EmbeddedActorContextSerializer(ContextModelSerializer):
    """
    Simplified actor serializer for embedding in other documents.

    Omits collections (inbox, outbox, followers, following, liked)
    to keep embedded representation compact.
    """

    inbox = OmittedField()
    outbox = OmittedField()
    followers = OmittedField()
    following = OmittedField()
    liked = OmittedField()


class QuestionContextSerializer(ContextModelSerializer):
    """
    Question serializer that embeds choice options (oneOf/anyOf).

    Choices are embedded as full objects so clients can display them.
    """

    one_of = EmbeddedReferenceField()
    any_of = EmbeddedReferenceField()


__all__ = (
    "CollectionContextSerializer",
    "CollectionPageContextSerializer",
    "EmbeddedActorContextSerializer",
    "EmbeddedCollectionContextSerializer",
    "QuestionContextSerializer",
)
