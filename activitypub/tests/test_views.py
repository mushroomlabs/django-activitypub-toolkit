import json
from unittest.mock import patch

import httpretty
from django.test import override_settings
from django.urls import resolve
from rest_framework.test import APIClient

from activitypub.factories import AccountFactory, DomainFactory
from activitypub.tests.base import BaseTestCase, use_nodeinfo

CONTENT_TYPE = "application/ld+json"


@override_settings(
    REST_FRAMEWORK={"TEST_REQUEST_DEFAULT_FORMAT": "json"},
)
class InboxViewTestCase(BaseTestCase):
    def setUp(self):
        self.client = APIClient()
        self.domain = DomainFactory(name="testserver", local=True)
        self.account = AccountFactory(username="bob", domain=self.domain)

    @httpretty.activate
    @use_nodeinfo("testserver", "nodeinfo/testserver.json")
    def test_can_resolve_to_generic_ap_object_view(self):
        self.assertEqual(self.account.actor.inbox.uri, "http://testserver/users/bob/inbox")
        resolve("/users/bob/inbox")

    @httpretty.activate
    @use_nodeinfo("remote.example.com", "nodeinfo/mastodon.json")
    @patch("activitypub.views.activitystreams.process_message.delay_on_commit")
    def test_can_post_activity(self, process_message_task):
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
        self.assertTrue(process_message_task.called)
