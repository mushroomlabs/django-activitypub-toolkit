from datetime import datetime, timezone

from .. import factories, models
from ..contexts import AS2, SEC_V1_CONTEXT, SECv1
from ..projections import (
    ActorProjection,
    CollectionPageProjection,
    CollectionProjection,
    CollectionWithFirstPageProjection,
    ReferenceProjection,
)
from .base import BaseTestCase


class ReferenceProjectionTestCase(BaseTestCase):
    def test_can_project_object_with_basic_fields(self):
        """Test projecting an object with string and datetime fields"""
        obj = factories.ObjectFactory(
            reference__uri="https://example.com/objects/test",
            type=models.ObjectContext.Types.NOTE,
            name="Test Note",
            content="This is a simple note",
        )

        projection = ReferenceProjection(obj.reference)
        projection.build()
        data = projection.get_expanded()

        # Check that type is output as @type
        self.assertIn("@type", data)
        self.assertEqual(data["@type"], models.ObjectContext.Types.NOTE)

        # Check that other predicates are full URIs
        self.assertIn(str(AS2.name), data)
        self.assertIn(str(AS2.content), data)

        # Check values are in expanded form
        self.assertEqual(data[str(AS2.name)], [{"@value": "Test Note"}])
        self.assertEqual(data[str(AS2.content)], [{"@value": "This is a simple note"}])

    def test_can_project_reference_fields(self):
        """Test projecting reference fields (ForeignKey to Reference)"""
        actor = factories.ActorFactory(reference__uri="https://example.com/users/alice")
        obj = factories.ObjectFactory(
            reference__uri="https://example.com/objects/test",
            type=models.ObjectContext.Types.NOTE,
            content="A note",
        )
        obj.attributed_to.add(actor.reference)

        projection = ReferenceProjection(obj.reference)
        projection.build()
        data = projection.get_expanded()

        # Check that reference field is projected as URI
        self.assertIn(str(AS2.attributedTo), data)
        self.assertEqual(data[str(AS2.attributedTo)], [{"@id": "https://example.com/users/alice"}])

    def test_can_project_multiple_references(self):
        """Test projecting ReferenceField (Many-to-Many)"""
        alice = factories.ActorFactory(reference__uri="https://example.com/users/alice")
        bob = factories.ActorFactory(reference__uri="https://example.com/users/bob")

        obj = factories.ObjectFactory(
            reference__uri="https://example.com/objects/test",
            type=models.ObjectContext.Types.NOTE,
        )
        obj.to.add(alice.reference, bob.reference)

        projection = ReferenceProjection(obj.reference)
        projection.build()
        data = projection.get_expanded()

        # Check that multiple references are projected
        self.assertIn(str(AS2.to), data)
        self.assertEqual(len(data[str(AS2.to)]), 2)
        uris = [ref["@id"] for ref in data[str(AS2.to)]]
        self.assertIn("https://example.com/users/alice", uris)
        self.assertIn("https://example.com/users/bob", uris)

    def test_skips_none_values(self):
        """Test that None values are not included in projection"""
        obj = factories.ObjectFactory(
            reference__uri="https://example.com/objects/test",
            type=models.ObjectContext.Types.NOTE,
            content="A note",
            name=None,  # Explicitly None
        )

        projection = ReferenceProjection(obj.reference)
        projection.build()
        data = projection.get_expanded()

        # Name should not be in output
        self.assertNotIn(str(AS2.name), data)
        # Content should be
        self.assertIn(str(AS2.content), data)

    def test_projects_datetime_with_type(self):
        """Test that DateTimeField is projected with proper XSD type"""
        obj = factories.ObjectFactory(
            reference__uri="https://example.com/objects/test",
            type=models.ObjectContext.Types.NOTE,
            published=datetime(2023, 11, 16, 12, 0, 0, tzinfo=timezone.utc),
        )

        projection = ReferenceProjection(obj.reference)
        projection.build()
        data = projection.get_expanded()

        # Check datetime projection
        self.assertIn(str(AS2.published), data)
        published_data = data[str(AS2.published)][0]
        self.assertIn("@value", published_data)
        self.assertIn("@type", published_data)
        self.assertEqual(published_data["@type"], "http://www.w3.org/2001/XMLSchema#dateTime")
        self.assertEqual(published_data["@value"], "2023-11-16T12:00:00+00:00")


