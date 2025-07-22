from django.core.exceptions import ValidationError
import httpretty

from activitypub import factories
from activitypub.models import (
    Activity,
    Actor,
    Link,
    LinkedDataModel,
    Object,
    Reference,
)
from activitypub.schemas import AS2

from .base import BaseTestCase, with_document_file, use_nodeinfo


class CoreTestCase(BaseTestCase):
    @httpretty.activate
    @use_nodeinfo("mastodon.example.com", "nodeinfo/mastodon.json")
    @with_document_file("mastodon/actor.json")
    def test_can_load_mastodon_actor(self, actor):
        self.assertEqual(actor.inbox.uri, "https://mastodon.example.com/users/tester/inbox")
        self.assertIsNotNone(actor.published)
        self.assertEqual(actor.published.year, 1999)

    @httpretty.activate
    @use_nodeinfo("mastodon.example.com", "nodeinfo/mastodon.json")
    @with_document_file("mastodon/actor.json")
    def test_can_load_hashtags_actor(self, actor):
        self.assertEqual(actor.tags.count(), 3)
        self.assertEqual(Link.objects.count(), 3)
        tag_names = list(Link.objects.order_by("name").values_list("name", flat=True))
        self.assertListEqual(tag_names, ["#activitypub", "#django", "#fediverse"])
        for link in Link.objects.all():
            self.assertEqual(link.type, str(AS2.Hashtag))
            self.assertIsNotNone(link.href)

    @httpretty.activate
    @use_nodeinfo("community.nodebb.org", "nodeinfo/nodebb.json")
    @with_document_file("nodebb/actor.json")
    def test_can_load_nodebb_actor(self, actor):
        self.assertEqual(actor.uri, "https://community.nodebb.org/uid/2")
        self.assertIsNotNone(actor.published)
        self.assertEqual(actor.published.year, 2013)
        self.assertEqual(actor.name, "julian")


class ReferenceTestCase(BaseTestCase):
    @httpretty.activate
    @use_nodeinfo("actor.example.com", "nodeinfo/mastodon.json")
    def test_can_reference_from_existing_object(self):
        actor = factories.ActorFactory(reference__uri="https://actor.example.com")
        self.assertEqual(actor.uri, "https://actor.example.com")
        self.assertEqual(actor.reference.item, actor, "referenced item is not about actor")

    def test_can_make_reference_for_public_actor(self):
        reference = Actor.PUBLIC.reference
        self.assertTrue(isinstance(reference, Reference))
        self.assertEqual(reference.uri, str(AS2.Public))

    def test_can_resolve_public_actor_reference(self):
        reference = Actor.PUBLIC.reference
        reference.resolve()
        self.assertEqual(reference.status, reference.STATUS.resolved)


class ObjectTestCase(BaseTestCase):
    def test_can_serialize(self):
        object = factories.ObjectFactory(
            reference__uri="https://example.com/objects/test",
            type=Object.Types.NOTE,
            content="This is a simple note",
        )

        json_ld_doc = object.to_jsonld()
        self.assertTrue("@context" in json_ld_doc)
        self.assertEqual(json_ld_doc["id"], object.uri)
        self.assertEqual(json_ld_doc["type"], "Note")
        self.assertEqual(json_ld_doc["content"], "This is a simple note")


class AccountTestCase(BaseTestCase):
    def test_can_get_subject_name(self):
        domain = factories.DomainFactory(name="example.com")
        person = factories.AccountFactory(username="test", domain=domain)
        self.assertEqual(person.subject_name, "@test@example.com")


class ActorTestCase(BaseTestCase):
    def test_can_get_public_actor(self):
        public_actor = Actor.PUBLIC
        self.assertEqual(public_actor.uri, str(AS2.Public))

    def test_can_get_only_create_specific_types(self):
        with self.assertRaises(ValidationError):
            actor = factories.ActorFactory(type="Invalid")
            actor.full_clean()

    def test_can_get_followers_list(self):
        alice = factories.ActorFactory(name="alice")
        bob = factories.ActorFactory(name="bob")

        # Bob follows alice
        alice.followers.append(item=bob)
        bob.following.append(item=alice)

        self.assertTrue(bob in alice.followed_by)

    def test_can_get_follows_list(self):
        alice = factories.ActorFactory(name="alice")
        bob = factories.ActorFactory(name="bob")

        # Bob follows alice
        alice.followers.append(item=bob)
        bob.following.append(item=alice)

        self.assertTrue(alice in bob.follows)

    def test_can_get_followers_inboxes(self):
        alice = factories.ActorFactory(name="alice")
        bob = factories.ActorFactory(name="bob")

        self.assertIsNotNone(bob.inbox, "Inbox for bob was not created")

        # Bob follows alice
        alice.followers.append(item=bob)
        bob.following.append(item=alice)

        self.assertTrue(bob.inbox in alice.followers_inboxes)


class CollectionTestCase(BaseTestCase):
    def setUp(self):
        self.collection = factories.CollectionFactory()

    def test_can_append_item(self):
        object = factories.ObjectFactory()
        self.collection.append(item=object)
        self.assertEqual(self.collection.collection_items.count(), 1)


