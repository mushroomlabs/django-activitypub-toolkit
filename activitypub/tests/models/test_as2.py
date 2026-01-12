import httpretty
from django.core.exceptions import ValidationError

from activitypub import factories
from activitypub.contexts import AS2
from activitypub.models import (
    Activity,
    CollectionContext,
    CollectionItem,
    Language,
    LanguageMap,
    LinkContext,
    LinkedDataDocument,
    ObjectContext,
    Reference,
)
from activitypub.tests.base import BaseTestCase, silence_notifications, use_nodeinfo


class ActorTestCase(BaseTestCase):
    def test_can_get_only_create_specific_types(self):
        with self.assertRaises(ValidationError):
            actor = factories.ActorFactory(type="Invalid")
            actor.full_clean()

    def test_can_get_followers_list(self):
        alice = factories.ActorFactory(name="alice")
        bob = factories.ActorFactory(name="bob")

        # Alice adds bob as followers
        alice.accept_follow(bob.reference)

        alice_followers = CollectionContext.make(alice.followers)

        self.assertTrue(alice_followers.contains(bob.reference))

    def test_can_get_follows_list(self):
        alice = factories.ActorFactory(name="alice")
        bob = factories.ActorFactory(name="bob")

        bob.follow(alice.reference)

        bob_follows = bob.following.get_by_context(CollectionContext)

        self.assertTrue(bob_follows.contains(alice.reference))

    def test_can_get_followers_inboxes(self):
        alice = factories.ActorFactory(name="alice")
        bob = factories.ActorFactory(name="bob")

        alice_followers = factories.CollectionFactory(reference=alice.followers)
        bob_following = factories.CollectionFactory(reference=bob.following)

        self.assertIsNotNone(bob.inbox, "Inbox for bob was not created")

        # Bob follows alice
        alice_followers.append(item=bob.reference)
        bob_following.append(item=alice.reference)

        self.assertTrue(bob.inbox in alice.followers_inboxes)


class CollectionTestCase(BaseTestCase):
    def setUp(self):
        self.collection = factories.CollectionFactory()

    def test_can_append_item(self):
        object = factories.ObjectFactory()
        self.collection.append(item=object.reference)
        self.assertEqual(self.collection.collection_items.count(), 1)


class LinkTestCase(BaseTestCase):
    def test_can_create_mentions(self):
        mention = factories.LinkFactory(type=LinkContext.Types.MENTION)
        self.assertEqual(mention.type, str(AS2.Mention))


class ActivityTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.local_instance = factories.InstanceFactory(
            domain__name="testserver", domain__scheme="http"
        )

    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @use_nodeinfo("http://testserver", "nodeinfo/testserver.json")
    def test_can_deserialize_inbox_message(self):
        reference = Reference.make(
            "https://remote.example.com/0cc0a50f-9043-4d9b-b82a-ab3cd13ab906"
        )

        message = LinkedDataDocument.objects.create(
            reference=reference,
            data={
                "id": "https://remote.example.com/0cc0a50f-9043-4d9b-b82a-ab3cd13ab906",
                "type": "Follow",
                "actor": "https://remote.example.com/users/alice",
                "object": "http://testserver/users/bob",
                "@context": "https://www.w3.org/ns/activitystreams",
            },
        )
        message.load()

        activity = reference.get_by_context(Activity)
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

    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @use_nodeinfo("http://testserver", "nodeinfo/testserver.json")
    @silence_notifications("https://remote.example.com")
    def test_can_do_follow(self):
        remote_domain = factories.DomainFactory(name="remote.example.com")

        followed = factories.ActorFactory(reference__domain=remote_domain)
        follower = factories.ActorFactory(reference__domain=remote_domain)
        follow = factories.ActivityFactory(
            type=Activity.Types.FOLLOW, actor=follower.reference, object=followed.reference
        )
        follow.do()
        accept = factories.ActivityFactory(
            type=Activity.Types.ACCEPT, actor=followed.reference, object=follow.reference
        )
        accept.do()

        self.assertTrue(
            CollectionItem.objects.filter(
                item=follower.reference, collection__reference=followed.followers
            ).exists()
        )

    @httpretty.activate
    @silence_notifications("https://remote.example.com")
    def test_can_do_unfollow(self):
        remote_domain = factories.DomainFactory(name="remote.example.com")

        followed = factories.ActorFactory(reference__domain=remote_domain)
        follower = factories.ActorFactory(reference__domain=remote_domain)
        follow = factories.ActivityFactory(
            type=Activity.Types.FOLLOW, actor=follower.reference, object=followed.reference
        )
        follow.do()
        accept = factories.ActivityFactory(
            type=Activity.Types.ACCEPT, actor=followed.reference, object=follow.reference
        )
        accept.do()
        unfollow = factories.ActivityFactory(
            type=Activity.Types.UNDO, actor=follower.reference, object=follow.reference
        )
        unfollow.do()

        self.assertFalse(
            CollectionItem.objects.filter(
                item=follower.reference, collection__reference=followed.followers
            ).exists()
        )

    @httpretty.activate
    @use_nodeinfo("https://local.example.com", "nodeinfo/testserver.json")
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    def test_replies_get_added_to_collection(self):
        note = factories.ObjectFactory(
            reference__uri="https://local.example.com/objects/first-note",
            reference__domain__name="local.example.com",
            reference__domain__local=True,
            type=ObjectContext.Types.NOTE,
            content="This is a simple note",
        )
        reply = factories.ObjectFactory(
            reference__uri="https://remote.example.com/objects/reply-to-note",
            reference__domain__name="remote.example.com",
            reference__domain__local=False,
            type=ObjectContext.Types.NOTE,
            content="This is a reply",
        )

        reply.in_reply_to.add(note.reference)

        self.assertIsNotNone(note.replies, "Replies collection should have been created")
        replies = note.replies.get_by_context(CollectionContext)
        self.assertTrue(replies.contains(item=reply.reference))

    @httpretty.activate
    @use_nodeinfo("https://local.example.com", "nodeinfo/testserver.json")
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    def test_likes_get_added_to_likes_collection(self):
        local_domain = factories.DomainFactory(name="local.example.com", local=True)
        remote_domain = factories.DomainFactory(name="remote.example.com", local=False)

        note = factories.ObjectFactory(
            reference__uri="https://local.example.com/objects/first-note",
            reference__domain=local_domain,
            type=ObjectContext.Types.NOTE,
            content="This is a simple note",
        )
        like = factories.ActivityFactory(
            reference__uri="https://remote.example.com/activity/like-note",
            reference__domain=remote_domain,
            type=Activity.Types.LIKE,
            object=note.reference,
        )
        like.do()

        likes_collection = CollectionContext.make(note.likes)

        self.assertTrue(likes_collection.contains(item=like.reference))

    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @use_nodeinfo("http://testserver", "nodeinfo/testserver.json")
    def test_announces_get_added_to_shares_collection(self):
        remote_domain = factories.DomainFactory(name="remote.example.com", local=False)

        note = factories.ObjectFactory(
            reference__uri="http://testserver/objects/first-note",
            reference__domain=self.local_instance.domain,
            type=ObjectContext.Types.NOTE,
            content="This is a simple note",
        )
        announce = factories.ActivityFactory(
            reference__uri="https://remote.example.com/activity/share-note",
            reference__domain=remote_domain,
            type=Activity.Types.ANNOUNCE,
            object=note.reference,
        )
        announce.do()
        note.refresh_from_db()
        shares_collection = CollectionContext.make(reference=note.shares)
        self.assertTrue(shares_collection.contains(announce.reference))

    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @use_nodeinfo("http://testserver", "nodeinfo/testserver.json")
    def test_undo_like_removes_from_collections(self):
        """Undoing a like removes it from both actor's liked and object's likes collections"""
        remote_domain = factories.DomainFactory(name="remote.example.com", local=False)

        # Create an actor with a liked collection
        actor = factories.ActorFactory(
            reference__uri="https://remote.example.com/users/alice",
            reference__domain=remote_domain,
        )
        # Create liked collection reference using factory
        liked_ref = factories.ReferenceFactory(
            uri="https://remote.example.com/users/alice/liked",
            domain=remote_domain,
        )
        actor.liked = liked_ref
        actor.save()

        # Create a local note
        note = factories.ObjectFactory(
            reference__uri="http://testserver/objects/note-123",
            reference__domain=self.local_instance.domain,
            type=ObjectContext.Types.NOTE,
            content="Test note",
        )

        # Create a like activity
        like = factories.ActivityFactory(
            reference__uri="https://remote.example.com/activity/like-1",
            reference__domain=remote_domain,
            type=Activity.Types.LIKE,
            actor=actor.reference,
            object=note.reference,
        )
        like.do()

        # Verify the like was added to both collections
        liked_collection = CollectionContext.make(actor.liked)
        likes_collection = CollectionContext.make(note.likes)

        self.assertTrue(
            liked_collection.contains(note.reference),
            "Object should be in actor's liked collection",
        )
        self.assertTrue(
            likes_collection.contains(like.reference),
            "Like should be in object's likes collection",
        )

        # Now undo the like
        undo = factories.ActivityFactory(
            reference__uri="https://remote.example.com/activity/undo-like-1",
            type=Activity.Types.UNDO,
            actor=actor.reference,
            object=like.reference,
        )
        undo.do()

        # Verify the like was removed from both collections
        self.assertFalse(
            liked_collection.contains(note.reference),
            "Object should be removed from actor's liked collection",
        )
        self.assertFalse(
            likes_collection.contains(like.reference),
            "Like should be removed from object's likes collection",
        )

    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @use_nodeinfo("http://testserver", "nodeinfo/testserver.json")
    def test_undo_like_when_actor_has_no_liked_collection(self):
        """undoing a like works even when actor has no liked collection"""
        remote_domain = factories.DomainFactory(name="remote.example.com", local=False)

        actor = factories.ActorFactory(
            reference__uri="https://remote.example.com/users/bob",
            reference__domain=remote_domain,
        )

        # Don't set a liked collection for this actor
        note = factories.ObjectFactory(
            reference__uri="http://testserver/objects/note-456",
            reference__domain=self.local_instance.domain,
            type=ObjectContext.Types.NOTE,
            content="Another test note",
        )

        like = factories.ActivityFactory(
            reference__uri="https://remote.example.com/activity/like-2",
            reference__domain=remote_domain,
            type=Activity.Types.LIKE,
            actor=actor.reference,
            object=note.reference,
        )
        like.do()

        # Verify the like was added to the object's likes collection
        likes_collection = CollectionContext.make(note.likes)
        self.assertTrue(likes_collection.contains(like.reference))

        # Undo the like - should not crash even though actor has no liked collection
        undo = factories.ActivityFactory(
            reference__uri="https://remote.example.com/activity/undo-like-2",
            type=Activity.Types.UNDO,
            actor=actor.reference,
            object=like.reference,
        )
        undo.do()

        # Verify the like was removed from object's likes collection
        self.assertFalse(likes_collection.contains(like.reference))

    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @use_nodeinfo("http://testserver", "nodeinfo/testserver.json")
    def test_undo_announce_removes_from_shares_collection(self):
        """undoing an announce removes it from the object's shares collection"""
        remote_domain = factories.DomainFactory(name="remote.example.com", local=False)

        actor = factories.ActorFactory(
            reference__uri="https://remote.example.com/users/carol",
            reference__domain=remote_domain,
        )

        note = factories.ObjectFactory(
            reference__uri="http://testserver/objects/note-789",
            reference__domain=self.local_instance.domain,
            type=ObjectContext.Types.NOTE,
            content="Note to be shared",
        )

        # Create and do an announce
        announce = factories.ActivityFactory(
            reference__uri="https://remote.example.com/activity/announce-1",
            reference__domain=remote_domain,
            type=Activity.Types.ANNOUNCE,
            actor=actor.reference,
            object=note.reference,
        )
        announce.do()

        # Verify the announce was added to shares collection
        note.refresh_from_db()
        self.assertIsNotNone(note.shares, "Shares collection should be created")
        shares_collection = CollectionContext.make(note.shares)
        self.assertTrue(
            shares_collection.contains(announce.reference),
            "Announce should be in shares collection",
        )

        # Undo the announce
        undo = factories.ActivityFactory(
            reference__uri="https://remote.example.com/activity/undo-announce-1",
            type=Activity.Types.UNDO,
            actor=actor.reference,
            object=announce.reference,
        )
        undo.do()

        # Verify the announce was removed from shares collection
        self.assertFalse(
            shares_collection.contains(announce.reference),
            "Announce should be removed from shares collection",
        )

    def test_undo_announce_when_shares_is_none(self):
        """undoing an announce handles the case where object has no shares collection"""
        actor = factories.ActorFactory()
        note = factories.ObjectFactory(
            type=ObjectContext.Types.NOTE,
            content="Note without shares",
        )

        announce = factories.ActivityFactory(
            type=Activity.Types.ANNOUNCE,
            actor=actor.reference,
            object=note.reference,
        )

        # Create an undo without doing the announce first
        undo = factories.ActivityFactory(
            type=Activity.Types.UNDO,
            actor=actor.reference,
            object=announce.reference,
        )

        # Should not crash when object has no shares collection
        undo.do()  # Should complete without error

    @httpretty.activate
    @use_nodeinfo("https://local.example.com", "nodeinfo/testserver.json")
    def test_do_add_adds_item_to_actor_owned_collection(self):
        """Add activity adds an item to an actor-owned collection"""
        local_domain = factories.DomainFactory(name="local.example.com", local=True)

        alice = factories.ActorFactory(name="Alice", reference__domain=local_domain)

        # Create a custom collection owned by the actor (e.g., a featured collection)
        featured_ref = factories.ReferenceFactory(
            uri=f"{alice.uri}/collections/featured", domain=local_domain
        )
        featured_collection = CollectionContext.make(featured_ref, name="Featured")
        featured_collection.attributed_to.add(alice.reference)

        # Create a note to add to the collection
        note = factories.ObjectFactory(type=ObjectContext.Types.NOTE, content="Featured note")

        # Create an Add activity
        add_activity = factories.ActivityFactory(
            type=Activity.Types.ADD,
            actor=alice.reference,
            object=note.reference,
            target=featured_ref,
        )

        # Execute the add
        add_activity.do()

        # Verify the note was added to the collection
        self.assertTrue(
            featured_collection.contains(note.reference),
            "Note should be added to the featured collection",
        )

    def test_do_add_fails_when_collection_not_owned_by_actor(self):
        """Add activity fails when trying to add to a collection not owned by the actor"""
        remote_domain = factories.DomainFactory(name="remote.example.com", local=False)

        alice = factories.ActorFactory(
            name="Alice",
            reference__domain=remote_domain,
        )
        bob = factories.ActorFactory(
            name="Bob",
            reference__domain=remote_domain,
        )

        # Create a collection owned by bob
        bob_collection_ref = factories.ReferenceFactory(
            uri=f"{bob.uri}/collections/featured",
            domain=bob.reference.domain,
        )
        bob_collection = CollectionContext.make(bob_collection_ref)
        bob_collection.attributed_to.add(bob.reference)

        note = factories.ObjectFactory(
            type=ObjectContext.Types.NOTE,
            content="Note to add",
        )

        # Alice tries to add to Bob's collection
        add_activity = factories.ActivityFactory(
            type=Activity.Types.ADD,
            actor=alice.reference,
            object=note.reference,
            target=bob_collection_ref,
        )

        add_activity.do()

        # The add should fail (logged as warning), and the item should NOT be added
        self.assertFalse(
            bob_collection.contains(note.reference),
            "Note should NOT be added to other actor's collection",
        )

    def test_do_add_when_target_is_none(self):
        """Add activity handles gracefully when target is None"""
        actor = factories.ActorFactory()
        note = factories.ObjectFactory()

        add_activity = factories.ActivityFactory(
            type=Activity.Types.ADD,
            actor=actor.reference,
            object=note.reference,
            target=None,
        )

        # Should not crash
        add_activity.do()

    @httpretty.activate
    @use_nodeinfo("https://local.example.com", "nodeinfo/testserver.json")
    def test_do_remove_removes_item_from_actor_owned_collection(self):
        """Remove activity removes an item from an actor-owned collection"""
        local_domain = factories.DomainFactory(name="local.example.com", local=True)

        alice = factories.ActorFactory(
            name="Alice",
            reference__domain=local_domain,
        )

        featured_ref = factories.ReferenceFactory(
            uri=f"{alice.uri}/collections/featured",
            domain=local_domain,
        )
        featured_collection = CollectionContext.make(featured_ref, name="Featured")
        featured_collection.attributed_to.add(alice.reference)

        note = factories.ObjectFactory(
            type=ObjectContext.Types.NOTE,
            content="Featured note",
        )

        # First add the note to the collection
        featured_collection.append(note.reference)
        self.assertTrue(
            featured_collection.contains(note.reference), "Note should be in collection initially"
        )

        # Create a Remove activity
        remove_activity = factories.ActivityFactory(
            type=Activity.Types.REMOVE,
            actor=alice.reference,
            object=note.reference,
            target=featured_ref,
        )

        # Execute the remove
        remove_activity.do()

        # Verify the note was removed from the collection
        self.assertFalse(
            featured_collection.contains(note.reference),
            "Note should be removed from the featured collection",
        )

    def test_do_remove_from_followers_collection(self):
        """Remove activity can remove an item from actor's followers"""
        local_domain = factories.DomainFactory(name="local.example.com", local=True)

        alice = factories.ActorFactory(
            name="Alice",
            reference__domain=local_domain,
        )
        followers_collection = CollectionContext.make(alice.followers)

        follower = factories.ActorFactory()

        # Add follower to the collection
        followers_collection.append(follower.reference)
        self.assertTrue(followers_collection.contains(follower.reference))

        # Remove the follower
        remove_activity = factories.ActivityFactory(
            type=Activity.Types.REMOVE,
            actor=alice.reference,
            object=follower.reference,
            target=alice.followers,
        )

        remove_activity.do()

        self.assertFalse(
            followers_collection.contains(follower.reference), "Follower should be removed"
        )

    def test_do_remove_fails_when_collection_not_owned_by_actor(self):
        """Remove activity fails when trying to remove from a collection not owned by the actor"""
        remote_domain = factories.DomainFactory(name="remote.example.com", local=False)

        alice = factories.ActorFactory(
            name="Alice",
            reference__domain=remote_domain,
        )
        bob = factories.ActorFactory(
            name="Bob",
            reference__domain=remote_domain,
        )

        bob_collection_ref = factories.ReferenceFactory(
            uri=f"{bob.uri}/collections/items",
            domain=bob.reference.domain,
        )
        bob_collection = CollectionContext.make(bob_collection_ref)

        note = factories.ObjectFactory()
        bob_collection.append(note.reference)
        self.assertTrue(bob_collection.contains(note.reference))

        # Alice tries to remove from Bob's collection
        remove_activity = factories.ActivityFactory(
            type=Activity.Types.REMOVE,
            actor=alice.reference,
            object=note.reference,
            target=bob_collection_ref,
        )

        remove_activity.do()

        # The remove should fail, and the item should still be in the collection
        self.assertTrue(
            bob_collection.contains(note.reference),
            "Note should still be in collection after failed remove",
        )

    def test_do_remove_when_target_is_none(self):
        """Remove activity handles gracefully when target is None"""
        actor = factories.ActorFactory()
        note = factories.ObjectFactory()

        remove_activity = factories.ActivityFactory(
            type=Activity.Types.REMOVE,
            actor=actor.reference,
            object=note.reference,
            target=None,
        )

        # Should not crash
        remove_activity.do()


