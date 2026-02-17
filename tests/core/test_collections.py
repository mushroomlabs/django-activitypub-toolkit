from django.test import override_settings

from activitypub.core import models
from activitypub.core.factories import CollectionFactory, DomainFactory, ReferenceFactory
from tests.core.base import BaseTestCase


@override_settings(
    FEDERATION={"DEFAULT_URL": "http://testserver", "FORCE_INSECURE_HTTP": True},
    ALLOWED_HOSTS=["testserver"],
)
class OrderedCollectionTestCase(BaseTestCase):
    def setUp(self):
        self.domain = DomainFactory(scheme="http", name="testserver", local=True)
        self.collection = CollectionFactory(
            reference__domain=self.domain, type=models.CollectionContext.Types.ORDERED
        )

    def test_items_are_in_reverse_chronological_order(self):
        """Items in OrderedCollection must be presented most recent first."""
        item1 = ReferenceFactory(domain=self.domain)
        item2 = ReferenceFactory(domain=self.domain)
        item3 = ReferenceFactory(domain=self.domain)

        self.collection.append(item1)
        self.collection.append(item2)
        self.collection.append(item3)

        items = list(self.collection.items)
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0].item, item3, "Most recent item should be first")
        self.assertEqual(items[1].item, item2)
        self.assertEqual(items[2].item, item1, "Oldest item should be last")

    def test_first_page_contains_newest_items(self):
        """For reverse chronological order, first page should have newest items."""
        self.collection.make_page()
        for i in range(5):
            item = ReferenceFactory(domain=self.domain)
            self.collection.append(item)

        first_page = self.collection.first.get_by_context(models.CollectionPageContext)
        self.assertIsNotNone(first_page)

        first_page_items = list(first_page.items)
        self.assertEqual(len(first_page_items), 5)

        newest_item = list(self.collection.items)[0]
        self.assertEqual(first_page_items[0].item, newest_item.item)

    def test_last_page_contains_oldest_items(self):
        """For reverse chronological order, last page should have oldest items"""
        self.collection.make_page()
        for i in range(3):
            item = ReferenceFactory(domain=self.domain)
            self.collection.append(item)

        self.assertIsNotNone(self.collection.last)
        last_page = self.collection.last.get_by_context(models.CollectionPageContext)
        self.assertIsNotNone(last_page)

    def test_pages_chronological_ordering(self):
        [self.collection.make_page() for _ in range(3)]

        self.assertIsNotNone(self.collection.first)
        self.assertIsNotNone(self.collection.last)
        self.assertNotEqual(self.collection.first, self.collection.last)

        page1 = self.collection.first.get_by_context(models.CollectionPageContext)
        last_page = self.collection.last.get_by_context(models.CollectionPageContext)

        self.assertIsNotNone(page1.next, "First page should have next")
        page2 = page1.next.get_by_context(models.CollectionPageContext)

        self.assertIsNotNone(page2.next, "Second page should have next")
        page3 = page2.next.get_by_context(models.CollectionPageContext)

        self.assertIsNone(page3.next, "Third/last page should not have next")
        self.assertEqual(page3, last_page)

        self.assertIsNone(page1.previous, "First page should not have previous")
        self.assertIsNotNone(page2.previous, "Second page should have previous")
        self.assertEqual(page2.previous.get_by_context(models.CollectionPageContext), page1)
        self.assertIsNotNone(page3.previous, "Third page should have previous")
        self.assertEqual(page3.previous.get_by_context(models.CollectionPageContext), page2)

    def test_all_pages_reachable_from_first_and_last(self):
        pages = [self.collection.make_page() for _ in range(5)]

        page_uris = set(p.reference.uri for p in pages)

        forward_visited = set()
        current = self.collection.first.get_by_context(models.CollectionPageContext)
        while current is not None:
            forward_visited.add(current.reference.uri)
            if current.next:
                current = current.next.get_by_context(models.CollectionPageContext)
            else:
                break

        backward_visited = set()
        current = self.collection.last.get_by_context(models.CollectionPageContext)
        while current is not None:
            backward_visited.add(current.reference.uri)
            if current.previous:
                current = current.previous.get_by_context(models.CollectionPageContext)
            else:
                break

        self.assertEqual(
            forward_visited,
            page_uris,
            "All pages should be reachable from first via next chain",
        )
        self.assertEqual(
            backward_visited,
            page_uris,
            "All pages should be reachable from last via prev chain",
        )

    def test_new_page_becomes_first_not_last(self):
        page1 = self.collection.make_page()

        self.assertEqual(self.collection.first, page1.reference)
        self.assertEqual(self.collection.last, page1.reference)

        page2 = self.collection.make_page()

        self.assertEqual(
            self.collection.first,
            page2.reference,
            "New page should become first (contains newer items)",
        )
        self.assertEqual(
            self.collection.last,
            page1.reference,
            "Old page should become last (contains older items)",
        )

        page3 = self.collection.make_page()

        self.assertEqual(self.collection.first, page3.reference)
        self.assertEqual(self.collection.last, page1.reference)