class LinkTestCase(BaseTestCase):
    def test_links_do_not_need_references(self):
        link = factories.LinkFactory()
        self.assertIsNone(link.reference)

    def test_can_create_mentions(self):
        mention = factories.LinkFactory(type=Link.Types.MENTION)
        self.assertEqual(mention.type, str(AS2.Mention))

    def test_can_serialize(self):
        account = factories.AccountFactory()
        mention = factories.LinkFactory(
            type=Link.Types.MENTION, href=account.actor.uri, name=account.subject_name
        )
        json_ld_doc = mention.to_jsonld()
        self.assertFalse("id" in json_ld_doc)
        self.assertEqual(mention.href, account.actor.uri)


class ActivityTestCase(BaseTestCase):
    @httpretty.activate
    @use_nodeinfo("remote.example.com", "nodeinfo/mastodon.json")
    @use_nodeinfo("testserver", "nodeinfo/testserver.json")
    def test_can_deserialize_inbox_message(self):
        message = {
            "id": "https://remote.example.com/0cc0a50f-9043-4d9b-b82a-ab3cd13ab906",
            "type": "Follow",
            "actor": "https://remote.example.com/users/alice",
            "object": "http://testserver/users/bob",
            "@context": "https://www.w3.org/ns/activitystreams",
        }

        activity = LinkedDataModel.load(message)
        self.assertEqual(
            activity.uri, "https://remote.example.com/0cc0a50f-9043-4d9b-b82a-ab3cd13ab906"
        )
        self.assertEqual(activity.type, Activity.Types.FOLLOW)
        self.assertIsNotNone(
            Reference.objects.filter(uri="https://remote.example.com/users/alice").first(),
            "did not create reference for actor",
        )
        self.assertIsNotNone(
            Reference.objects.filter(uri="http://testserver/users/bob").first(),
            "did not create reference for object",
        )

        self.assertIsNone(activity.actor, "Actor was resolved when it should not")
        self.assertIsNone(activity.object, "Object was resolved when it should not")

    def test_can_do_follow(self):
        followed = factories.ActorFactory()
        follower = factories.ActorFactory()
        follow = factories.ActivityFactory(
            type=Activity.Types.FOLLOW, actor=follower, object=followed
        )
        follow.do()
        accept = factories.ActivityFactory(
            type=Activity.Types.ACCEPT, actor=followed, object=follow
        )
        accept.do()

        self.assertTrue(follower in followed.followers.items.all())

    def test_can_do_unfollow(self):
        followed = factories.ActorFactory()
        follower = factories.ActorFactory()
        follow = factories.ActivityFactory(
            type=Activity.Types.FOLLOW, actor=follower, object=followed
        )
        follow.do()
        accept = factories.ActivityFactory(
            type=Activity.Types.ACCEPT, actor=followed, object=follow
        )
        accept.do()
        unfollow = factories.ActivityFactory(
            type=Activity.Types.UNDO, actor=follower, object=follow
        )
        unfollow.do()

        self.assertFalse(follower in followed.followers.items.all())

    def test_replies_get_added_to_collection(self):
        note = factories.ObjectFactory(
            reference__uri="https://local.example.com/objects/first-note",
            reference__domain__local=True,
            type=Object.Types.NOTE,
            content="This is a simple note",
        )
        reply = factories.ObjectFactory(
            reference__uri="https://remote.example.com/objects/reply-to-note",
            reference__domain__local=False,
            type=Object.Types.NOTE,
            content="This is a reply",
        )

        reply.in_reply_to.add(note)

        self.assertTrue(note.replies.items.filter(id=reply.id).exists())

    def test_likes_get_added_to_likes_collection(self):
        note = factories.ObjectFactory(
            reference__uri="https://local.example.com/objects/first-note",
            reference__domain__local=True,
            type=Object.Types.NOTE,
            content="This is a simple note",
        )
        like = factories.ActivityFactory(
            reference__uri="https://remote.example.com/activity/like-note",
            reference__domain__local=False,
            type=Activity.Types.LIKE,
            object=note,
        )
        like.do()
        self.assertTrue(note.likes.items.filter(id=like.id).exists())

    def test_announces_get_added_to_shares_collection(self):
        note = factories.ObjectFactory(
            reference__uri="https://local.example.com/objects/first-note",
            reference__domain__local=True,
            type=Object.Types.NOTE,
            content="This is a simple note",
        )
        announce = factories.ActivityFactory(
            reference__uri="https://remote.example.com/activity/share-note",
            reference__domain__local=False,
            type=Activity.Types.ANNOUNCE,
            object=note,
        )
        announce.do()
        self.assertTrue(note.shares.items.filter(id=announce.id).exists())


class LinkedDataModelTestCase(BaseTestCase):
    def test_can_determine_collection_attributes(self):
        collection = factories.CollectionFactory()
        self.assertListEqual(
            collection.native_attributes,
            [
                "published",
                "updated",
                "name",
                "content",
                "media_type",
                "summary",
                "start_time",
                "end_time",
                "duration",
                "url",
                "type",
                "total_items",
                "current",
                "items",
            ],
        )
