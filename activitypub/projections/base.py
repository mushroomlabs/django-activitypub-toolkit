from activitypub.contexts import AS2, SEC_V1_CONTEXT, SECv1
from activitypub.models import CollectionContext, CollectionPageContext, Reference

from .core import ReferenceProjection, use_context


class BaseCollectionProjection(ReferenceProjection):
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

    class Meta:
        extra = {"get_items": AS2.items, "get_total_items": AS2.totalItems}


class CollectionPageProjection(BaseCollectionProjection):
    CONTEXT_MODEL = CollectionPageContext


class CollectionProjection(BaseCollectionProjection):
    CONTEXT_MODEL = CollectionContext


class CollectionWithTotalProjection(ReferenceProjection):
    class Meta:
        fields = (AS2.totalItems,)


class CollectionWithFirstPageProjection(ReferenceProjection):
    def get_total_items(self):
        obj = self.reference.get_by_context(CollectionContext)
        total = obj and obj.total_items
        return total and [
            {"@value": total, "@type": "http://www.w3.org/2001/XMLSchema#nonNegativeInteger"}
        ]

    class Meta:
        omit = (AS2.items, AS2.orderedItems, AS2.last)
        overrides = {AS2.first: CollectionPageProjection}
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
    "PublicKeyProjection",
    "ActorProjection",
    "QuestionProjection",
    "NoteProjection",
)
