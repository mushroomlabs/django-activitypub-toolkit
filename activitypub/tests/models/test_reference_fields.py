from django.db.models import Q

from activitypub import factories
from activitypub.models import ActivityContext, ObjectContext, SecV1Context
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