class CollectionProjectionTestCase(BaseTestCase):
    def setUp(self):
        self.local_domain = factories.DomainFactory(
            scheme="http", name="testserver", local=True, port=80
        )

    def test_can_project_collection_page_with_items(self):
        """Test that a collection page projects with its items"""
        collection_ref = factories.ReferenceFactory(
            domain=self.local_domain, path="/collections/test"
        )
        collection = models.CollectionContext.make(
            reference=collection_ref,
            type=models.CollectionContext.Types.UNORDERED,
        )
        item_refs = []
        for i in range(3):
            item_ref = factories.ReferenceFactory(domain=self.local_domain, path=f"/items/{i}")
            collection.append(item_ref)
            item_refs.append(item_ref)

        # Get the first page that was created
        page = collection.pages.first()
        self.assertIsNotNone(page, "Collection should have created a page")

        # Project the collection page
        projection = CollectionPageProjection(page.reference)
        projection.build()
        data = projection.get_expanded()

        # Verify items are in the projected data
        self.assertIn(str(AS2.items), data)
        items_data = data[str(AS2.items)]

        # Should have 3 items
        self.assertEqual(len(items_data), 3)

        # Each item should be a reference with @id
        item_uris = [item["@id"] for item in items_data]
        self.assertIn("http://testserver/items/0", item_uris)
        self.assertIn("http://testserver/items/1", item_uris)
        self.assertIn("http://testserver/items/2", item_uris)

    def test_collection_projection_includes_total_items(self):
        collection_ref = factories.ReferenceFactory(
            domain=self.local_domain, path="/collections/test"
        )
        collection = models.CollectionContext.objects.create(
            reference=collection_ref,
            type=models.CollectionContext.Types.UNORDERED,
        )

        # Add some items
        for i in range(3):
            item_ref = factories.ReferenceFactory(domain=self.local_domain, path=f"/items/{i}")
            collection.append(item_ref)

        # Use CollectionProjection
        projection = CollectionProjection(collection.reference)
        projection.build()
        expanded = projection.get_expanded()

        # Should have totalItems in expanded form
        self.assertIn(str(AS2.totalItems), expanded)
        total_items_data = expanded[str(AS2.totalItems)]
        self.assertIsInstance(total_items_data, list)
        self.assertEqual(len(total_items_data), 1)
        self.assertEqual(total_items_data[0]["@value"], 3)
        self.assertEqual(
            total_items_data[0]["@type"], "http://www.w3.org/2001/XMLSchema#nonNegativeInteger"
        )

    def test_collection_projection_includes_items(self):
        collection_ref = factories.ReferenceFactory(
            domain=self.local_domain, path="/collections/test"
        )
        collection = models.CollectionContext.objects.create(
            reference=collection_ref,
            type=models.CollectionContext.Types.UNORDERED,
        )

        # Add some items
        item_refs = []
        for i in range(2):
            item_ref = factories.ReferenceFactory(domain=self.local_domain, path=f"/items/{i}")
            collection.append(item_ref)
            item_refs.append(item_ref)

        # Use CollectionProjection
        projection = CollectionProjection(collection.reference)
        projection.build()
        expanded = projection.get_expanded()

        # Should have items in expanded form
        self.assertIn(str(AS2.items), expanded)
        items_data = expanded[str(AS2.items)]
        self.assertIsInstance(items_data, list)
        self.assertEqual(len(items_data), 2)

        # Each item should be a reference
        item_uris = [item["@id"] for item in items_data]
        self.assertIn("http://testserver/items/0", item_uris)
        self.assertIn("http://testserver/items/1", item_uris)

    def test_collection_projection_compacted(self):
        collection_ref = factories.ReferenceFactory(
            domain=self.local_domain, path="/collections/test"
        )
        collection = models.CollectionContext.objects.create(
            reference=collection_ref,
            type=models.CollectionContext.Types.ORDERED,
            name="Test Collection",
        )

        # Add some items
        for i in range(3):
            item_ref = factories.ReferenceFactory(domain=self.local_domain, path=f"/items/{i}")
            collection.append(item_ref)

        # Use CollectionProjection
        projection = CollectionProjection(collection.reference)
        projection.build()
        compacted = projection.get_compacted()

        # Should have @context
        self.assertIn("@context", compacted)

        # Should have basic fields
        self.assertEqual(compacted["id"], "http://testserver/collections/test")
        self.assertEqual(compacted["type"], "OrderedCollection")
        self.assertEqual(compacted["name"], "Test Collection")

        # Should have totalItems
        self.assertIn("totalItems", compacted)
        self.assertEqual(compacted["totalItems"], 3)

        # Should have items
        self.assertIn("orderedItems", compacted)
        self.assertIsInstance(compacted["orderedItems"], list)
        self.assertEqual(len(compacted["orderedItems"]), 3)


