from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from activitypub.core.factories import ActorFactory, DomainFactory, IdentityFactory, ObjectFactory
from activitypub.core.models import ObjectContext
from tests.core.base import BaseTestCase


@override_settings(ROOT_URLCONF="tests.core.urls")
class RemoteReferenceProxyViewTestCase(BaseTestCase):
    def setUp(self):
        self.client = APIClient()
        self.remote_domain = DomainFactory(scheme="https", name="remote.example.com", local=False)
        self.local_domain = DomainFactory(scheme="http", name="testserver", local=True, port=80)

        self.local_ref = ActorFactory(
            reference__domain=self.local_domain,
            preferred_username="localuser",
        ).reference
        self.remote_object = ObjectFactory(
            reference__domain=self.remote_domain,
            reference__path="/test/note",
            type=ObjectContext.Types.NOTE,
            content="This is a note",
        )
        self.user = IdentityFactory(actor__reference__domain=self.local_domain).user

    def test_local_resource_returns_404(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("proxy-remote-object", kwargs={"resource": self.local_ref.uri})
        response = self.client.get(url, HTTP_ACCEPT="application/activity+json")

        self.assertEqual(response.status_code, 404)

    def test_unauthenticated_user_returns_401(self):
        url = reverse("proxy-remote-object", kwargs={"resource": self.remote_object.reference.uri})
        response = self.client.get(url, HTTP_ACCEPT="application/activity+json")
        self.assertEqual(response.status_code, 401)

    def test_unexisting_reference_returns_404(self):
        self.client.force_authenticate(user=self.user)
        url = reverse(
            "proxy-remote-object", kwargs={"resource": "https://remote.example.com/nonexistent"}
        )
        response = self.client.get(url, HTTP_ACCEPT="application/activity+json")

        self.assertEqual(response.status_code, 404)

    def test_valid_request_returns_json_ld_document(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("proxy-remote-object", kwargs={"resource": self.remote_object.reference.uri})
        response = self.client.get(url, HTTP_ACCEPT="application/activity+json")
        self.assertEqual(response.status_code, 200)

        data = response.json()

        self.assertEqual(data["id"], "https://remote.example.com/test/note")
        self.assertEqual(data["type"], "Note")
        self.assertEqual(data["content"], "This is a note")
