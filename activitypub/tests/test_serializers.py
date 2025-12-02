from datetime import datetime, timezone

from .. import factories, models
from ..contexts import AS2, SECv1
from ..serializers import (
    CollectionContextSerializer,
    ContextModelSerializer,
    EmbeddedActorContextSerializer,
    EmbeddedCollectionContextSerializer,
    LinkedDataSerializer,
)

from .base import BaseTestCase


class ContextModelSerializerTestCase(BaseTestCase):
    def test_can_serialize_object_with_basic_fields(self):
        """Test serializing an object with string and datetime fields"""
        obj = factories.ObjectFactory(
            reference__uri="https://example.com/objects/test",
            type=models.ObjectContext.Types.NOTE,
            name="Test Note",
            content="This is a simple note",
        )

        serializer = ContextModelSerializer(obj)
        data = serializer.data

        # Check that type is output as @type
        self.assertIn("@type", data)
        self.assertEqual(data["@type"], models.ObjectContext.Types.NOTE)

        # Check that other predicates are full URIs
        self.assertIn(str(AS2.name), data)
        self.assertIn(str(AS2.content), data)

        # Check values are in expanded form
        self.assertEqual(data[str(AS2.name)], [{"@value": "Test Note"}])
        self.assertEqual(data[str(AS2.content)], [{"@value": "This is a simple note"}])

    def test_can_serialize_reference_fields(self):
        """Test serializing reference fields (ForeignKey to Reference)"""
        actor = factories.ActorFactory(reference__uri="https://example.com/users/alice")
        obj = factories.ObjectFactory(
            reference__uri="https://example.com/objects/test",
            type=models.ObjectContext.Types.NOTE,
            content="A note",
        )
        obj.attributed_to.add(actor.reference)

        serializer = ContextModelSerializer(obj)
        data = serializer.data

        # Check that reference field is serialized as URI
        self.assertIn(str(AS2.attributedTo), data)
        self.assertEqual(data[str(AS2.attributedTo)], [{"@id": "https://example.com/users/alice"}])

    def test_can_serialize_multiple_references(self):
        """Test serializing ReferenceField (Many-to-Many)"""
        alice = factories.ActorFactory(reference__uri="https://example.com/users/alice")
        bob = factories.ActorFactory(reference__uri="https://example.com/users/bob")

        obj = factories.ObjectFactory(
            reference__uri="https://example.com/objects/test",
            type=models.ObjectContext.Types.NOTE,
        )
        obj.to.add(alice.reference, bob.reference)

        serializer = ContextModelSerializer(obj)
        data = serializer.data

        # Check that multiple references are serialized
        self.assertIn(str(AS2.to), data)
        self.assertEqual(len(data[str(AS2.to)]), 2)
        uris = [ref["@id"] for ref in data[str(AS2.to)]]
        self.assertIn("https://example.com/users/alice", uris)
        self.assertIn("https://example.com/users/bob", uris)

    def test_skips_none_values(self):
        """Test that None values are not included in serialization"""
        obj = factories.ObjectFactory(
            reference__uri="https://example.com/objects/test",
            type=models.ObjectContext.Types.NOTE,
            content="A note",
            name=None,  # Explicitly None
        )

        serializer = ContextModelSerializer(obj)
        data = serializer.data

        # Name should not be in output
        self.assertNotIn(str(AS2.name), data)
        # Content should be
        self.assertIn(str(AS2.content), data)

    def test_serializes_datetime_with_type(self):
        """Test that DateTimeField is serialized with proper XSD type"""
        obj = factories.ObjectFactory(
            reference__uri="https://example.com/objects/test",
            type=models.ObjectContext.Types.NOTE,
            published=datetime(2023, 11, 16, 12, 0, 0, tzinfo=timezone.utc),
        )

        serializer = ContextModelSerializer(obj)
        data = serializer.data

        # Check datetime serialization
        self.assertIn(str(AS2.published), data)
        published_data = data[str(AS2.published)][0]
        self.assertIn("@value", published_data)
        self.assertIn("@type", published_data)
        self.assertEqual(published_data["@type"], "http://www.w3.org/2001/XMLSchema#dateTime")
        self.assertEqual(published_data["@value"], "2023-11-16T12:00:00+00:00")