class SecV1ProjectionTestCase(BaseTestCase):
    def test_projects_public_key_and_owner(self):
        """Test that SecV1Context projects public key and owner"""
        owner = factories.ActorFactory(reference__uri="https://example.com/users/alice")

        # Create a SecV1Context
        keypair_ref = factories.ReferenceFactory(uri="https://example.com/users/alice#main-key")
        secv1 = models.SecV1Context.objects.create(
            reference=keypair_ref,
            public_key_pem="-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----",
        )
        secv1.owner.add(owner.reference)

        # Project
        projection = ReferenceProjection(secv1.reference, scope={"viewer": None})
        projection.build()
        data = projection.get_expanded()

        # Should have owner and public key
        self.assertIn(str(SECv1.owner), data)
        self.assertIn(str(SECv1.publicKeyPem), data)

        # Check values
        self.assertEqual(data[str(SECv1.owner)], [{"@id": "https://example.com/users/alice"}])
        self.assertEqual(
            data[str(SECv1.publicKeyPem)][0]["@value"],
            "-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----",
        )


class CollectionWithFirstPageProjectionTestCase(BaseTestCase):
    """
    Test CollectionWithFirstPageProjection which embeds the first page.
    """

    def setUp(self):
        self.domain = factories.DomainFactory(
            scheme="http", name="testserver", local=True, port=80
        )

    def test_collection_embeds_first_page(self):
        factories.ActorFactory(preferred_username="alice", reference__domain=self.domain)

        # Create a collection with items
        collection_ref = models.Reference.make("http://testserver/collections/test")
        collection = models.CollectionContext.make(
            reference=collection_ref,
            type=models.CollectionContext.Types.UNORDERED,
        )

        # Add some items
        for i in range(3):
            item_ref = models.Reference.make(f"http://testserver/items/{i}")
            collection.append(item=item_ref)

        # Use CollectionWithFirstPageProjection
        projection = CollectionWithFirstPageProjection(collection_ref)
        projection.build()
        data = projection.get_expanded()

        # Should NOT have items (omitted)
        self.assertNotIn(str(AS2.items), data)

        # Should have first (embedded)
        self.assertIn(str(AS2.first), data)
        first_data = data[str(AS2.first)]
        self.assertIsInstance(first_data, list)
        self.assertEqual(len(first_data), 1)

        # First should be embedded (has @type, items, etc.)
        first_page = first_data[0]
        self.assertIn("@type", first_page)
        # The first page should have items
        self.assertTrue(str(AS2.items) in first_page)


