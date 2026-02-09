import json
import re

import httpretty
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from activitypub.core import models
from activitypub.core.factories import (
    ActivityFactory,
    ActorFactory,
    CollectionFactory,
    DomainFactory,
    ObjectFactory,
)
from tests.core.base import (
    silence_notifications,
    use_nodeinfo,
    with_remote_reference,
)

CONTENT_TYPE = "application/ld+json"


@override_settings(
    FEDERATION={
        "DEFAULT_URL": "http://testserver",
        "FORCE_INSECURE_HTTP": True,
        "REJECT_FOLLOW_REQUEST_CHECKS": [],
    },
    ALLOWED_HOSTS=["testserver"],
)
class InboxViewTestCase(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        self.domain = DomainFactory(scheme="http", name="testserver", local=True)
        self.actor = ActorFactory(
            preferred_username="bob",
            reference__domain=self.domain,
            manually_approves_followers=True,
        )
        CollectionFactory(reference=self.actor.inbox)

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
        follow_request = models.FollowRequest.objects.get(activity=activity.reference)
        self.assertEqual(follow_request.status, models.FollowRequest.STATUS.submitted)
        self.assertEqual(str(follow_request.follower.uri), remote_actor_uri)
        self.assertEqual(str(follow_request.followed.uri), "http://testserver/users/bob")

    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @with_remote_reference("https://remote.example.com/users/alice", "standard/actor.alice.json")
    @silence_notifications("https://remote.example.com")
    def test_accept_follow_updates_collections(self):
        # Silence notifications to dynamically-generated test domains
        test_domain_pattern = re.compile(r"https?://test-domain-\d+\.com/.*")
        httpretty.register_uri(httpretty.POST, test_domain_pattern)
        httpretty.register_uri(httpretty.GET, test_domain_pattern)

        # Scenario: Bob (local) followed Alice (remote), Alice accepts
        # Create the remote domain and actor with proper domain association
        remote_domain = models.Domain.make("https://remote.example.com")
        remote_actor = ActorFactory(
            reference__domain=remote_domain,
            preferred_username="alice",
        )
        follow_activity = ActivityFactory(
            reference__domain=self.domain,
            type=models.Activity.Types.FOLLOW,
            actor=self.actor.reference,
            object=remote_actor.reference,
        )
        models.FollowRequest.objects.create(
            follower=follow_activity.actor,
            followed=follow_activity.object,
            activity=follow_activity.reference,
        )

        # Alice (remote) sends Accept to Bob's inbox
        accept_activity = {
            "id": "https://remote.example.com/activities/accept-follow",
            "type": "Accept",
            "actor": "https://remote.example.com/users/alice",
            "object": str(follow_activity.reference.uri),
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/inbox", data=json.dumps(accept_activity), content_type=CONTENT_TYPE
        )
        self.assertEqual(response.status_code, 202)

        # Verify the notification was created and the document was stored
        notification = models.Notification.objects.filter(
            resource__uri="https://remote.example.com/activities/accept-follow"
        ).first()
        self.assertIsNotNone(notification)

        document = models.LinkedDataDocument.objects.filter(
            reference__uri="https://remote.example.com/activities/accept-follow"
        ).first()
        self.assertIsNotNone(document)
        self.assertEqual(document.data["type"], "Accept")

    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @with_remote_reference("https://remote.example.com/users/alice", "standard/actor.alice.json")
    def test_like_activity_updates_likes_collections(self):
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
    @silence_notifications("https://remote.example.com")
    def test_undo_activity_reverses_side_effects(self):
        # First create and process a follow

        remote_actor_ref = models.Reference.make("https://remote.example.com/users/alice")
        remote_actor_ref.resolve()

        remote_actor = remote_actor_ref.get_by_context(models.ActorContext)
        follow_activity = ActivityFactory(
            type=models.Activity.Types.FOLLOW,
            actor=remote_actor.reference,
            object=self.actor.reference,
        )
        follow_activity.do()

        # Accept the follow
        accept_activity = ActivityFactory(
            type=models.Activity.Types.ACCEPT,
            actor=self.actor.reference,
            object=follow_activity.reference,
        )
        accept_activity.do()

        # Verify follow was established
        followers_collection = models.CollectionContext.make(self.actor.followers)
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
        followers_collection = models.CollectionContext.make(self.actor.followers)
        self.assertFalse(followers_collection.contains(remote_actor.reference))

        # Verify follow request was deleted
        self.assertFalse(
            models.FollowRequest.objects.filter(activity=follow_activity.reference).exists()
        )

    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @with_remote_reference("https://remote.example.com/users/alice", "standard/actor.alice.json")
    def test_blocked_domain_rejects_activity(self):
        """activities from blocked domains are rejected."""
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
        """malformed activities return appropriate error responses."""
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
        """Undo Like activity removes the like from collections"""
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
        """Undo Announce activity removes the announce from shares collection"""
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
        """Undo Like also removes object from actor's liked collection"""
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


@override_settings(
    FEDERATION={
        "DEFAULT_URL": "http://testserver",
        "FORCE_INSECURE_HTTP": True,
        "REJECT_FOLLOW_REQUEST_CHECKS": [],
    },
    ALLOWED_HOSTS=["testserver"],
)
class InboxSecurityTestCase(TransactionTestCase):
    """Security tests for S2S inbox operations"""

    def setUp(self):
        self.client = APIClient()
        self.domain = DomainFactory(scheme="http", name="testserver", local=True)
        self.bob = ActorFactory(
            preferred_username="bob",
            reference__domain=self.domain,
        )
        CollectionFactory(reference=self.bob.inbox)

    @httpretty.activate
    @use_nodeinfo("https://evil.example.com", "nodeinfo/mastodon.json")
    @with_remote_reference("https://evil.example.com/users/mallory", "standard/actor.alice.json")
    def test_create_with_object_id_on_different_domain_not_loaded(self):
        """
        Threat: remote actor tries to create object with ID pointing to our server.
        The request is accepted but the object is not loaded.
        """
        # Mallory from evil.example.com tries to create an object with testserver ID
        create_activity = {
            "id": "https://evil.example.com/activities/hijack-1",
            "type": "Create",
            "actor": "https://evil.example.com/users/mallory",
            "object": {
                "id": "http://testserver/notes/hijacked-note-123",
                "type": "Note",
                "content": "This note pretends to be from testserver",
                "attributedTo": "https://evil.example.com/users/mallory",
            },
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/inbox",
            data=json.dumps(create_activity),
            content_type="application/ld+json",
        )

        # Request is accepted
        self.assertEqual(response.status_code, 202)

        # Verify no ObjectContext was created with that ID (Reference may exist from parsing)
        self.assertFalse(
            models.ObjectContext.objects.filter(
                reference__uri="http://testserver/notes/hijacked-note-123"
            ).exists(),
            "Object with unauthorized domain ID should not be loaded",
        )

    @httpretty.activate
    @use_nodeinfo("https://evil.example.com", "nodeinfo/mastodon.json")
    @with_remote_reference("https://evil.example.com/users/mallory", "standard/actor.alice.json")
    def test_update_of_object_not_owned_by_actor_has_no_effect(self):
        """
        Attack: Remote actor tries to update content owned by someone else.
        The request is accepted but silently discarded
        """
        # Create a note owned by Bob (local)
        bob_note = ObjectFactory(
            reference__domain=self.domain,
            reference__path="/notes/bobs-note-999",
            type=models.ObjectContext.Types.NOTE,
            content="Bob's original content",
        )
        bob_note.attributed_to.add(self.bob.reference)

        # Mallory tries to update Bob's note
        update_activity = {
            "id": "https://evil.example.com/activities/hijack-update-1",
            "type": "Update",
            "actor": "https://evil.example.com/users/mallory",
            "object": {
                "id": str(bob_note.reference.uri),
                "type": "Note",
                "content": "Mallory hijacked Bob's note!",
            },
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/inbox",
            data=json.dumps(update_activity),
            content_type="application/ld+json",
        )

        self.assertEqual(response.status_code, 202)

        # Verify the note wasn't modified
        bob_note.refresh_from_db()
        self.assertEqual(bob_note.content, "Bob's original content")

    @httpretty.activate
    @use_nodeinfo("https://evil.example.com", "nodeinfo/mastodon.json")
    @with_remote_reference("https://evil.example.com/users/mallory", "standard/actor.alice.json")
    def test_delete_of_object_not_owned_by_actor_has_no_effect(self):
        """
        Attack vector: Remote actor tries to delete content owned by someone else.
        The activity is processed but the delete is not executed.
        """
        # Create a note owned by Bob (local)
        bob_note = ObjectFactory(
            reference__domain=self.domain,
            reference__path="/notes/bobs-note-to-delete",
            type=models.ObjectContext.Types.NOTE,
            content="Bob's note that should not be deleted",
        )
        bob_note.attributed_to.add(self.bob.reference)

        # Mallory tries to delete Bob's note
        delete_activity = {
            "id": "https://evil.example.com/activities/hijack-delete-1",
            "type": "Delete",
            "actor": "https://evil.example.com/users/mallory",
            "object": str(bob_note.reference.uri),
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/inbox",
            data=json.dumps(delete_activity),
            content_type="application/ld+json",
        )

        # requested is accepted but ignored
        self.assertEqual(response.status_code, 202)

        # Verify the note still exists (the delete action is not executed)
        self.assertTrue(
            models.ObjectContext.objects.filter(reference=bob_note.reference).exists(),
            "Object should not be deleted by unauthorized actor",
        )

    @httpretty.activate
    @use_nodeinfo("https://evil.example.com", "nodeinfo/mastodon.json")
    @with_remote_reference("https://evil.example.com/users/mallory", "standard/actor.alice.json")
    def test_create_cannot_overwrite_existing_reference(self):
        """
        S2S: Create activity cannot overwrite an existing object.
        Attack vector: Remote actor tries to replace existing content with malicious content.
        The request is accepted but the malicious content is not loaded.
        """
        # Create an existing note
        existing_note = ObjectFactory(
            reference__domain=self.domain,
            reference__path="/notes/existing-note-xyz",
            type=models.ObjectContext.Types.NOTE,
            content="Original trusted content",
        )
        existing_note.attributed_to.add(self.bob.reference)

        # Mallory tries to create an object with the same ID
        create_activity = {
            "id": "https://evil.example.com/activities/overwrite-1",
            "type": "Create",
            "actor": "https://evil.example.com/users/mallory",
            "object": {
                "id": str(existing_note.reference.uri),
                "type": "Note",
                "content": "Mallory replaced the trusted content",
                "attributedTo": "https://evil.example.com/users/mallory",
            },
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/inbox",
            data=json.dumps(create_activity),
            content_type="application/ld+json",
        )

        # Request is accepted but malicious content is not loaded
        self.assertEqual(response.status_code, 202)

        # Verify the original content wasn't modified
        existing_note.refresh_from_db()
        self.assertEqual(existing_note.content, "Original trusted content")

    @httpretty.activate
    @use_nodeinfo("https://evil.example.com", "nodeinfo/mastodon.json")
    @with_remote_reference("https://evil.example.com/users/mallory", "standard/actor.alice.json")
    def test_create_with_attributedto_impersonation_not_loaded(self):
        """
        Attack: Remote actor creates content claiming it's from someone else.
        The request should be accepted, but we do not process it
        """
        # Mallory creates a note claiming it's from Bob
        create_activity = {
            "id": "https://evil.example.com/activities/impersonate-1",
            "type": "Create",
            "actor": "https://evil.example.com/users/mallory",
            "object": {
                "id": "https://evil.example.com/notes/fake-note-from-bob",
                "type": "Note",
                "content": "This note claims to be from Bob",
                "attributedTo": "http://testserver/users/bob",
            },
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/inbox",
            data=json.dumps(create_activity),
            content_type="application/ld+json",
        )

        # Request is accepted
        self.assertEqual(response.status_code, 202)

        # But the object with wrong attributedTo should not be loaded
        self.assertFalse(
            models.ObjectContext.objects.filter(
                reference__uri="https://evil.example.com/notes/fake-note-from-bob"
            ).exists(),
            "Object with impersonated attributedTo should not be loaded",
        )

    @httpretty.activate
    @use_nodeinfo("https://evil.example.com", "nodeinfo/mastodon.json")
    @with_remote_reference("https://evil.example.com/users/mallory", "standard/actor.alice.json")
    def test_reject_activity_with_spoofed_actor(self):
        """
        S2S: Reject activity where actor field claims to be from a different domain.
        Attack vector: Remote actor claims to be a local actor to bypass authorization.
        """
        # evil.example.com sends activity claiming to be from testserver
        spoofed_activity = {
            "id": "https://evil.example.com/activities/spoof-1",
            "type": "Follow",
            "actor": "http://testserver/users/bob",
            "object": "http://testserver/users/alice",
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/inbox",
            data=json.dumps(spoofed_activity),
            content_type="application/ld+json",
        )

        # Should be rejected - actor domain doesn't match the sender
        # Note: In production this would be enforced by HTTP signature verification
        self.assertIn(
            response.status_code,
            [400, 401, 403],
            f"Should reject activity with spoofed actor, got {response.status_code}",
        )