class CollectionSerializerTestCase(BaseTestCase):
    def test_can_serialize_collection_with_items(self):
        """Test that a collection serializes with its items"""
        domain = factories.DomainFactory(scheme="http", name="testserver", local=True)
        collection_ref = factories.ReferenceFactory(domain=domain, path="/collections/test")
        collection = models.CollectionContext.objects.create(
            reference=collection_ref,
            type=models.CollectionContext.Types.UNORDERED,
        )
        item_refs = []
        for i in range(3):
            item_ref = factories.ReferenceFactory(domain=domain, path=f"/items/{i}")
            collection.append(item_ref)
            item_refs.append(item_ref)

        # Serialize the collection
        serializer = CollectionContextSerializer(collection)
        data = serializer.data

        # Verify items are in the serialized data
        self.assertIn(str(AS2.items), data)
        items_data = data[str(AS2.items)]

        # Should have 3 items
        self.assertEqual(len(items_data), 3)

        # Each item should be a reference with @id
        item_uris = [item["@id"] for item in items_data]
        self.assertIn("http://testserver/items/0", item_uris)
        self.assertIn("http://testserver/items/1", item_uris)
        self.assertIn("http://testserver/items/2", item_uris)


class SecV1SerializerTestCase(BaseTestCase):
    def test_serializes_public_key_and_owner(self):
        """Test that SecV1Context serializes public key and owner"""
        owner = factories.ActorFactory(reference__uri="https://example.com/users/alice")

        # Create a SecV1Context
        keypair_ref = factories.ReferenceFactory(uri="https://example.com/users/alice#main-key")
        secv1 = models.SecV1Context.objects.create(
            reference=keypair_ref,
            public_key_pem="-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----",
        )
        secv1.owner.add(owner.reference)

        # Serialize
        serializer = ContextModelSerializer(secv1, context={"viewer": None})
        data = serializer.data

        # Should have owner and public key
        self.assertIn(str(SECv1.owner), data)
        self.assertIn(str(SECv1.publicKeyPem), data)

        # Check values
        self.assertEqual(data[str(SECv1.owner)], [{"@id": "https://example.com/users/alice"}])
        self.assertEqual(
            data[str(SECv1.publicKeyPem)][0]["@value"],
            "-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----",
        )


