import httpretty

from activitypub import factories
from activitypub.contexts import AS2
from activitypub.models import ActorContext, EndpointContext, LinkContext
from activitypub.tests.base import BaseTestCase, use_nodeinfo, with_document_file


class CoreTestCase(BaseTestCase):
    @httpretty.activate
    @use_nodeinfo("https://mastodon.example.com", "nodeinfo/mastodon.json")
    @with_document_file("mastodon/actor.json")
    def test_can_load_mastodon_actor(self, document):
        actor = document.reference.get_by_context(ActorContext)
        self.assertEqual(actor.inbox.uri, "https://mastodon.example.com/users/tester/inbox")
        self.assertIsNotNone(actor.published)
        self.assertEqual(actor.published.year, 1999)

    @httpretty.activate
    @use_nodeinfo("https://mastodon.example.com", "nodeinfo/mastodon.json")
    @with_document_file("mastodon/actor.json")
    def test_can_load_hashtags_actor(self, document):
        actor = document.reference.get_by_context(ActorContext)
        self.assertEqual(actor.tags.count(), 3)
        self.assertEqual(LinkContext.objects.count(), 3)
        tag_names = list(LinkContext.objects.order_by("name").values_list("name", flat=True))
        self.assertListEqual(tag_names, ["#activitypub", "#django", "#fediverse"])
        for link in LinkContext.objects.all():
            self.assertEqual(link.type, str(AS2.Hashtag))
            self.assertIsNotNone(link.href)

    @httpretty.activate
    @use_nodeinfo("https://mastodon.example.com", "nodeinfo/mastodon.json")
    @with_document_file("mastodon/actor.json")
    def test_can_load_shared_inbox_endpoint(self, document):
        actor_endpoints = EndpointContext.objects.filter(
            reference__actor_endpoints__reference=document.reference
        ).first()

        self.assertIsNotNone(actor_endpoints)

        self.assertEqual(actor_endpoints.shared_inbox, "https://mastodon.example.com/inbox")

    @httpretty.activate
    @use_nodeinfo("https://community.nodebb.org", "nodeinfo/nodebb.json")
    @with_document_file("nodebb/actor.json")
    def test_can_load_nodebb_actor(self, document):
        actor = document.reference.get_by_context(ActorContext)
        self.assertEqual(actor.uri, "https://community.nodebb.org/uid/2")
        self.assertIsNotNone(actor.published)
        self.assertEqual(actor.published.year, 2013)
        self.assertEqual(actor.name, "julian")

    @httpretty.activate
    @use_nodeinfo("https://lemmy.example.com", "nodeinfo/lemmy.json")
    @with_document_file("lemmy/actor.json")
    def test_can_load_lemmy_actor(self, document):
        actor = document.reference.get_by_context(ActorContext)
        self.assertEqual(actor.uri, "https://lemmy.example.com/u/alice")
        self.assertIsNotNone(actor.published)
        self.assertIsNone(actor.name)
        self.assertEqual(actor.published.year, 2025)
        self.assertEqual(actor.preferred_username, "alice")


class ReferenceTestCase(BaseTestCase):
    @httpretty.activate
    @use_nodeinfo("https://actor.example.com", "nodeinfo/mastodon.json")
    def test_can_reference_from_existing_object(self):
        actor = factories.ActorFactory(reference__uri="https://actor.example.com")
        self.assertEqual(actor.uri, "https://actor.example.com")
        self.assertTrue(ActorContext.objects.filter(reference=actor.reference).exists())
