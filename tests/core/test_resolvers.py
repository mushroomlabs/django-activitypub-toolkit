from django.test import TestCase

from activitypub.core.resolvers import ContextUriResolver


class ContextResolverTestCase(TestCase):
    def setUp(self):
        self.resolver = ContextUriResolver()

    def test_can_resolve_public_actor(self):
        self.assertTrue(self.resolver.can_resolve("https://www.w3.org/ns/activitystreams#Public"))

    def test_can_not_regular_uris(self):
        self.assertFalse(self.resolver.can_resolve("https://activitypub.rocks"))
