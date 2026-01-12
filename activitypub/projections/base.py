from django.core.exceptions import FieldDoesNotExist
from django.db import models

from activitypub.contexts import AS2, RDF, SEC_V1_CONTEXT, SECv1
from activitypub.models import CollectionContext, CollectionPageContext, Reference

from .core import ReferenceProjection, use_context


class BaseCollectionProjectionMixin:
    CONTEXT_MODEL = None

    def get_items(self):
        obj = self.reference.get_by_context(self.CONTEXT_MODEL)
        if obj and obj.items:
            return [{"@id": ci.item.uri} for ci in obj.items]

        return None

    def get_total_items(self):
        obj = self.reference.get_by_context(self.CONTEXT_MODEL)
        total = obj and obj.total_items
        return total and [
            {"@value": total, "@type": "http://www.w3.org/2001/XMLSchema#nonNegativeInteger"}
        ]


class CollectionPageProjection(BaseCollectionProjectionMixin, ReferenceProjection):
    CONTEXT_MODEL = CollectionPageContext

    class Meta:
        extra = {"get_items": AS2.items, "get_total_items": AS2.totalItems}


class EmbeddedCollectionPageProjection(BaseCollectionProjectionMixin, ReferenceProjection):
    CONTEXT_MODEL = CollectionPageContext

    class Meta:
        fields = (RDF.type, AS2.items)
        extra = {"get_items": AS2.items}


class CollectionProjection(BaseCollectionProjectionMixin, ReferenceProjection):
    CONTEXT_MODEL = CollectionContext

    class Meta:
        extra = {"get_items": AS2.items, "get_total_items": AS2.totalItems}


class CollectionWithTotalProjection(ReferenceProjection):
    CONTEXT_MODEL = CollectionContext

    class Meta:
        fields = (AS2.totalItems,)


class CollectionWithFirstPageProjection(BaseCollectionProjectionMixin, ReferenceProjection):
    CONTEXT_MODEL = CollectionContext

    class Meta:
        omit = (AS2.items, AS2.orderedItems, AS2.last)
        overrides = {AS2.first: EmbeddedCollectionPageProjection}
        extra = {"get_total_items": AS2.totalItems}


class PublicKeyProjection(ReferenceProjection):
    class Meta:
        omit = (
            SECv1.revoked,
            SECv1.created,
            SECv1.creator,
            SECv1.signatureValue,
            SECv1.signatureAlgorithm,
        )


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
        overrides = {AS2.endpoints: EndpointProjection}


class QuestionProjection(ReferenceProjection):
    class Meta:
        embed = (AS2.oneOf, AS2.anyOf)


class NoteProjection(ReferenceProjection):
    class Meta:
        overrides = {
            AS2.replies: CollectionWithFirstPageProjection,
            AS2.likes: CollectionWithTotalProjection,
            AS2.shares: CollectionWithTotalProjection,
        }


__all__ = (
    "CollectionProjection",
    "CollectionPageProjection",
    "CollectionWithTotalProjection",
    "CollectionWithFirstPageProjection",
    "EmbeddedCollectionPageProjection",
    "EndpointProjection",
    "PublicKeyProjection",
    "ActorProjection",
    "QuestionProjection",
    "NoteProjection",
)
