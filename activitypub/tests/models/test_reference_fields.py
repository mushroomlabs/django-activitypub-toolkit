from django.db.models import Q

from activitypub import factories
from activitypub.models import ActivityContext, ObjectContext, SecV1Context
from activitypub.models.fields import ContextProxy
from activitypub.tests.base import BaseTestCase


class ReferenceFieldQuerySetTestCase(BaseTestCase):
    """Test QuerySet filtering with ReferenceField."""

    def test_filter_by_reference_exact(self):
        """Test Model.objects.filter(field=ref)"""
        # Create actor and key
        actor_ref = factories.ReferenceFactory()
        key = factories.SecV1ContextFactory()
        key.owner.add(actor_ref)

        # Filter should work
        results = SecV1Context.objects.filter(owner=actor_ref)
        self.assertIn(key, results)
        self.assertEqual(results.count(), 1)

    def test_filter_by_reference_multiple_matches(self):
        """Test filtering returns multiple matches"""
        actor_ref = factories.ReferenceFactory()
        key1 = factories.SecV1ContextFactory()
        key2 = factories.SecV1ContextFactory()
        key1.owner.add(actor_ref)
        key2.owner.add(actor_ref)

        results = SecV1Context.objects.filter(owner=actor_ref)
        self.assertEqual(results.count(), 2)
        self.assertIn(key1, results)
        self.assertIn(key2, results)

    def test_filter_by_reference_no_match(self):
        """Test filtering with no matches returns empty"""
        actor_ref = factories.ReferenceFactory()
        other_ref = factories.ReferenceFactory()
        key = factories.SecV1ContextFactory()
        key.owner.add(other_ref)

        results = SecV1Context.objects.filter(owner=actor_ref)
        self.assertEqual(results.count(), 0)

    def test_filter_by_reference_in(self):
        """Test Model.objects.filter(field__in=[ref1, ref2])"""
        ref1 = factories.ReferenceFactory()
        ref2 = factories.ReferenceFactory()
        ref3 = factories.ReferenceFactory()

        key1 = factories.SecV1ContextFactory()
        key2 = factories.SecV1ContextFactory()
        key3 = factories.SecV1ContextFactory()

        key1.owner.add(ref1)
        key2.owner.add(ref2)
        key3.owner.add(ref3)

        results = SecV1Context.objects.filter(owner__in=[ref1, ref2])
        self.assertEqual(results.count(), 2)
        self.assertIn(key1, results)
        self.assertIn(key2, results)
        self.assertNotIn(key3, results)

    def test_filter_by_reference_isnull_true(self):
        """Test Model.objects.filter(field__isnull=True)"""
        key_with_owner = factories.SecV1ContextFactory()
        key_with_owner.owner.add(factories.ReferenceFactory())

        key_without_owner = factories.SecV1ContextFactory()

        results = SecV1Context.objects.filter(owner__isnull=True)
        self.assertIn(key_without_owner, results)
        self.assertNotIn(key_with_owner, results)

    def test_filter_by_reference_isnull_false(self):
        """Test Model.objects.filter(field__isnull=False)"""
        key_with_owner = factories.SecV1ContextFactory()
        key_with_owner.owner.add(factories.ReferenceFactory())

        key_without_owner = factories.SecV1ContextFactory()

        results = SecV1Context.objects.filter(owner__isnull=False)
        self.assertIn(key_with_owner, results)
        self.assertNotIn(key_without_owner, results)

    def test_filter_chaining(self):
        """Test that filter chaining works"""
        ref1 = factories.ReferenceFactory()
        key1 = factories.SecV1ContextFactory(public_key_pem="KEY1")
        key2 = factories.SecV1ContextFactory(public_key_pem="KEY2")
        key1.owner.add(ref1)
        key2.owner.add(ref1)

        results = SecV1Context.objects.filter(owner=ref1).filter(public_key_pem="KEY1")
        self.assertEqual(results.count(), 1)
        self.assertIn(key1, results)

    def test_filter_with_q_objects(self):
        """Test filtering with Q objects"""
        ref1 = factories.ReferenceFactory()
        ref2 = factories.ReferenceFactory()
        key1 = factories.SecV1ContextFactory()
        key2 = factories.SecV1ContextFactory()
        key1.owner.add(ref1)
        key2.owner.add(ref2)

        results = SecV1Context.objects.filter(Q(owner=ref1) | Q(owner=ref2))
        self.assertEqual(results.count(), 2)

    def test_exclude(self):
        """Test exclude() method"""
        ref1 = factories.ReferenceFactory()
        key1 = factories.SecV1ContextFactory()
        key2 = factories.SecV1ContextFactory()
        key1.owner.add(ref1)

        results = SecV1Context.objects.exclude(owner=ref1)
        self.assertNotIn(key1, results)
        self.assertIn(key2, results)

    def test_related_manager_still_works(self):
        """Ensure instance.field.all() still works after adding path_info"""
        key = factories.SecV1ContextFactory()
        ref = factories.ReferenceFactory()
        key.owner.add(ref)

        # This should still work via ReferenceRelatedManager
        self.assertEqual(key.owner.count(), 1)
        self.assertIn(ref, key.owner.all())

    def test_filter_on_object_context_tags(self):
        """Test filtering works on other ReferenceFields like ObjectContext.tags"""
        tag_ref = factories.ReferenceFactory()
        obj = factories.ObjectFactory()
        obj.tags.add(tag_ref)

        results = ObjectContext.objects.filter(tags=tag_ref)
        self.assertIn(obj, results)

    def test_multiple_reference_fields_filter(self):
        """Test filtering when model has multiple ReferenceFields"""
        actor_ref = factories.ReferenceFactory()
        object_ref = factories.ReferenceFactory()

        activity = factories.ActivityContextFactory(actor=actor_ref, object=object_ref)

        # Filter by actor
        results = ActivityContext.objects.filter(actor=actor_ref)
        self.assertIn(activity, results)

        # Filter by object
        results = ActivityContext.objects.filter(object=object_ref)
        self.assertIn(activity, results)

        # Filter by both
        results = ActivityContext.objects.filter(actor=actor_ref, object=object_ref)
        self.assertIn(activity, results)