class EmbeddedSerializationTestCase(BaseTestCase):
    """
    Test that serializers correctly handle embedded vs main subject context.

    When serializing as the main subject (embedded=False), all fields should
    be present. When embedded (embedded=True), simplified serializers omit
    collection fields and other verbose data.
    """

    def setUp(self):
        self.domain = factories.DomainFactory(scheme="http", name="testserver", local=True)

    def test_collection_omits_items_when_embedded(self):
        """Test that embedded collections omit items"""
        factories.AccountFactory(username="alice", domain=self.domain)

        # Create a collection with items
        collection_ref = models.Reference.make("http://testserver/collections/test")
        collection = models.CollectionContext.objects.create(
            reference=collection_ref,
            type=models.CollectionContext.Types.UNORDERED,
        )

        # Add some items
        for i in range(3):
            item_ref = models.Reference.make(f"http://testserver/items/{i}")
            collection.append(item=item_ref)

        # Main serialization - includes items
        serializer = LinkedDataSerializer(collection_ref, embedded=False)
        main_data = serializer.data
        self.assertIn(str(AS2.items), main_data)

        # Embedded serialization - omits items
        serializer_embedded = LinkedDataSerializer(collection_ref, embedded=True)
        embedded_data = serializer_embedded.data
        self.assertNotIn(str(AS2.items), embedded_data)

        # But @id should still be there
        self.assertEqual(embedded_data["@id"], "http://testserver/collections/test")

    def test_serializer_preserves_non_omitted_predicates(self):
        """Test that serializers preserve predicates not omitted"""
        account = factories.AccountFactory(username="bob", domain=self.domain)
        actor = account.actor

        note = models.ObjectContext.objects.create(
            reference=models.Reference.make("http://testserver/notes/123"),
            type=models.ObjectContext.Types.NOTE,
            content="Hello, Fediverse!",
            name="Test Note",
            published=datetime(2024, 11, 16, 12, 0, 0, tzinfo=timezone.utc),
        )
        note.attributed_to.add(actor.reference)

        # Serialize (both main and embedded behave the same for ObjectContext)
        serializer = LinkedDataSerializer(note.reference, embedded=False)
        data = serializer.data

        # Verify all fields are preserved (still in expanded form)
        self.assertEqual(data["@id"], "http://testserver/notes/123")
        self.assertIn(str(AS2.name), data)
        self.assertIn(str(AS2.content), data)
        self.assertIn(str(AS2.published), data)
        self.assertIn(str(AS2.attributedTo), data)

    def test_actor_omits_collections_when_embedded(self):
        """Test that embedded actors omit inbox/outbox/followers/following"""
        account = factories.AccountFactory(username="alice", domain=self.domain)
        actor = account.actor

        # Main serialization - includes collections
        serializer = LinkedDataSerializer(actor.reference, embedded=False)
        main_data = serializer.data

        # Note: inbox/outbox use Path objects (LDP.inbox | AS2.inbox)
        # so they appear with a different key
        # Check that inbox and outbox appear in some form
        has_inbox = any("inbox" in str(k) for k in main_data.keys())
        has_outbox = any("outbox" in str(k) for k in main_data.keys())
        self.assertTrue(has_inbox, f"No inbox found in keys: {list(main_data.keys())}")
        self.assertTrue(has_outbox, f"No outbox found in keys: {list(main_data.keys())}")

        # Embedded serialization - omits collections
        serializer_embedded = LinkedDataSerializer(actor.reference, embedded=True)
        embedded_data = serializer_embedded.data

        # Check that inbox/outbox are NOT present
        has_inbox_emb = any("inbox" in str(k) for k in embedded_data.keys())
        has_outbox_emb = any("outbox" in str(k) for k in embedded_data.keys())
        self.assertFalse(
            has_inbox_emb, f"Inbox unexpectedly found in keys: {list(embedded_data.keys())}"
        )
        self.assertFalse(
            has_outbox_emb, f"Outbox unexpectedly found in keys: {list(embedded_data.keys())}"
        )

        self.assertNotIn(str(AS2.followers), embedded_data)
        self.assertNotIn(str(AS2.following), embedded_data)

        # But basic fields should still be there
        self.assertIn(str(AS2.preferredUsername), embedded_data)

    def test_serializer_output_is_expanded(self):
        """Test that serializer output is in expanded form (full URIs)"""
        account = factories.AccountFactory(username="bob", domain=self.domain)
        actor = account.actor

        note = models.ObjectContext.objects.create(
            reference=models.Reference.make("http://testserver/notes/456"),
            type=models.ObjectContext.Types.NOTE,
            content="Test content",
        )
        note.attributed_to.add(actor.reference)

        # Serialize
        serializer = LinkedDataSerializer(note.reference, embedded=False)
        data = serializer.data

        # Verify output is still expanded (uses full URIs)
        self.assertIn(str(AS2.content), data)
        self.assertIn(str(AS2.attributedTo), data)

        # Should NOT have compact keys
        self.assertNotIn("content", data)
        self.assertNotIn("attributedTo", data)

        # Should NOT have @context (that's added during compaction)
        self.assertNotIn("@context", data)

    def test_embedded_actor_serializer_omits_fields(self):
        """Test that EmbeddedActorContextSerializer directly omits fields"""
        account = factories.AccountFactory(username="alice", domain=self.domain)
        actor_context = account.actor

        # Use embedded serializer directly
        serializer = EmbeddedActorContextSerializer(actor_context)
        data = serializer.data

        # Verify collections are omitted
        self.assertNotIn(str(AS2.inbox), data)
        self.assertNotIn(str(AS2.outbox), data)
        self.assertNotIn(str(AS2.followers), data)
        self.assertNotIn(str(AS2.following), data)

    def test_embedded_collection_serializer_omits_fields(self):
        """Test that EmbeddedCollectionContextSerializer omits items"""
        collection_ref = models.Reference.make("http://testserver/collections/test")
        collection = models.CollectionContext.objects.create(
            reference=collection_ref,
            type=models.CollectionContext.Types.UNORDERED,
        )

        # Add items
        for i in range(3):
            item_ref = models.Reference.make(f"http://testserver/items/{i}")
            collection.append(item=item_ref)

        # Use embedded serializer directly
        serializer = EmbeddedCollectionContextSerializer(collection)
        data = serializer.data

        # Verify items are omitted
        self.assertNotIn(str(AS2.items), data)
        self.assertNotIn(str(AS2.orderedItems), data)

        # But totalItems should still be there
        self.assertIn(str(AS2.totalItems), data)