@override_settings(
    FEDERATION={"DEFAULT_URL": "http://testserver", "FORCE_INSECURE_HTTP": True},
    ALLOWED_HOSTS=["testserver"],
)
class UnorderedCollectionTestCase(BaseTestCase):
    def setUp(self):
        self.domain = DomainFactory(scheme="http", name="testserver", local=True)
        self.collection = CollectionFactory(
            reference__domain=self.domain,
            type=models.CollectionContext.Types.UNORDERED,
        )

    def test_items_maintain_insertion_order(self):
        item1 = ReferenceFactory(domain=self.domain)
        item2 = ReferenceFactory(domain=self.domain)
        item3 = ReferenceFactory(domain=self.domain)

        self.collection.append(item1)
        self.collection.append(item2)
        self.collection.append(item3)

        items = list(self.collection.items)
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0].item, item1, "First appended should be first")
        self.assertEqual(items[1].item, item2)
        self.assertEqual(items[2].item, item3, "Last appended should be last")

    def test_pages_reachable_from_first_and_last(self):
        pages = [self.collection.make_page() for _ in range(3)]

        page_uris = set(p.reference.uri for p in pages)

        forward_visited = set()
        current = self.collection.first.get_by_context(models.CollectionPageContext)
        while current is not None:
            forward_visited.add(current.reference.uri)
            if current.next:
                current = current.next.get_by_context(models.CollectionPageContext)
            else:
                break

        backward_visited = set()
        current = self.collection.last.get_by_context(models.CollectionPageContext)
        while current is not None:
            backward_visited.add(current.reference.uri)
            if current.previous:
                current = current.previous.get_by_context(models.CollectionPageContext)
            else:
                break

        self.assertEqual(
            forward_visited,
            page_uris,
            "All pages should be reachable from first via next chain",
        )
        self.assertEqual(
            backward_visited,
            page_uris,
            "All pages should be reachable from last via prev chain",
        )


