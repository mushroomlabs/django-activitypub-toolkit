from datetime import datetime, timezone

from .. import factories, models
from ..schemas import AS2, SECv1
from ..serializers import CollectionContextSerializer, ContextModelSerializer
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
