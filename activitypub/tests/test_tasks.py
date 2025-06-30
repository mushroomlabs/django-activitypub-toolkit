import os
from unittest.mock import patch

import httpretty

from activitypub.factories import (
    AccountFactory,
    ActivityFactory,
    ActorFactory,
    DomainFactory,
    MessageFactory,
)
from activitypub.models import Activity, Actor
from activitypub.tasks import process_standard_activity_flows

from .base import TEST_DOCUMENTS_FOLDER, BaseTestCase, use_nodeinfo


class MessageProcessingTestCase(BaseTestCase):
    def setUp(self):
        self.domain = DomainFactory(name="testserver", local=True)
        self.account = AccountFactory(username="bob", domain=self.domain)

    @httpretty.activate
    @use_nodeinfo("remote.example.com", "nodeinfo/mastodon.json")
    @use_nodeinfo("testserver", "nodeinfo/testserver.json")
    def test_message_authentication_resolves_sender(self):
        document = {
            "id": "https://remote.example.com/0cc0a50f-9043-4d9b-b82a-ab3cd13ab906",
            "type": "Follow",
            "actor": "https://remote.example.com/users/alice",
            "object": "http://testserver/users/bob",
            "@context": "https://www.w3.org/ns/activitystreams",
        }
        message = MessageFactory(
            sender__uri="https://remote.example.com/users/alice",
            recipient=self.account.actor.inbox.reference,
            activity__uri="https://remote.example.com/users/alice/follow/test-activity/",
            document=document,
        )

        with open(os.path.join(TEST_DOCUMENTS_FOLDER, "standard/actor.alice.json")) as doc:
            httpretty.register_uri(
                httpretty.GET, "https://remote.example.com/users/alice", body=doc.read()
            )
            message.authenticate()

            follower = Actor.objects.filter(
                reference__uri="https://remote.example.com/users/alice"
            ).first()

            self.assertIsNotNone(follower, "follower actor was not created")


class ActivityHandlingTestCase(BaseTestCase):
    def test_can_handle_undo(self):
        actor = ActorFactory()
        follow = ActivityFactory(type=Activity.Types.FOLLOW, object=actor)
        unfollow = ActivityFactory(type=Activity.Types.UNDO, object=follow)

        with patch("activitypub.models.Activity.undo") as undo:
            process_standard_activity_flows(follow.uri)
            self.assertFalse(undo.called)
            process_standard_activity_flows(unfollow.uri)
            self.assertTrue(undo.called)
