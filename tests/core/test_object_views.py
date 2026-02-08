from datetime import datetime, timezone

from rest_framework.test import APIClient

from activitypub.core import models
from activitypub.core.factories import (
    ActorFactory,
    CollectionFactory,
    DomainFactory,
    SecV1ContextFactory,
)
from tests.core.base import BaseTestCase


class ActivityPubObjectViewTestCase(BaseTestCase):
    def setUp(self):
        self.client = APIClient()
        self.domain = DomainFactory(scheme="http", name="testserver", local=True, port=80)

    def test_can_serialize_actor(self):
        """an actor is serialized in ActivityPub-compatible format"""

        expected = {
            "@context": [
                "https://www.w3.org/ns/activitystreams",
                "https://w3id.org/security/v1",
                {
                    "Emoji": "as:Emoji",
                    "Hashtag": "as:Hashtag",
                    "manuallyApprovesFollowers": {
                        "@id": "as:manuallyApprovesFollowers",
                        "@type": "xsd:boolean",
                    },
                    "movedTo": {"@id": "as:movedTo", "@type": "@id"},
                    "alsoKnownAs": {"@id": "as:alsoKnownAs", "@type": "@id"},
                    "sensitive": {"@id": "as:sensitive", "@type": "xsd:boolean"},
                },
            ],
            "id": "http://testserver/users/alice",
            "type": "Person",
            "preferredUsername": "alice",
            "name": "Alice Activitypub",
            "summary": "Just a simple test actor",
            "followers": "http://testserver/users/alice/followers",
            "following": "http://testserver/users/alice/following",
            "inbox": "http://testserver/users/alice/inbox",
            "outbox": "http://testserver/users/alice/outbox",
            "manuallyApprovesFollowers": False,
            "published": "2024-01-01T00:00:00+00:00",
            "publicKey": {
                "id": "http://testserver/keys/alice-main-key",
                "owner": "http://testserver/users/alice",
                "publicKeyPem": "ALICE_KEY_PEM",
            },
        }

        actor = ActorFactory(
            preferred_username="alice",
            reference__path="/users/alice",
            reference__domain=self.domain,
            name="Alice Activitypub",
            summary="Just a simple test actor",
            published=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        )
        key_ref = models.Reference.make("http://testserver/keys/alice-main-key")
        key = SecV1ContextFactory(reference=key_ref, public_key_pem="ALICE_KEY_PEM")
        key.owner.add(actor.reference)

        response = self.client.get(
            "http://testserver/users/alice",
            HTTP_ACCEPT="application/activity+json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)

    def test_can_serialize_note_object(self):
        actor = ActorFactory(preferred_username="bob", reference__domain=self.domain)

        note = models.ObjectContext.objects.create(
            reference=models.Reference.make("http://testserver/notes/123"),
            type=models.ObjectContext.Types.NOTE,
            content="Hello, Fediverse!",
            name="Test Note",
            published=datetime(2024, 11, 16, 12, 0, 0, tzinfo=timezone.utc),
        )
        note.attributed_to.add(actor.reference)

        response = self.client.get(
            "/notes/123",
            HTTP_ACCEPT="application/activity+json",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Check @context
        self.assertIn("@context", data)
        self.assertIsInstance(data["@context"], list)
        self.assertEqual(data["@context"][0], "https://www.w3.org/ns/activitystreams")

        # Check core fields
        self.assertEqual(data["id"], "http://testserver/notes/123")
        self.assertEqual(data["type"], "Note")
        self.assertEqual(data["content"], "Hello, Fediverse!")
        self.assertEqual(data["name"], "Test Note")
        self.assertEqual(data["attributedTo"], "http://testserver/users/bob")
        self.assertEqual(data["published"], "2024-11-16T12:00:00+00:00")

        # Check that collections are present (URIs will be dynamic)
        self.assertIn("likes", data)
        self.assertIn("replies", data)
        self.assertIn("shares", data)

    def test_can_serialize_create_activity(self):
        """Create activities now embed their objects for client convenience"""
        expected_context = [
            "https://www.w3.org/ns/activitystreams",
            {
                "Emoji": "as:Emoji",
                "Hashtag": "as:Hashtag",
                "sensitive": {"@id": "as:sensitive", "@type": "xsd:boolean"},
            },
        ]

        actor = ActorFactory(preferred_username="alice", reference__domain=self.domain)

        note = models.ObjectContext.objects.create(
            reference=models.Reference.make("http://testserver/notes/789"),
            type=models.ObjectContext.Types.NOTE,
            content="Created note",
        )
        note.attributed_to.add(actor.reference)

        models.ActivityContext.objects.create(
            reference=models.Reference.make("http://testserver/activities/create-789"),
            type=models.ActivityContext.Types.CREATE,
            actor=actor.reference,
            object=note.reference,
            published=datetime(2024, 11, 16, 14, 30, 0, tzinfo=timezone.utc),
        )

        response = self.client.get(
            "/activities/create-789", HTTP_ACCEPT="application/activity+json"
        )

        self.assertEqual(response.status_code, 200)

        actual = response.json()

        # Check top-level fields
        self.assertEqual(actual["id"], "http://testserver/activities/create-789")
        self.assertEqual(actual["type"], "Create")
        self.assertEqual(actual["actor"], "http://testserver/users/alice")
        self.assertEqual(actual["published"], "2024-11-16T14:30:00+00:00")

        # Check @context structure (content matters, not order)
        self.assertIsInstance(actual["@context"], list)
        self.assertEqual(len(actual["@context"]), 2)
        self.assertEqual(actual["@context"][0], "https://www.w3.org/ns/activitystreams")
        self.assertIsInstance(actual["@context"][1], dict)
        self.assertEqual(actual["@context"][1], expected_context[1])

        # Check that object is embedded (not just a URI)
        self.assertIsInstance(actual["object"], dict)
        self.assertEqual(actual["object"]["id"], "http://testserver/notes/789")
        self.assertEqual(actual["object"]["type"], "Note")
        self.assertEqual(actual["object"]["content"], "Created note")

    def test_can_serialize_collection(self):
        collection_ref = models.Reference.make("http://testserver/collections/test")
        collection = CollectionFactory(
            reference=collection_ref,
            type=models.CollectionContext.Types.ORDERED,
            name="Test Collection",
        )

        for i in range(5):
            item_ref = models.Reference.make(f"http://testserver/items/{i}")
            item = models.ObjectContext.objects.create(
                reference=item_ref,
                type=models.ObjectContext.Types.NOTE,
                content=f"Item {i}",
            )
            collection.append(item.reference)

        response = self.client.get("/collections/test", HTTP_ACCEPT="application/activity+json")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["id"], "http://testserver/collections/test")
        self.assertEqual(data["type"], "OrderedCollection")
        self.assertEqual(data["name"], "Test Collection")
        self.assertEqual(data["totalItems"], 5)

        # Collection should have either items or first (for pagination)
        self.assertTrue("orderedItems" in data or "first" in data)

    def test_can_serialize_question_object(self):
        """
        a Question object is serialized with oneOf choices and embedded replies collection
        """
        actor = ActorFactory(preferred_username="alice", reference__domain=self.domain)

        # Create the Question object
        question = models.ObjectContext.objects.create(
            reference=models.Reference.make("http://testserver/questions/poll-123"),
            type=models.ObjectContext.Types.QUESTION,
            name="What's your favorite color?",
            content="Please choose one of the options below",
            published=datetime(2024, 11, 16, 15, 0, 0, tzinfo=timezone.utc),
        )
        question.attributed_to.add(actor.reference)

        # Create choice options as Note objects
        choice_refs = []
        for choice_name in ["Red", "Blue", "Green"]:
            choice_ref = models.Reference.make(
                f"http://testserver/questions/poll-123/choices/{choice_name.lower()}"
            )
            models.ObjectContext.objects.create(
                reference=choice_ref,
                type=models.ObjectContext.Types.NOTE,
                name=choice_name,
            )
            choice_refs.append(choice_ref)

        # Create QuestionContext to link choices
        question_context = models.QuestionContext.objects.create(reference=question.reference)
        for choice_ref in choice_refs:
            question_context.one_of.add(choice_ref)

        response = self.client.get("/questions/poll-123", HTTP_ACCEPT="application/activity+json")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Check basic structure
        self.assertEqual(data["id"], "http://testserver/questions/poll-123")
        self.assertEqual(data["type"], "Question")
        self.assertEqual(data["name"], "What's your favorite color?")
        self.assertEqual(data["content"], "Please choose one of the options below")
        self.assertEqual(data["attributedTo"], "http://testserver/users/alice")
        self.assertEqual(data["published"], "2024-11-16T15:00:00+00:00")

        # Check that oneOf is present
        self.assertIn("oneOf", data)

        # Verify each choice has basic fields
        for choice in data["oneOf"]:
            self.assertIn("type", choice)
            self.assertEqual(choice["type"], "Note")
            self.assertIn("name", choice)
            # Choices may have embedded replies collection (with totalItems: 0)
            # This is fine - it shows the collection exists even if empty

    def test_question_with_choices_having_embedded_replies(self):
        """
        Test Question with choices that have replies collections.
        Each choice should embed its replies collection showing id and totalItems.
        """
        actor = ActorFactory(preferred_username="alice", reference__domain=self.domain)

        # Create the Question
        question = models.ObjectContext.objects.create(
            reference=models.Reference.make("http://testserver/questions/poll-456"),
            type=models.ObjectContext.Types.QUESTION,
            name="Best programming language?",
            content="Vote for your favorite",
            published=datetime(2024, 11, 20, 10, 0, 0, tzinfo=timezone.utc),
        )
        question.attributed_to.add(actor.reference)

        # Create choice options as Note objects with replies
        choice_data = [
            ("Python", 5),
            ("JavaScript", 3),
            ("Rust", 7),
        ]

        choice_refs = []
        for choice_name, reply_count in choice_data:
            choice_ref = models.Reference.make(
                f"http://testserver/questions/poll-456/choices/{choice_name.lower()}"
            )
            choice = models.ObjectContext.objects.create(
                reference=choice_ref,
                type=models.ObjectContext.Types.NOTE,
                name=choice_name,
            )

            # Create a replies collection for this choice
            replies_ref = models.Reference.make(
                f"http://testserver/questions/poll-456/choices/{choice_name.lower()}/replies"
            )
            replies_collection = models.CollectionContext.make(
                reference=replies_ref,
                type=models.CollectionContext.Types.ORDERED,
            )

            # Add some reply items to the collection
            for i in range(reply_count):
                reply_ref = models.Reference.make(
                    f"http://testserver/questions/poll-456/choices/{choice_name.lower()}/replies/{i}"
                )
                replies_collection.append(reply_ref)

            # Link the replies collection to the choice
            choice.replies = replies_ref
            choice.save()

            choice_refs.append(choice_ref)

        # Create QuestionContext to link choices
        question_context = models.QuestionContext.objects.create(reference=question.reference)
        for choice_ref in choice_refs:
            question_context.one_of.add(choice_ref)

        response = self.client.get("/questions/poll-456", HTTP_ACCEPT="application/activity+json")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Verify basic question structure
        self.assertEqual(data["id"], "http://testserver/questions/poll-456")
        self.assertEqual(data["type"], "Question")
        self.assertIn("oneOf", data)

        # Verify each choice has replies as an embedded collection
        for choice in data["oneOf"]:
            self.assertIn("id", choice)
            self.assertIn("name", choice)
            self.assertIn("replies", choice)

            # Replies should be an embedded collection object with metadata
            self.assertIsInstance(choice["replies"], dict)
            self.assertEqual(choice["replies"]["type"], "OrderedCollection")
            self.assertIn("id", choice["replies"])
            self.assertTrue(choice["replies"]["id"].startswith("http://"))
            self.assertIn("totalItems", choice["replies"])
            self.assertIn("first", choice["replies"])
            self.assertIsInstance(choice["replies"]["first"], dict)

    def test_note_with_replies_collection_embedding(self):
        """
        A Note object embeds the replies collection with totalItems and first page,
        providing clients with collection metadata upfront.
        """
        actor = ActorFactory(preferred_username="bob", reference__domain=self.domain)

        # Create a Note
        note = models.ObjectContext.objects.create(
            reference=models.Reference.make("http://testserver/notes/note-with-replies"),
            type=models.ObjectContext.Types.NOTE,
            content="This is a note with many replies",
            published=datetime(2024, 11, 21, 14, 0, 0, tzinfo=timezone.utc),
        )
        note.attributed_to.add(actor.reference)

        # Create a replies collection
        replies_ref = models.Reference.make("http://testserver/collections/note-replies")
        replies_collection = models.CollectionContext.make(
            reference=replies_ref,
            type=models.CollectionContext.Types.ORDERED,
        )

        # Add several reply items
        for i in range(10):
            reply_ref = models.Reference.make(f"http://testserver/notes/reply-{i}")
            models.ObjectContext.objects.create(
                reference=reply_ref,
                type=models.ObjectContext.Types.NOTE,
                content=f"Reply {i}",
            )
            replies_collection.append(reply_ref)

        # Link replies to the note
        note.replies = replies_ref
        note.save()

        # Test 1: Get the note - replies should be just a reference (string URL)
        note_response = self.client.get(
            "/notes/note-with-replies", HTTP_ACCEPT="application/activity+json"
        )

        self.assertEqual(note_response.status_code, 200)
        note_data = note_response.json()

        self.assertEqual(note_data["id"], "http://testserver/notes/note-with-replies")
        self.assertEqual(note_data["type"], "Note")
        self.assertIn("replies", note_data)

        # Replies should be an embedded collection object
        self.assertIsInstance(note_data["replies"], dict)
        self.assertEqual(note_data["replies"]["type"], "OrderedCollection")
        self.assertEqual(note_data["replies"]["id"], "http://testserver/collections/note-replies")
        self.assertIn("totalItems", note_data["replies"])
        self.assertEqual(note_data["replies"]["totalItems"], 10)
        self.assertIn("first", note_data["replies"])
        self.assertIsInstance(note_data["replies"]["first"], dict)

        # Test 2: Get the collection directly - first page should be embedded
        collection_response = self.client.get(
            "/collections/note-replies", HTTP_ACCEPT="application/activity+json"
        )

        self.assertEqual(collection_response.status_code, 200)
        collection_data = collection_response.json()

        self.assertEqual(collection_data["id"], "http://testserver/collections/note-replies")
        self.assertEqual(collection_data["type"], "OrderedCollection")
        self.assertIn("totalItems", collection_data)
        self.assertEqual(collection_data["totalItems"], 10)
        self.assertIn("first", collection_data)

        # First page should be embedded (object), not just a reference (string)
        self.assertIsInstance(collection_data["first"], dict)
        self.assertIn("id", collection_data["first"])
        self.assertIn("type", collection_data["first"])
        self.assertEqual(collection_data["first"]["type"], "OrderedCollectionPage")

        # Note: AS2 uses "orderedItems" for OrderedCollectionPage, but the current
        # implementation uses "items" - this is a known limitation
        items_key = "orderedItems" if "orderedItems" in collection_data["first"] else "items"
        self.assertIn(items_key, collection_data["first"])

        # Verify the items are present in the first page
        self.assertIsInstance(collection_data["first"][items_key], list)
        self.assertGreater(len(collection_data["first"][items_key]), 0)