class RelatedContextFieldTestCase(BaseTestCase):
    """Test RelatedContextField and ContextProxy functionality."""

    def test_can_access_related_context_via_proxy(self):
        """Test accessing a related context through RelatedContextField"""
        actor = factories.ActorFactory()

        # Access secv1 through RelatedContextField - should return a ContextProxy
        secv1_proxy = actor.secv1
        self.assertIsInstance(secv1_proxy, ContextProxy)

    def test_proxy_lazy_loads_context(self):
        """Test that ContextProxy lazy-loads the context instance"""
        actor = factories.ActorFactory()

        # Initially, no SecV1Context should exist in database
        self.assertFalse(SecV1Context.objects.filter(reference=actor.reference).exists())

        # Access an attribute through the proxy - should create the context in memory
        actor.secv1.public_key_pem = "-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----"

        # Accessing the attribute should work (proving the context was created)
        self.assertEqual(
            actor.secv1.public_key_pem,
            "-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----",
        )

        # Should still not be in database until saved
        self.assertFalse(SecV1Context.objects.filter(reference=actor.reference).exists())

    def test_proxy_can_set_and_get_attributes(self):
        """Test setting and getting attributes through the proxy"""
        actor = factories.ActorFactory()

        # Set attributes through proxy
        actor.secv1.public_key_pem = (
            "-----BEGIN PUBLIC KEY-----\ntest_key\n-----END PUBLIC KEY-----"
        )

        # Get attributes through proxy
        self.assertEqual(
            actor.secv1.public_key_pem,
            "-----BEGIN PUBLIC KEY-----\ntest_key\n-----END PUBLIC KEY-----",
        )

    def test_proxy_save_creates_in_database(self):
        """Test that saving through proxy persists to database"""
        actor = factories.ActorFactory()

        # Initially not in database
        self.assertFalse(SecV1Context.objects.filter(reference=actor.reference).exists())

        # Modify and save
        actor.secv1.public_key_pem = (
            "-----BEGIN PUBLIC KEY-----\nmodified\n-----END PUBLIC KEY-----"
        )
        actor.secv1.save()

        # Now should exist in database
        self.assertTrue(SecV1Context.objects.filter(reference=actor.reference).exists())

    def test_proxy_save_persists_to_database(self):
        """Test that calling save() on proxy persists changes"""
        actor = factories.ActorFactory()

        # Set a value and save
        actor.secv1.public_key_pem = (
            "-----BEGIN PUBLIC KEY-----\npersisted\n-----END PUBLIC KEY-----"
        )
        actor.secv1.save()

        # Verify it was saved to the database
        saved_context = SecV1Context.objects.get(reference=actor.reference)
        self.assertEqual(
            saved_context.public_key_pem,
            "-----BEGIN PUBLIC KEY-----\npersisted\n-----END PUBLIC KEY-----",
        )

    def test_proxy_loads_existing_context(self):
        """Test that proxy loads an existing context if it exists"""
        actor = factories.ActorFactory()

        # Create a SecV1Context directly
        existing_context = SecV1Context.objects.create(
            reference=actor.reference,
            public_key_pem="-----BEGIN PUBLIC KEY-----\nexisting\n-----END PUBLIC KEY-----",
        )

        # Access through proxy should load the existing context
        self.assertEqual(
            actor.secv1.public_key_pem,
            "-----BEGIN PUBLIC KEY-----\nexisting\n-----END PUBLIC KEY-----",
        )

        # Modifying should update the same instance
        actor.secv1.public_key_pem = (
            "-----BEGIN PUBLIC KEY-----\nmodified\n-----END PUBLIC KEY-----"
        )
        actor.secv1.save()

        # Verify it updated the existing context, not created a new one
        self.assertEqual(SecV1Context.objects.filter(reference=actor.reference).count(), 1)
        updated_context = SecV1Context.objects.get(reference=actor.reference)
        self.assertEqual(updated_context.pk, existing_context.pk)
        self.assertEqual(
            updated_context.public_key_pem,
            "-----BEGIN PUBLIC KEY-----\nmodified\n-----END PUBLIC KEY-----",
        )

    def test_proxy_is_cached_per_instance(self):
        """Test that the proxy is cached and returns the same instance"""
        actor = factories.ActorFactory()

        # Access proxy twice
        proxy1 = actor.secv1
        proxy2 = actor.secv1

        # Should be the exact same object
        self.assertIs(proxy1, proxy2)

    def test_proxy_modifications_persist_across_access(self):
        """Test that modifications persist when accessing the proxy multiple times"""
        actor = factories.ActorFactory()

        # Set a value through the proxy
        actor.secv1.public_key_pem = "-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----"

        # Access proxy again - should still have the value
        self.assertEqual(
            actor.secv1.public_key_pem,
            "-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----",
        )

        # Modify again through the same proxy
        actor.secv1.public_key_pem = (
            "-----BEGIN PUBLIC KEY-----\nmodified_again\n-----END PUBLIC KEY-----"
        )

        # Should have the new value
        self.assertEqual(
            actor.secv1.public_key_pem,
            "-----BEGIN PUBLIC KEY-----\nmodified_again\n-----END PUBLIC KEY-----",
        )

    def test_different_instances_have_separate_proxies(self):
        """Test that different model instances have separate proxies"""
        actor1 = factories.ActorFactory()
        actor2 = factories.ActorFactory()

        # Set different values
        actor1.secv1.public_key_pem = (
            "-----BEGIN PUBLIC KEY-----\nactor1\n-----END PUBLIC KEY-----"
        )
        actor2.secv1.public_key_pem = (
            "-----BEGIN PUBLIC KEY-----\nactor2\n-----END PUBLIC KEY-----"
        )

        # Values should be independent
        self.assertEqual(
            actor1.secv1.public_key_pem,
            "-----BEGIN PUBLIC KEY-----\nactor1\n-----END PUBLIC KEY-----",
        )
        self.assertEqual(
            actor2.secv1.public_key_pem,
            "-----BEGIN PUBLIC KEY-----\nactor2\n-----END PUBLIC KEY-----",
        )

    def test_proxy_with_owner_reference_field(self):
        """Test that proxy works alongside ReferenceField usage"""
        actor = factories.ActorFactory()
        owner_ref = factories.ReferenceFactory()

        # Set up SecV1Context with both proxy and ReferenceField
        actor.secv1.public_key_pem = "-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----"
        actor.secv1.save()

        # Add owner through ReferenceField
        secv1_context = SecV1Context.objects.get(reference=actor.reference)
        secv1_context.owner.add(owner_ref)

        # Verify both work
        self.assertEqual(
            actor.secv1.public_key_pem,
            "-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----",
        )
        self.assertEqual(secv1_context.owner.count(), 1)
        self.assertIn(owner_ref, secv1_context.owner.all())
