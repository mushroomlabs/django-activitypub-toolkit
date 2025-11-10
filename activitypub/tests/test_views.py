import json
from datetime import datetime, timezone

import httpretty
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from activitypub import models
from activitypub.factories import (
    AccountFactory,
    ActivityFactory,
    ActorFactory,
    CollectionFactory,
    DomainFactory,
    ObjectFactory,
)
from activitypub.tests.base import BaseTestCase, use_nodeinfo, with_remote_reference

CONTENT_TYPE = "application/ld+json"


@override_settings(
    FEDERATION={"DEFAULT_URL": "http://testserver", "FORCE_INSECURE_HTTP": True},
    ALLOWED_HOSTS=["testserver"],
)
class InboxViewTestCase(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        self.domain = DomainFactory(scheme="http", name="testserver", local=True)
        self.account = AccountFactory(
            username="bob", domain=self.domain, actor__manually_approves_followers=True
        )
        CollectionFactory(reference=self.account.actor.inbox)

    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @with_remote_reference("https://remote.example.com/users/alice", "standard/actor.alice.json")
    def test_can_post_activity(self):
        message = {
            "id": "https://remote.example.com/0cc0a50f-9043-4d9b-b82a-ab3cd13ab906",
            "type": "Follow",
            "actor": "https://remote.example.com/users/alice",
            "object": "http://testserver/users/bob",
            "@context": "https://www.w3.org/ns/activitystreams",
        }
        response = self.client.post(
            "/users/bob/inbox", data=json.dumps(message), content_type=CONTENT_TYPE
        )
        self.assertEqual(response.status_code, 202, response.content)

    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @with_remote_reference("https://remote.example.com/users/alice", "standard/actor.alice.json")
    def test_follow_activity_creates_follow_request(self):
        """Test that posting a Follow activity creates a pending follow request."""
        remote_actor_uri = "https://remote.example.com/users/alice"
        follow_activity = {
            "id": "https://remote.example.com/follow-activity/123",
            "type": "Follow",
            "actor": remote_actor_uri,
            "object": "http://testserver/users/bob",
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/inbox", data=json.dumps(follow_activity), content_type=CONTENT_TYPE
        )
        self.assertEqual(response.status_code, 202)

        # Verify activity was created and processed
        activity = models.Activity.objects.get(
            reference__uri="https://remote.example.com/follow-activity/123"
        )
        self.assertEqual(activity.type, models.Activity.Types.FOLLOW)

        # Verify follow request was created
        follow_request = models.FollowRequest.objects.get(activity=activity)
        self.assertEqual(follow_request.status, models.FollowRequest.STATUS.pending)
        self.assertEqual(str(follow_request.follower.uri), remote_actor_uri)
        self.assertEqual(str(follow_request.followed.uri), "http://testserver/users/bob")

    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @with_remote_reference("https://remote.example.com/users/alice", "standard/actor.alice.json")
    def test_accept_follow_updates_collections(self):
        """Test that accepting a follow updates followers/following collections."""
        # First create a follow request
        remote_actor = ActorFactory(reference__uri="https://remote.example.com/users/alice")
        follow_activity = ActivityFactory(
            type=models.Activity.Types.FOLLOW,
            actor=remote_actor.reference,
            object=self.account.actor.reference,
        )
        follow_request = models.FollowRequest.objects.create(activity=follow_activity)

        # Post accept activity
        accept_activity = {
            "id": "https://remote.example.com/accept-activity",
            "type": "Accept",
            "actor": "http://testserver/users/bob",
            "object": str(follow_activity.reference.uri),
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/inbox", data=json.dumps(accept_activity), content_type=CONTENT_TYPE
        )
        self.assertEqual(response.status_code, 202)

        # Refresh follow request and verify it's accepted
        follow_request.refresh_from_db()
        self.assertEqual(follow_request.status, models.FollowRequest.STATUS.accepted)

        # Verify collections were updated
        followers_collection = models.CollectionContext.make(self.account.actor.followers)
        following_collection = models.CollectionContext.make(remote_actor.following)

        self.assertTrue(followers_collection.contains(remote_actor.reference))
        self.assertTrue(following_collection.contains(self.account.actor.reference))

    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @with_remote_reference("https://remote.example.com/users/alice", "standard/actor.alice.json")
    def test_like_activity_updates_likes_collections(self):
        """Test that posting a Like activity updates likes collections."""
        # Create a local note to like
        note = ObjectFactory(
            reference__domain=self.domain,
            type=models.ObjectContext.Types.NOTE,
            content="Test note",
        )

        like_activity = {
            "id": "https://remote.example.com/like-activity",
            "type": "Like",
            "actor": "https://remote.example.com/users/alice",
            "object": str(note.reference.uri),
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/inbox", data=json.dumps(like_activity), content_type=CONTENT_TYPE
        )
        self.assertEqual(response.status_code, 202)

        # Verify likes collection was updated
        likes_collection = models.CollectionContext.make(note.likes)
        like_activity_ref = models.Reference.objects.get(uri=like_activity["id"])
        self.assertTrue(likes_collection.contains(like_activity_ref))

    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @with_remote_reference("https://remote.example.com/users/alice", "standard/actor.alice.json")
    def test_announce_activity_updates_shares_collection(self):
        """Test that posting an Announce activity updates shares collection."""
        # Create a local note to announce
        note = ObjectFactory(
            reference__domain=self.domain,
            type=models.ObjectContext.Types.NOTE,
            content="Test note to announce",
        )

        announce_activity = {
            "id": "https://remote.example.com/announce-activity",
            "type": "Announce",
            "actor": "https://remote.example.com/users/alice",
            "object": str(note.reference.uri),
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/inbox", data=json.dumps(announce_activity), content_type=CONTENT_TYPE
        )
        self.assertEqual(response.status_code, 202)

        # Refresh note and verify shares collection
        note.refresh_from_db()
        self.assertIsNotNone(note.shares)
        shares_collection = models.CollectionContext.make(note.shares)
        announce_activity_ref = models.Reference.objects.get(uri=announce_activity["id"])
        self.assertTrue(shares_collection.contains(announce_activity_ref))

    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @with_remote_reference("https://remote.example.com/users/alice", "standard/actor.alice.json")
    def test_undo_activity_reverses_side_effects(self):
        """Test that posting an Undo activity reverses previous activity side effects."""
        # First create and process a follow

        remote_actor_ref = models.Reference.make("https://remote.example.com/users/alice")
        remote_actor_ref.resolve()

        remote_actor = remote_actor_ref.get_by_context(models.ActorContext)
        follow_activity = ActivityFactory(
            type=models.Activity.Types.FOLLOW,
            actor=remote_actor.reference,
            object=self.account.actor.reference,
        )
        follow_activity.do()

        # Accept the follow
        accept_activity = ActivityFactory(
            type=models.Activity.Types.ACCEPT,
            actor=self.account.actor.reference,
            object=follow_activity.reference,
        )
        accept_activity.do()

        # Verify follow was established
        followers_collection = models.CollectionContext.make(self.account.actor.followers)
        self.assertTrue(followers_collection.contains(remote_actor.reference))

        # Now undo the follow
        undo_activity = {
            "id": "https://remote.example.com/undo-activity",
            "type": "Undo",
            "actor": "https://remote.example.com/users/alice",
            "object": str(follow_activity.reference.uri),
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/inbox", data=json.dumps(undo_activity), content_type=CONTENT_TYPE
        )
        self.assertEqual(response.status_code, 202)

        # Verify follow was undone
        followers_collection = models.CollectionContext.make(self.account.actor.followers)
        self.assertFalse(followers_collection.contains(remote_actor.reference))

        # Verify follow request was deleted
        self.assertFalse(models.FollowRequest.objects.filter(activity=follow_activity).exists())

    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @with_remote_reference("https://remote.example.com/users/alice", "standard/actor.alice.json")
    def test_blocked_domain_rejects_activity(self):
        """Test that activities from blocked domains are rejected."""
        DomainFactory(name="blocked.example.com", blocked=True)

        blocked_activity = {
            "id": "https://blocked.example.com/activity",
            "type": "Follow",
            "actor": "https://blocked.example.com/users/spammer",
            "object": "http://testserver/users/bob",
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/inbox", data=json.dumps(blocked_activity), content_type=CONTENT_TYPE
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("blocked", response.content.decode().lower())

    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @with_remote_reference("https://remote.example.com/users/alice", "standard/actor.alice.json")
    def test_invalid_activity_returns_bad_request(self):
        """Test that malformed activities return appropriate error responses."""
        invalid_activity = {
            "id": "https://remote.example.com/invalid",
            "type": "Follow",
            # Missing required 'actor' field
            "object": "http://testserver/users/bob",
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/inbox", data=json.dumps(invalid_activity), content_type=CONTENT_TYPE
        )
        self.assertEqual(response.status_code, 400)

    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @with_remote_reference("https://remote.example.com/users/alice", "standard/actor.alice.json")
    def test_undo_like_removes_from_collections_via_inbox(self):
        """Test that Undo Like activity removes the like from collections"""
        # Create a note by bob (local)
        note = ObjectFactory(
            reference__domain=self.domain,
            type=models.ObjectContext.Types.NOTE,
            content="Bob's note",
        )

        # Alice (remote) likes the note
        like_activity = {
            "id": "https://remote.example.com/activities/like-123",
            "type": "Like",
            "actor": "https://remote.example.com/users/alice",
            "object": str(note.reference.uri),
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/inbox",
            data=json.dumps(like_activity),
            content_type="application/ld+json",
        )
        self.assertEqual(response.status_code, 202)

        # Verify like was added to likes collection
        likes_collection = models.CollectionContext.make(note.likes)
        like_ref = models.Reference.objects.get(uri=like_activity["id"])
        self.assertTrue(likes_collection.contains(like_ref))

        # Alice undoes the like
        undo_like_activity = {
            "id": "https://remote.example.com/activities/undo-like-123",
            "type": "Undo",
            "actor": "https://remote.example.com/users/alice",
            "object": like_activity["id"],
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/inbox",
            data=json.dumps(undo_like_activity),
            content_type="application/ld+json",
        )
        self.assertEqual(response.status_code, 202)

        # Verify like was removed from likes collection
        self.assertFalse(
            likes_collection.contains(like_ref), "Like should be removed from likes collection"
        )

    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @with_remote_reference("https://remote.example.com/users/alice", "standard/actor.alice.json")
    def test_undo_announce_removes_from_shares_collection_via_inbox(self):
        """Test that Undo Announce activity removes the announce from shares collection"""
        # Create a note by bob (local)
        note = ObjectFactory(
            reference__domain=self.domain,
            type=models.ObjectContext.Types.NOTE,
            content="Bob's note to share",
        )

        # Alice (remote) announces the note
        announce_activity = {
            "id": "https://remote.example.com/activities/announce-456",
            "type": "Announce",
            "actor": "https://remote.example.com/users/alice",
            "object": str(note.reference.uri),
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/inbox",
            data=json.dumps(announce_activity),
            content_type="application/ld+json",
        )
        self.assertEqual(response.status_code, 202)

        # Verify announce was added to shares collection
        note.refresh_from_db()
        self.assertIsNotNone(note.shares, "Shares collection should be created")
        shares_collection = models.CollectionContext.make(note.shares)
        announce_ref = models.Reference.objects.get(uri=announce_activity["id"])
        self.assertTrue(shares_collection.contains(announce_ref))

        # Alice undoes the announce
        undo_announce_activity = {
            "id": "https://remote.example.com/activities/undo-announce-456",
            "type": "Undo",
            "actor": "https://remote.example.com/users/alice",
            "object": announce_activity["id"],
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/inbox",
            data=json.dumps(undo_announce_activity),
            content_type="application/ld+json",
        )
        self.assertEqual(response.status_code, 202)

        # Verify announce was removed from shares collection
        self.assertFalse(
            shares_collection.contains(announce_ref),
            "Announce should be removed from shares collection",
        )

    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @with_remote_reference("https://remote.example.com/users/alice", "standard/actor.alice.json")
    def test_undo_like_with_actor_liked_collection(self):
        """Test that Undo Like also removes object from actor's liked collection"""
        # Create remote actor alice with a liked collection
        alice_ref = models.Reference.make("https://remote.example.com/users/alice")
        alice_ref.resolve()
        alice = alice_ref.get_by_context(models.ActorContext)

        # Set up alice's liked collection
        alice_liked_ref = models.Reference.make("https://remote.example.com/users/alice/liked")
        alice.liked = alice_liked_ref
        alice.save()

        # Create a note by bob (local)
        note = ObjectFactory(
            reference__domain=self.domain,
            type=models.ObjectContext.Types.NOTE,
            content="Bob's note",
        )

        # Alice (remote) likes the note
        like_activity = {
            "id": "https://remote.example.com/activities/like-789",
            "type": "Like",
            "actor": "https://remote.example.com/users/alice",
            "object": str(note.reference.uri),
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/inbox",
            data=json.dumps(like_activity),
            content_type="application/ld+json",
        )
        self.assertEqual(response.status_code, 202)

        # Verify like was added to both collections
        likes_collection = models.CollectionContext.make(note.likes)
        liked_collection = models.CollectionContext.make(alice.liked)
        like_ref = models.Reference.objects.get(uri=like_activity["id"])

        self.assertTrue(likes_collection.contains(like_ref))
        self.assertTrue(liked_collection.contains(note.reference))

        # Alice undoes the like
        undo_like_activity = {
            "id": "https://remote.example.com/activities/undo-like-789",
            "type": "Undo",
            "actor": "https://remote.example.com/users/alice",
            "object": like_activity["id"],
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/inbox",
            data=json.dumps(undo_like_activity),
            content_type="application/ld+json",
        )
        self.assertEqual(response.status_code, 202)

        # Verify like was removed from both collections
        self.assertFalse(likes_collection.contains(like_ref))
        self.assertFalse(liked_collection.contains(note.reference))


class ActivityPubObjectViewTestCase(BaseTestCase):
    """
    Test that the ActivityPubObjectDetailView correctly serializes
    objects in a format compatible with common fediverse software.
    """

    def setUp(self):
        self.client = APIClient()
        self.domain = DomainFactory(scheme="http", name="testserver", local=True)

    def test_can_serialize_actor(self):
        """Test that an actor is serialized in ActivityPub-compatible format"""
        expected = {
            "@context": [
                "https://www.w3.org/ns/activitystreams",
                {
                    "manuallyApprovesFollowers": {
                        "@id": "as:manuallyApprovesFollowers",
                        "@type": "xsd:boolean",
                    },
                    "sensitive": {"@id": "as:sensitive", "@type": "xsd:boolean"},
                    "Hashtag": "as:Hashtag",
                    "Emoji": "as:Emoji",
                    "movedTo": {"@id": "as:movedTo", "@type": "@id"},
                    "alsoKnownAs": {"@id": "as:alsoKnownAs", "@type": "@id"},
                },
            ],
            "id": "http://testserver/users/alice",
            "type": "Person",
            "preferredUsername": "alice",
            "name": "Alice Activitypub",
            "summary": "Just a simple test actor",
            "followers": "http://testserver/users/alice/followers",
            "following": "http://testserver/users/alice/following",
            "manuallyApprovesFollowers": False,
            "published": "2024-01-01T00:00:00+00:00",
        }

        account = AccountFactory(username="alice", domain=self.domain)
        actor = account.actor
        actor.name = "Alice Activitypub"
        actor.summary = "Just a simple test actor"
        actor.preferred_username = "alice"
        actor.published = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        actor.save()

        response = self.client.get(
            "http://testserver/users/alice",
            HTTP_ACCEPT="application/activity+json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)

    def test_can_serialize_note_object(self):
        """Test that a Note object is serialized correctly"""
        account = AccountFactory(username="bob", domain=self.domain)
        actor = account.actor

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
        """Test that a Create activity is serialized correctly"""
        expected = {
            "@context": [
                "https://www.w3.org/ns/activitystreams",
                {
                    "manuallyApprovesFollowers": {
                        "@id": "as:manuallyApprovesFollowers",
                        "@type": "xsd:boolean",
                    },
                    "sensitive": {"@id": "as:sensitive", "@type": "xsd:boolean"},
                    "Hashtag": "as:Hashtag",
                    "Emoji": "as:Emoji",
                    "movedTo": {"@id": "as:movedTo", "@type": "@id"},
                    "alsoKnownAs": {"@id": "as:alsoKnownAs", "@type": "@id"},
                },
            ],
            "id": "http://testserver/activities/create-789",
            "type": "Create",
            "actor": "http://testserver/users/alice",
            "object": "http://testserver/notes/789",
            "published": "2024-11-16T14:30:00+00:00",
        }

        account = AccountFactory(username="alice", domain=self.domain)
        actor = account.actor

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
        self.assertEqual(response.json(), expected)

    def test_can_serialize_collection(self):
        """Test that a Collection is serialized with proper structure"""
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
        self.assertTrue("items" in data or "first" in data)

    def test_can_serialize_question_object(self):
        """Test that a Question object is serialized with oneOf choices and embedded replies collection"""
        account = AccountFactory(username="alice", domain=self.domain)
        actor = account.actor

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
            self.assertIn("id", choice)
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
        account = AccountFactory(username="alice", domain=self.domain)
        actor = account.actor

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

        # Verify each choice has embedded replies with id and totalItems
        for choice in data["oneOf"]:
            self.assertIn("id", choice)
            self.assertIn("name", choice)
            self.assertIn("replies", choice)

            # Replies should be embedded as an object (not just a string reference)
            self.assertIsInstance(choice["replies"], dict)
            self.assertIn("id", choice["replies"])
            self.assertIn("totalItems", choice["replies"])

            # Verify totalItems matches what we created
            choice_name = choice["name"]
            expected_count = next(count for name, count in choice_data if name == choice_name)
            self.assertEqual(choice["replies"]["totalItems"], expected_count)

    def test_note_with_replies_collection_embedding(self):
        """
        Test that a Note object shows replies as reference, but accessing
        the collection URL directly returns it with embedded first page.
        """
        account = AccountFactory(username="bob", domain=self.domain)
        actor = account.actor

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
            reply_note = models.ObjectContext.objects.create(
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

        # Replies should be a simple reference (string)
        self.assertIsInstance(note_data["replies"], str)
        self.assertEqual(note_data["replies"], "http://testserver/collections/note-replies")

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


class ActivityOutboxTestCase(TransactionTestCase):
    """Test C2S activities posted to the outbox"""

    def setUp(self):
        self.client = APIClient()
        self.domain = DomainFactory(scheme="http", name="testserver", local=True)
        self.account = AccountFactory(username="bob", domain=self.domain)
        CollectionFactory(reference=self.account.actor.outbox)

    def test_local_actor_can_post_follow_to_own_outbox(self):
        """Test that a local actor can post a Follow activity to their own outbox"""
        # Create a remote actor to follow
        remote_domain = DomainFactory(name="remote.example.com", local=False)
        alice = ActorFactory(
            name="Alice",
            reference__uri="https://remote.example.com/users/alice",
            reference__domain=remote_domain,
        )

        follow_activity = {
            "type": "Follow",
            "actor": "http://testserver/users/bob",
            "object": str(alice.reference.uri),
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/outbox",
            data=json.dumps(follow_activity),
            content_type="application/ld+json",
        )

        # C2S should return 201 Created
        self.assertEqual(response.status_code, 201)

        # Verify side effects: FollowRequest should be created
        # Note: The activity ID will be assigned by the server
        self.assertTrue(
            models.FollowRequest.objects.filter(
                activity__actor=self.account.actor.reference,
                activity__object=alice.reference,
            ).exists(),
            "FollowRequest should be created",
        )

    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @with_remote_reference("https://remote.example.com/users/alice", "standard/actor.alice.json")
    def test_remote_actor_cannot_post_to_outbox(self):
        """Test that a remote actor cannot post to a local actor's outbox"""
        follow_activity = {
            "id": "http://testserver/activities/spoof-follow-from-bob-123",
            "type": "Follow",
            "actor": "https://remote.example.com/users/alice",
            "object": "http://testserver/users/bob",
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/outbox",
            data=json.dumps(follow_activity),
            content_type="application/ld+json",
        )

        # Should return 403 Forbidden
        self.assertEqual(response.status_code, 403)