class LanguageTestCase(BaseTestCase):
    def test_can_create_language(self):
        language = Language.create_language(
            code="en",
            iso_639_1="en",
            iso_639_3="eng",
            name="English",
        )
        self.assertEqual(language.code, "en")
        self.assertEqual(language.iso_639_1, "en")
        self.assertEqual(language.iso_639_3, "eng")
        self.assertEqual(language.name, "English")
        self.assertEqual(str(language), "English (en)")

    def test_can_create_language_variant(self):
        language = Language.create_language(
            code="pt-BR",
            iso_639_1="pt",
            iso_639_3="por",
            name="Portuguese (Brazil)",
        )
        self.assertEqual(language.code, "pt-br")
        self.assertEqual(language.iso_639_1, "pt")

    def test_language_code_is_unique(self):
        en = Language.create_language(code="en", iso_639_1="en", iso_639_3="eng", name="English")
        with self.assertRaises(Exception):
            reference = en.reference
            Language.objects.create(
                reference=reference, code="en", iso_639_1="en", iso_639_3="eng", name="English"
            )

    def test_top_languages_enum(self):
        self.assertEqual(LanguageMap.EN.code, "en")
        self.assertEqual(LanguageMap.EN.iso_639_3, "eng")
        self.assertEqual(LanguageMap.EN.name, "English")

        self.assertEqual(LanguageMap.PT_BR.code, "pt-br")
        self.assertEqual(LanguageMap.PT_BR.iso_639_3, "por")
        self.assertEqual(LanguageMap.PT_BR.name, "Portuguese (Brazil)")

    def test_can_load_languages(self):
        self.assertEqual(Language.objects.count(), 0)

        Language.load()

        self.assertGreater(Language.objects.count(), 0)
        self.assertEqual(Language.objects.count(), len(LanguageMap))

        en_language = Language.objects.get(code="en")
        self.assertEqual(en_language.iso_639_1, "en")
        self.assertEqual(en_language.iso_639_3, "eng")
        self.assertEqual(en_language.name, "English")

        pt_br_language = Language.objects.get(code="pt-br")
        self.assertEqual(pt_br_language.iso_639_1, "pt")
        self.assertEqual(pt_br_language.iso_639_3, "por")
        self.assertEqual(pt_br_language.name, "Portuguese (Brazil)")

        pt_language = Language.objects.get(code="pt")
        self.assertEqual(pt_language.iso_639_1, "pt")
        self.assertEqual(pt_language.iso_639_3, "por")
        self.assertEqual(pt_language.name, "Portuguese")

    def test_load_languages_is_idempotent(self):
        Language.load()
        count_first = Language.objects.count()

        Language.load()
        count_second = Language.objects.count()

        self.assertEqual(count_first, count_second)