@override_settings(
    FEDERATION={"DEFAULT_URL": "http://testserver", "FORCE_INSECURE_HTTP": True},
    ALLOWED_HOSTS=["testserver"],
)
class CollectionAppendTestCase(BaseTestCase):
    def setUp(self):
        self.domain = DomainFactory(scheme="http", name="testserver", local=True)

    def test_append_to_ordered_collection_goes_to_first_page(self):
        collection = CollectionFactory(
            reference__domain=self.domain,
            type=models.CollectionContext.Types.ORDERED,
        )
        collection.make_page()

        item = ReferenceFactory(domain=self.domain)
        collection.append(item)

        first_page = collection.first.get_by_context(models.CollectionPageContext)
        self.assertTrue(first_page.contains(item))

    def test_append_creates_new_page_when_full(self):
        """When collection has no pages and fills up, append creates a page and migrates items."""
        collection = CollectionFactory(
            reference__domain=self.domain,
            type=models.CollectionContext.Types.ORDERED,
        )

        page_size = models.CollectionPageContext.PAGE_SIZE

        for i in range(page_size):
            item = ReferenceFactory(domain=self.domain)
            collection.append(item)

        self.assertEqual(collection.pages.count(), 0)
        self.assertEqual(collection.collection_items.count(), page_size)
        self.assertEqual(collection.total_items, page_size)

        extra_item = ReferenceFactory(domain=self.domain)
        collection.append(extra_item)

        collection.refresh_from_db()
        self.assertEqual(collection.pages.count(), 1)
        self.assertIsNotNone(collection.first)

        first_page = collection.first.get_by_context(models.CollectionPageContext)
        self.assertTrue(first_page.contains(extra_item))
        self.assertEqual(first_page.collection_items.count(), page_size + 1)
        self.assertEqual(collection.total_items, page_size + 1)

    def test_append_to_ordered_multi_page_goes_to_newest_page(self):
        collection = CollectionFactory(
            reference__domain=self.domain,
            type=models.CollectionContext.Types.ORDERED,
        )
        collection.make_page()
        page_size = models.CollectionPageContext.PAGE_SIZE

        for i in range(page_size * 2):
            item = ReferenceFactory(domain=self.domain)
            collection.append(item)

        self.assertEqual(collection.pages.count(), 2)

        new_item = ReferenceFactory(domain=self.domain)
        collection.append(new_item)

        first_page = collection.first.get_by_context(models.CollectionPageContext)
        self.assertTrue(
            first_page.contains(new_item),
            "New items should go to first (newest) page",
        )

    def test_append_same_item_twice_returns_existing(self):
        collection = CollectionFactory(
            reference__domain=self.domain,
            type=models.CollectionContext.Types.ORDERED,
        )
        collection.make_page()

        item = ReferenceFactory(domain=self.domain)
        result1 = collection.append(item)
        result2 = collection.append(item)

        self.assertEqual(result1, result2)
        self.assertEqual(collection.total_items, 1)

    def test_append_to_full_page_creates_new_page(self):
        """When a page is full, append should create a new page."""
        collection = CollectionFactory(
            reference__domain=self.domain,
            type=models.CollectionContext.Types.ORDERED,
        )
        page = collection.make_page()
        page_size = models.CollectionPageContext.PAGE_SIZE

        items = []
        for i in range(page_size):
            item = ReferenceFactory(domain=self.domain)
            collection.append(item)
            items.append(item)

        self.assertEqual(collection.pages.count(), 1)
        self.assertEqual(page.collection_items.count(), page_size)

        extra_item = ReferenceFactory(domain=self.domain)
        collection.append(extra_item)
        collection.refresh_from_db()

        self.assertEqual(collection.pages.count(), 2)

        first_page = collection.first.get_by_context(models.CollectionPageContext)
        self.assertTrue(
            first_page.contains(extra_item), "New item should be in first (newest) page"
        )

    def test_items_migrated_to_page_when_collection_becomes_paginated(self):
        collection = CollectionFactory(
            reference__domain=self.domain,
            type=models.CollectionContext.Types.ORDERED,
        )

        page_size = models.CollectionPageContext.PAGE_SIZE
        items = [ReferenceFactory(domain=self.domain) for _ in range(page_size)]

        for item in items:
            collection.append(item)

        self.assertEqual(collection.pages.count(), 0)
        self.assertEqual(collection.collection_items.count(), page_size)
        self.assertEqual(collection.total_items, page_size)

        extra_item = ReferenceFactory(domain=self.domain)
        collection.append(extra_item)
        collection.refresh_from_db()

        self.assertEqual(collection.pages.count(), 1)
        self.assertEqual(
            collection.collection_items.count(),
            0,
            "Items should be migrated from collection to page",
        )

        first_page = collection.first.get_by_context(models.CollectionPageContext)
        self.assertEqual(first_page.collection_items.count(), page_size + 1)

        for item in items:
            self.assertTrue(
                first_page.contains(item), f"Original item {item.uri} should be in page"
            )

        page_items = list(first_page.items)
        self.assertEqual(page_items[0].item, extra_item, "Newest item should be first")
        self.assertEqual(page_items[-1].item, items[0], "Oldest item should be last")


@override_settings(
    FEDERATION={"DEFAULT_URL": "http://testserver", "FORCE_INSECURE_HTTP": True},
    ALLOWED_HOSTS=["testserver"],
)
class CollectionMakePageTestCase(BaseTestCase):
    def setUp(self):
        self.domain = DomainFactory(scheme="http", name="testserver", local=True)

    def test_make_page_sets_first_and_last_on_first_page(self):
        collection = CollectionFactory(
            reference__domain=self.domain,
            type=models.CollectionContext.Types.ORDERED,
        )

        page = collection.make_page()

        self.assertEqual(collection.first, page.reference)
        self.assertEqual(collection.last, page.reference)

    def test_make_page_updates_last_on_subsequent_pages(self):
        collection = CollectionFactory(
            reference__domain=self.domain,
            type=models.CollectionContext.Types.ORDERED,
        )

        collection.make_page()
        collection.make_page()

        self.assertIsNotNone(collection.last, "last should be set after second page")

        collection.make_page()
        self.assertIsNotNone(collection.last, "last should remain set after third page")

    def test_make_page_no_dangling_pages(self):
        collection = CollectionFactory(
            reference__domain=self.domain,
            type=models.CollectionContext.Types.ORDERED,
        )

        pages = [collection.make_page() for _ in range(5)]

        all_page_uris = set(p.reference.uri for p in pages)

        reachable_uris = set()
        current = collection.first.get_by_context(models.CollectionPageContext)
        while current is not None:
            reachable_uris.add(current.reference.uri)
            if current.next:
                current = current.next.get_by_context(models.CollectionPageContext)
            else:
                break

        self.assertEqual(
            reachable_uris,
            all_page_uris,
            "No pages should be dangling - all must be reachable from first",
        )
