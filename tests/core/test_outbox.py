import json

import httpretty
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from activitypub.core import models
from activitypub.core.factories import (
    ActorFactory,
    CollectionFactory,
    DomainFactory,
    IdentityFactory,
    ObjectFactory,
)
from tests.core.base import (
    silence_notifications,
    use_nodeinfo,
    with_remote_reference,
)


@override_settings(
    FEDERATION={
        "DEFAULT_URL": "http://testserver",
        "FORCE_INSECURE_HTTP": True,
        "REJECT_FOLLOW_REQUEST_CHECKS": [],
    },
    ALLOWED_HOSTS=["testserver"],
)
class ActivityOutboxTestCase(TransactionTestCase):
    """Test C2S activities posted to the outbox"""

    def setUp(self):
        self.client = APIClient()
        self.domain = DomainFactory(scheme="http", name="testserver", local=True)
        self.actor = ActorFactory(preferred_username="bob", reference__domain=self.domain)
        CollectionFactory(reference=self.actor.outbox, type=models.CollectionContext.Types.ORDERED)

    @httpretty.activate
    @silence_notifications("https://remote.example.com")
    def test_local_actor_can_post_follow_to_own_outbox(self):
        # Only actors with a django user can post to the outbox, so we
        # need to create an identity which we use to connect the actor
        # and user.
        identity = IdentityFactory(actor=self.actor)
        self.client.force_authenticate(user=identity.user)

        alice = "https://remote.example.com/users/alice"

        follow_activity = {
            "type": "Follow",
            "actor": "http://testserver/users/bob",
            "object": alice,
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            self.actor.outbox,
            data=json.dumps(follow_activity),
            content_type="application/ld+json",
        )

        # C2S should return 201 Created
        self.assertEqual(response.status_code, 201)

        # Verify side effects: FollowRequest should be created
        # Note: The activity ID will be assigned by the server
        self.assertTrue(
            models.FollowRequest.objects.filter(
                follower=self.actor.reference,
                followed__uri=alice,
            ).exists(),
            "FollowRequest should be created",
        )

    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @with_remote_reference("https://remote.example.com/users/alice", "standard/actor.alice.json")
    def test_remote_actor_cannot_post_to_outbox(self):
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

        # Should return 401 Unauthorized
        self.assertEqual(response.status_code, 401)


@override_settings(
    FEDERATION={
        "DEFAULT_URL": "http://testserver",
        "FORCE_INSECURE_HTTP": True,
        "REJECT_FOLLOW_REQUEST_CHECKS": [],
    },
    ALLOWED_HOSTS=["testserver"],
)
class OutboxSecurityTestCase(TransactionTestCase):
    """Security tests for C2S outbox operations"""

    def setUp(self):
        self.client = APIClient()
        self.domain = DomainFactory(scheme="http", name="testserver", local=True)
        self.bob = ActorFactory(preferred_username="bob", reference__domain=self.domain)
        self.alice = ActorFactory(preferred_username="alice", reference__domain=self.domain)
        CollectionFactory(reference=self.bob.outbox, type=models.CollectionContext.Types.ORDERED)
        CollectionFactory(reference=self.alice.outbox, type=models.CollectionContext.Types.ORDERED)
        self.bob_identity = IdentityFactory(actor=self.bob)
        self.alice_identity = IdentityFactory(actor=self.alice)

    def test_actor_cannot_create_object_attributed_to_someone_else(self):
        """
        C2S: Reject Create activity where attributedTo doesn't match authenticated actor.
        Attack vector: User tries to create content impersonating another user.
        """
        self.client.force_authenticate(user=self.bob_identity.user)

        # Bob tries to create a note attributed to Alice
        create_activity = {
            "type": "Create",
            "actor": "http://testserver/users/bob",
            "object": {
                "type": "Note",
                "content": "This is a malicious note pretending to be from Alice",
                "attributedTo": "http://testserver/users/alice",
            },
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/outbox",
            data=json.dumps(create_activity),
            content_type="application/ld+json",
        )

        # Should be rejected - attributedTo doesn't match actor
        self.assertIn(
            response.status_code,
            [400, 403],
            f"Should reject Create with mismatched attributedTo, got {response.status_code}",
        )

    def test_actor_cannot_update_object_belonging_to_someone_else(self):
        """
        C2S: Reject Update activity targeting an object owned by another actor.
        Attack vector: User tries to modify another user's content.
        """
        # Create a note owned by Alice
        alice_note = ObjectFactory(
            reference__domain=self.domain,
            reference__path="/notes/alice-note-123",
            type=models.ObjectContext.Types.NOTE,
            content="Alice's original content",
        )
        alice_note.attributed_to.add(self.alice.reference)

        # Bob authenticates and tries to update Alice's note
        self.client.force_authenticate(user=self.bob_identity.user)

        update_activity = {
            "type": "Update",
            "actor": "http://testserver/users/bob",
            "object": {
                "id": str(alice_note.reference.uri),
                "type": "Note",
                "content": "Bob hijacked Alice's note!",
            },
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/outbox",
            data=json.dumps(update_activity),
            content_type="application/ld+json",
        )

        # Should be rejected - Bob doesn't own Alice's note
        self.assertIn(
            response.status_code,
            [400, 403],
            f"Should reject Update of object not owned by actor, got {response.status_code}",
        )

        # Verify the note wasn't modified
        alice_note.refresh_from_db()
        self.assertEqual(alice_note.content, "Alice's original content")

    def test_actor_cannot_delete_object_belonging_to_someone_else(self):
        """
        C2S: Reject Delete activity targeting an object owned by another actor.
        Attack vector: User tries to delete another user's content.
        """
        # Create a note owned by Alice
        alice_note = ObjectFactory(
            reference__domain=self.domain,
            reference__path="/notes/alice-note-456",
            type=models.ObjectContext.Types.NOTE,
            content="Alice's note that should not be deleted",
        )
        alice_note.attributed_to.add(self.alice.reference)

        # Bob authenticates and tries to delete Alice's note
        self.client.force_authenticate(user=self.bob_identity.user)

        delete_activity = {
            "type": "Delete",
            "actor": "http://testserver/users/bob",
            "object": str(alice_note.reference.uri),
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        response = self.client.post(
            "/users/bob/outbox",
            data=json.dumps(delete_activity),
            content_type="application/ld+json",
        )

        # Should be rejected - Bob doesn't own Alice's note
        self.assertIn(
            response.status_code,
            [400, 403],
            f"Should reject Delete of object not owned by actor, got {response.status_code}",
        )

        # Verify the note still exists
        self.assertTrue(
            models.ObjectContext.objects.filter(reference=alice_note.reference).exists()
        )
