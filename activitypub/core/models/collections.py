import logging
import sys

from django.db import models, transaction
from django.db.models import Max, Q
from model_utils.managers import InheritanceManager

from ..contexts import AS2, RDF
from ..settings import app_settings
from .as2 import AbstractAs2ObjectContext
from .base import generate_ulid
from .linked_data import Reference

logger = logging.getLogger(__name__)


class AbstractCollectionContext(AbstractAs2ObjectContext):
    LINKED_DATA_FIELDS = AbstractAs2ObjectContext.LINKED_DATA_FIELDS | {
        "type": RDF.type,
        "total_items": AS2.totalItems,
        "current": AS2.current,
        "first": AS2.first,
        "last": AS2.last,
        "items": AS2.items,
        "orderedItems": AS2.orderedItems,
    }
    objects = InheritanceManager()

    class Meta:
        abstract = True


class BaseCollectionContext(AbstractCollectionContext):
    @property
    def total_items(self):
        return self.collection_items.count()

    @property
    def is_ordered(self):
        return False

    @property
    def items(self) -> models.QuerySet:
        qs = self._get_item_queryset()

        # Counter-intuitive: "Ordered" Collections in AS2 means that
        # items are reverse ordered by creation date. At the same
        # time, we would like to keep items added to an unordered
        # collection in a fixed position.

        # Ordered items will use the created field to list the items
        # and reverse-chrono order, while for *unordered* items we must look
        # into the "order" field.

        ordered_key = "-created"
        unordered_key = "order"

        order_key = ordered_key if self.is_ordered else unordered_key
        return qs.select_related("item").order_by(order_key)

    @property
    def highest_order_value(self):
        return self.collection_items.aggregate(highest=Max("order")).get("highest") or 0

    def _get_item_queryset(self):
        return self.collection_items.all()

    def reset_ordering(self):
        for idx, item in enumerate(self.collection_items.all(), start=1):
            item.order = idx
            item.save()

    def _get_append_target(self):
        return self

    def contains(self, item: Reference):
        return self.collection_items.filter(item=item).exists()

    def remove(self, item: Reference):
        self.collection_items.filter(item=item).delete()

    def append(self, item: Reference) -> "CollectionItem":
        existing = CollectionItem.objects.filter(item=item, collection=self).first()

        if existing is not None:
            return existing

        target = self._get_append_target()
        target_size = target.collection_items.count()

        new_item_order = max(target.highest_order_value, target_size) + 1
        if new_item_order >= CollectionItem.MAX_ORDER_VALUE:
            new_item_order = (CollectionItem.MAX_ORDER_VALUE + new_item_order) / 2.0

        return CollectionItem.objects.create(order=new_item_order, item=item, collection=target)

    class Meta:
        ordering = ("reference__uri",)


class CollectionItem(models.Model):
    MAX_ORDER_VALUE = sys.float_info.max
    item = models.ForeignKey(Reference, related_name="in_collections", on_delete=models.CASCADE)
    collection = models.ForeignKey(
        BaseCollectionContext, related_name="collection_items", on_delete=models.CASCADE
    )
    order = models.FloatField(default=0.0)
    created = models.DateTimeField(auto_now_add=True)


