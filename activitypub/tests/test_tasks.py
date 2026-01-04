import os
from unittest.mock import patch

import httpretty
from django.test import TestCase

from activitypub.factories import (
    AccountFactory,
    ActivityFactory,
    ActorFactory,
    DomainFactory,
    LinkedDataDocumentFactory,
    NotificationFactory,
    NotificationProcessResultFactory,
)
from activitypub.models import Activity, Actor, Notification
from activitypub.tasks import clear_processed_messages, process_standard_activity_flows

from .base import TEST_DOCUMENTS_FOLDER, BaseTestCase, use_nodeinfo, silence_notifications


class CeleryConfigurationTestCase(TestCase):
    def testCanCallTask(self):
        NotificationProcessResultFactory()

        self.assertEqual(Notification.objects.count(), 1, "factory did not create notification")

        clear_processed_messages()

        self.assertEqual(
            Notification.objects.count(), 0, "direct call did delete processed notifications"
        )

        NotificationProcessResultFactory()

        clear_processed_messages.delay()

        self.assertEqual(
            Notification.objects.count(), 0, "Delay call did not delete processed notifications"
        )


class NotificationProcessingTestCase(BaseTestCase):
    def setUp(self):
        self.domain = DomainFactory(scheme="http", name="testserver", local=True, port=80)
        self.account = AccountFactory(username="bob", domain=self.domain)

    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @use_nodeinfo("http://testserver", "nodeinfo/testserver.json")
    def test_message_authentication_resolves_sender(self):
        document = LinkedDataDocumentFactory(
            data={
                "id": "https://remote.example.com/users/alice/follow/test-activity/",
                "type": "Follow",
                "actor": "https://remote.example.com/users/alice",
                "object": "http://testserver/users/bob",
                "@context": "https://www.w3.org/ns/activitystreams",
            },
            reference__uri="https://remote.example.com/users/alice/follow/test-activity/",
        )
        message = NotificationFactory(
            sender__uri="https://remote.example.com/users/alice",
            target=self.account.actor.inbox,
            resource=document.reference,
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
    @httpretty.activate
    @silence_notifications("https://remote.example.com")
    def test_can_handle_undo(self):
        actor = ActorFactory(reference__domain__name="remote.example.com")
        follow = ActivityFactory(type=Activity.Types.FOLLOW, object=actor.reference)
        unfollow = ActivityFactory(type=Activity.Types.UNDO, object=follow.reference)

        with patch("activitypub.models.ap.Activity.undo") as undo:
            process_standard_activity_flows(follow.reference)
            self.assertFalse(undo.called)
            process_standard_activity_flows(unfollow.reference)
            self.assertTrue(undo.called)
