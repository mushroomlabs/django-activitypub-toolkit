from django.core.exceptions import FieldDoesNotExist
from django.db import models

from activitypub.contexts import AS2, RDF, SCHEMA, SEC_V1_CONTEXT, SECv1
from activitypub.models import CollectionContext, CollectionPageContext, Reference

from .core import EmbeddedDocumentProjection, ReferenceProjection, use_context


class SourceProjection(ReferenceProjection):
    class Meta:
        fields = (AS2.content, AS2.mediaType)


class BaseCollectionProjection(ReferenceProjection):
    CONTEXT_MODEL = None

    def _get_items(self, container):
        return [{"@id": ci.item.uri} for ci in container.items]

    def get_unordered_items(self):
        obj = self.reference.get_by_context(self.CONTEXT_MODEL)
        if obj and obj.items and not obj.is_ordered:
            return self._get_items(obj)
        return None

    def get_ordered_items(self):
        obj = self.reference.get_by_context(self.CONTEXT_MODEL)
        if obj and obj.items and obj.is_ordered:
            return self._get_items(obj)
        return None

    def get_total_items(self):
        obj = self.reference.get_by_context(self.CONTEXT_MODEL)

        if obj is None:
            return None

        return [
            {
                "@value": obj.total_items,
                "@type": "http://www.w3.org/2001/XMLSchema#nonNegativeInteger",
            }
        ]

    class Meta:
        extra = {
            "get_unordered_items": AS2.items,
            "get_ordered_items": AS2.orderedItems,
            "get_total_items": AS2.totalItems,
        }


class CollectionPageProjection(BaseCollectionProjection):
    CONTEXT_MODEL = CollectionPageContext


class EmbeddedCollectionPageProjection(BaseCollectionProjection):
    CONTEXT_MODEL = CollectionPageContext

    class Meta:
        fields = (RDF.type, AS2.items, AS2.orderedItems, AS2.totalItems)


class CollectionProjection(BaseCollectionProjection):
    CONTEXT_MODEL = CollectionContext


class CollectionWithTotalProjection(BaseCollectionProjection):
    CONTEXT_MODEL = CollectionContext

    class Meta:
        fields = (AS2.totalItems, RDF.type)


class CollectionWithFirstPageProjection(BaseCollectionProjection):
    CONTEXT_MODEL = CollectionContext

    def _get_items(self, container):
        return None

    class Meta:
        omit = (AS2.items, AS2.orderedItems, AS2.last)
        overrides = {AS2.first: EmbeddedCollectionPageProjection}


class PublicKeyProjection(ReferenceProjection):
    class Meta:
        omit = (
            SECv1.revoked,
            SECv1.created,
            SECv1.creator,
            SECv1.signatureValue,
            SECv1.signatureAlgorithm,
        )


class LanguageProjection(EmbeddedDocumentProjection):
    class Meta:
        fields = (SCHEMA.identifier, AS2.name)


class EndpointProjection(ReferenceProjection):
    def _default_serialize(self, context_obj, field_name, value):
        try:
            field = context_obj._meta.get_field(field_name)
        except (AttributeError, FieldDoesNotExist):
            return super()._default_serialize(context_obj, field_name, value)

        # For URLFields in endpoints, serialize as @id
        if isinstance(field, models.URLField):
            return [{"@id": value}]

        # Delegate to parent for other field types
        return super()._default_serialize(context_obj, field_name, value)

    class Meta:
        omit = ()


class ActorProjection(ReferenceProjection):
    @use_context(SEC_V1_CONTEXT.url)
    def get_public_key(self):
        references = Reference.objects.filter(
            activitypub_secv1context_context__owner=self.reference
        )
        projections = [PublicKeyProjection(reference=ref, parent=self) for ref in references]
        return [p.get_expanded() for p in projections]

    class Meta:
        extra = {"get_public_key": SECv1.publicKey}
        overrides = {AS2.endpoints: EndpointProjection, AS2.source: SourceProjection}


class ObjectProjection(ReferenceProjection):
    class Meta:
        overrides = {
            AS2.source: SourceProjection,
            AS2.replies: CollectionWithFirstPageProjection,
            AS2.likes: CollectionWithTotalProjection,
            AS2.shares: CollectionWithTotalProjection,
        }
        embed = (AS2.oneOf, AS2.anyOf)


class QuestionProjection(ObjectProjection):
    pass


class NoteProjection(ObjectProjection):
    pass


class PageProjection(ObjectProjection):
    pass


class ActivityProjection(ReferenceProjection):
    class Meta:
        overrides = {AS2.object: ObjectProjection}


__all__ = (
    "ActivityProjection",
    "ActorProjection",
    "CollectionProjection",
    "CollectionPageProjection",
    "CollectionWithTotalProjection",
    "CollectionWithFirstPageProjection",
    "EmbeddedCollectionPageProjection",
    "EndpointProjection",
    "LanguageProjection",
    "NoteProjection",
    "ObjectProjection",
    "PageProjection",
    "PublicKeyProjection",
    "QuestionProjection",
    "SourceProjection",
)