class CollectionContext(BaseCollectionContext):
    class Types(models.TextChoices):
        UNORDERED = str(AS2.Collection)
        ORDERED = str(AS2.OrderedCollection)

    type = models.CharField(
        max_length=60,
        db_index=True,
        choices=Types.choices,
        default=Types.UNORDERED,
    )

    first = models.ForeignKey(
        Reference, null=True, blank=True, related_name="+", on_delete=models.SET_NULL
    )
    last = models.ForeignKey(
        Reference, null=True, blank=True, related_name="+", on_delete=models.SET_NULL
    )

    @property
    def is_ordered(self):
        return self.type == self.Types.ORDERED

    @property
    def total_items(self):
        return self._get_item_queryset().count()

    @property
    def collection_size(self):
        return self._get_item_queryset().count()

    @property
    def pages(self):
        return CollectionPageContext.objects.filter(part_of=self.reference)

    def _get_append_target(self):
        if not self.pages.exists():
            return self

        if self.last is not None:
            last_page = self.last.get_by_context(CollectionPageContext)
            return last_page._get_append_target()

        return self.make_page()

    def _get_item_queryset(self):
        page_references = CollectionPageContext.objects.filter(part_of=self.reference)
        if not page_references.exists():
            return self.collection_items.all()

        return CollectionItem.objects.filter(collection__in=page_references)

    @transaction.atomic
    def make_page(self):
        reference = CollectionPageContext.generate_reference(domain=self.reference.domain)
        page_types = CollectionPageContext.Types
        new_page = CollectionPageContext.make(
            reference=reference,
            part_of=self.reference,
            type=page_types.ORDERED if self.is_ordered else page_types.UNORDERED,
        )

        if self.first is None:
            self.first = reference
            self.save()

        if self.last is not None:
            last_page = CollectionPageContext.objects.filter(reference=self.last).first()
            last_page.next = reference
            new_page.previous = last_page.reference
            last_page.save()
        else:
            self.last = reference
            self.save()

        new_page.save()
        return new_page

    def contains(self, item: Reference):
        in_collection_q = Q(collection=self)
        in_page_q = Q(collection__collectionpagecontext__part_of=self.reference)
        return (
            CollectionItem.objects.filter(item=item).filter(in_collection_q | in_page_q).exists()
        )

    def remove(self, item: Reference):
        super().remove(item)
        for page in self.pages.filter(collection_items__item=item):
            page.remove(item)

    @classmethod
    def generate_reference(cls, domain):
        ulid = str(generate_ulid())
        if app_settings.Instance.collection_view_name:
            uri = domain.reverse_view(app_settings.Instance.collection_view_name, pk=ulid)
        else:
            uri = f"{domain.url}/collections/{ulid}"
        return Reference.make(uri)

    @classmethod
    def make(cls, reference: Reference, **defaults):
        collection, _ = cls.objects.get_or_create(reference=reference, **defaults)
        if collection.reference.is_local and collection.pages.count() == 0:
            collection.make_page()
        return collection


class CollectionPageContext(BaseCollectionContext):
    class Types(models.TextChoices):
        UNORDERED = str(AS2.CollectionPage)
        ORDERED = str(AS2.OrderedCollectionPage)

    PAGE_SIZE = app_settings.Instance.collection_page_size
    LINKED_DATA_FIELDS = AbstractAs2ObjectContext.LINKED_DATA_FIELDS | {
        "type": RDF.type,
        "total_items": AS2.totalItems,
        "part_of": AS2.partOf,
        "next": AS2.next,
        "previous": AS2.prev,
        "items": AS2.items,
        "ordered_items": AS2.orderedItems,
    }

    type = models.CharField(max_length=64, choices=Types.choices, default=Types.ORDERED)
    part_of = models.ForeignKey(
        Reference, related_name="in_collection_pages", on_delete=models.CASCADE
    )
    previous = models.ForeignKey(
        Reference, related_name="+", null=True, blank=True, on_delete=models.SET_NULL
    )

    next = models.ForeignKey(
        Reference, related_name="+", null=True, blank=True, on_delete=models.SET_NULL
    )

    @property
    def is_ordered(self):
        return self.type == self.Types.ORDERED

    def _get_append_target(self):
        current_page = self

        while (current_page and current_page.next) is not None:
            current_page = CollectionPageContext.objects.filter(
                reference=current_page.next
            ).first()

        if current_page.collection_items.count() < self.PAGE_SIZE:
            return current_page

        return self.part_of.get_by_context(CollectionContext).make_page()

    @classmethod
    def generate_reference(cls, domain):
        ulid = str(generate_ulid())
        if app_settings.Instance.collection_page_view_name:
            uri = domain.reverse_view(app_settings.Instance.collection_page_view_name, pk=ulid)
        else:
            uri = f"{domain.url}/pages/{ulid}"
        return Reference.make(uri)


__all__ = ("CollectionContext", "CollectionItem", "CollectionPageContext")