class ActorProjectionTestCase(BaseTestCase):
    """Test ActorProjection which adds publicKey via extra fields"""

    def test_actor_includes_public_key_expanded(self):
        """Test that ActorProjection includes embedded public key in expanded form"""
        domain = factories.DomainFactory(scheme="http", name="testserver", local=True, port=80)
        actor = factories.ActorFactory(preferred_username="alice", reference__domain=domain)

        # Create a public key for the actor
        keypair_ref = models.Reference.make("http://testserver/keys/alice-main-key")
        secv1 = models.SecV1Context.objects.create(
            reference=keypair_ref,
            public_key_pem="-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----",
        )
        secv1.owner.add(actor.reference)

        # Use ActorProjection
        projection = ActorProjection(actor.reference)
        projection.build()
        data = projection.get_expanded()

        # Should have publicKey in expanded form
        self.assertIn(str(SECv1.publicKey), data)
        public_keys = data[str(SECv1.publicKey)]
        self.assertIsInstance(public_keys, list)
        self.assertEqual(len(public_keys), 1)

        # Public key should be embedded with expanded predicates
        public_key = public_keys[0]
        self.assertIn("@id", public_key)
        self.assertEqual(public_key["@id"], "http://testserver/keys/alice-main-key")
        self.assertIn(str(SECv1.publicKeyPem), public_key)
        self.assertIn(str(SECv1.owner), public_key)

    def test_actor_includes_public_key_compacted(self):
        """Test that ActorProjection includes compacted public key with proper context"""
        domain = factories.DomainFactory(scheme="http", name="testserver", local=True, port=80)
        actor = factories.ActorFactory(preferred_username="alice", reference__domain=domain)

        # Create a public key for the actor
        keypair_ref = models.Reference.make("http://testserver/keys/alice-main-key")
        secv1 = models.SecV1Context.objects.create(
            reference=keypair_ref,
            public_key_pem="ALICE_KEY_PEM",
        )
        secv1.owner.add(actor.reference)

        # Use ActorProjection
        projection = ActorProjection(actor.reference)
        projection.build()

        # Check that security context was registered
        self.assertIn(SEC_V1_CONTEXT.url, projection.seen_contexts)

        compacted = projection.get_compacted()

        # Should have @context with security context
        self.assertIn("@context", compacted)
        self.assertIn(SEC_V1_CONTEXT.url, compacted["@context"])

        # Should have publicKey in compacted form (not full URI)
        self.assertIn("publicKey", compacted)
        self.assertNotIn(str(SECv1.publicKey), compacted)

        # Public key should be compacted object
        public_key = compacted["publicKey"]
        self.assertIsInstance(public_key, dict)
        self.assertEqual(public_key["id"], "http://testserver/keys/alice-main-key")

        # Nested fields should also be compacted
        self.assertIn("owner", public_key)
        self.assertNotIn(str(SECv1.owner), public_key)
        self.assertEqual(public_key["owner"], "http://testserver/users/alice")

        self.assertIn("publicKeyPem", public_key)
        self.assertNotIn(str(SECv1.publicKeyPem), public_key)
        self.assertEqual(public_key["publicKeyPem"], "ALICE_KEY_PEM")


class CompactedOutputTestCase(BaseTestCase):
    """Test that get_compacted() produces proper compacted JSON-LD"""

    def test_compacted_output_has_context(self):
        """Test that compacted output includes @context"""
        domain = factories.DomainFactory(scheme="http", name="testserver", local=True, port=80)
        actor = factories.ActorFactory(preferred_username="bob", reference__domain=domain)

        note = models.ObjectContext.objects.create(
            reference=models.Reference.make("http://testserver/notes/456"),
            type=models.ObjectContext.Types.NOTE,
            content="Test content",
        )
        note.attributed_to.add(actor.reference)

        # Project and compact
        projection = ReferenceProjection(note.reference)
        projection.build()
        compacted = projection.get_compacted()

        # Should have @context
        self.assertIn("@context", compacted)
        self.assertIsInstance(compacted["@context"], list)
        self.assertIn("https://www.w3.org/ns/activitystreams", compacted["@context"])

        # Should have compact keys
        self.assertIn("content", compacted)
        self.assertIn("attributedTo", compacted)

        # Should NOT have expanded keys
        self.assertNotIn(str(AS2.content), compacted)
        self.assertNotIn(str(AS2.attributedTo), compacted)

    def test_compacted_output_preserves_values(self):
        """Test that compaction preserves the actual values"""
        obj = factories.ObjectFactory(
            reference__uri="https://example.com/objects/compact-test",
            type=models.ObjectContext.Types.NOTE,
            name="Compact Test",
            content="This is content",
            published=datetime(2024, 11, 16, 12, 0, 0, tzinfo=timezone.utc),
        )

        projection = ReferenceProjection(obj.reference)
        projection.build()
        compacted = projection.get_compacted()

        # Check values are preserved
        self.assertEqual(compacted["id"], "https://example.com/objects/compact-test")
        self.assertEqual(compacted["type"], "Note")
        self.assertEqual(compacted["name"], "Compact Test")
        self.assertEqual(compacted["content"], "This is content")
        self.assertEqual(compacted["published"], "2024-11-16T12:00:00+00:00")
