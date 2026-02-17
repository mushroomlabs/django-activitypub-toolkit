from django.db.models import F
from django.test import TestCase

from activitypub.adapters.lemmy.factories import CommunityFactory
from activitypub.adapters.lemmy.models import Community, Person
from activitypub.adapters.lemmy.models.core import LemmyContextModel, LemmyObject
from activitypub.core.factories import ActorFactory, DomainFactory, ReferenceFactory
from activitypub.core.models import ActorContext, ObjectContext
from activitypub.core.models.managers import (
    ContextAwareInheritanceManager,
    ContextAwareInheritanceQuerySet,
    ContextAwareManager,
    ContextAwareQuerySet,
)

# BaseAs2ObjectContext is the concrete class that owns the `reference` OneToOne on its table;
# ObjectContext and ActorContext are MTI children that extend it.
_BASE_AS2_RELATED_NAME = "activitypub_baseas2objectcontext_context"
_LEMMY_CTX_RELATED_NAME = "activitypub_lemmy_adapter_lemmycontextmodel_context"


def _select_related_has_path(select_related, path):
    """Walk the nested select_related dict to check if a dotted path is present."""
    parts = path.split("__")
    current = select_related
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


class RelatedContextFieldRegistrationTest(TestCase):
    """_related_context_fields is populated at class definition time."""

    def test_lemmy_object_registers_as2_and_lemmy(self):
        rcf = LemmyObject._related_context_fields
        self.assertIn("as2", rcf)
        self.assertIn("lemmy", rcf)
        self.assertIs(rcf["as2"].context_class, ObjectContext)
        self.assertIs(rcf["lemmy"].context_class, LemmyContextModel)

    def test_subclass_override_replaces_parent_field(self):
        rcf = Community._related_context_fields
        self.assertIs(rcf["as2"].context_class, ActorContext)
        self.assertIn("lemmy", rcf)

    def test_subclass_dict_independent_from_parent(self):
        self.assertIsNot(
            Community.__dict__["_related_context_fields"],
            LemmyObject.__dict__["_related_context_fields"],
        )

    def test_person_as2_uses_actor_context(self):
        rcf = Person._related_context_fields
        self.assertIs(rcf["as2"].context_class, ActorContext)


class ContextAwareManagerTest(TestCase):
    """LemmyObject.objects is a ContextAwareInheritanceManager returning ContextAwareInheritanceQuerySet."""

    def test_manager_type(self):
        self.assertIsInstance(LemmyObject.objects, ContextAwareInheritanceManager)

    def test_manager_is_also_context_aware(self):
        # ContextAwareInheritanceManager IS-A ContextAwareManager
        self.assertIsInstance(LemmyObject.objects, ContextAwareManager)

    def test_queryset_type(self):
        self.assertIsInstance(LemmyObject.objects.all(), ContextAwareInheritanceQuerySet)

    def test_queryset_is_also_context_aware(self):
        # ContextAwareInheritanceQuerySet IS-A ContextAwareQuerySet
        self.assertIsInstance(LemmyObject.objects.all(), ContextAwareQuerySet)

    def test_select_subclasses_still_works(self):
        qs = LemmyObject.objects.select_subclasses(Community)
        self.assertIsInstance(qs, ContextAwareInheritanceQuerySet)


class RewriteLookupTest(TestCase):
    """_rewrite_lookup translates RelatedContextField prefixes to ORM join paths."""

    def setUp(self):
        self.qs = LemmyObject.objects.all()

    def test_rewrite_as2_field(self):
        rewritten = self.qs._rewrite_lookup("as2__name")
        expected = f"reference__{_BASE_AS2_RELATED_NAME}__objectcontext__name"
        self.assertEqual(rewritten, expected)

    def test_rewrite_lemmy_field(self):
        rewritten = self.qs._rewrite_lookup("lemmy__locked")
        expected = f"reference__{_LEMMY_CTX_RELATED_NAME}__locked"
        self.assertEqual(rewritten, expected)

    def test_non_context_field_passthrough(self):
        rewritten = self.qs._rewrite_lookup("reference__uri")
        self.assertEqual(rewritten, "reference__uri")

    def test_plain_non_context_field_passthrough(self):
        rewritten = self.qs._rewrite_lookup("object_id")
        self.assertEqual(rewritten, "object_id")

    def test_rewrite_community_as2_uses_actor_context(self):
        qs = Community.objects.all()
        rewritten = qs._rewrite_lookup("as2__preferred_username")
        expected = f"reference__{_BASE_AS2_RELATED_NAME}__actorcontext__preferred_username"
        self.assertEqual(rewritten, expected)


class FilterRewriteIntegrationTest(TestCase):
    """filter() and exclude() with context prefixes hit the database correctly."""

    def setUp(self):
        domain = DomainFactory(local=True)
        ref = ReferenceFactory(domain=domain)
        ActorFactory(
            reference=ref,
            type=ActorContext.Types.GROUP,
            preferred_username="testcommunity",
        )
        self.community = CommunityFactory(reference=ref)

    def test_filter_on_as2_preferred_username(self):
        result = Community.objects.filter(as2__preferred_username="testcommunity")
        self.assertIn(self.community, result)

    def test_filter_excludes_non_matching(self):
        result = Community.objects.filter(as2__preferred_username="other")
        self.assertNotIn(self.community, result)

    def test_exclude_on_as2(self):
        result = Community.objects.exclude(as2__preferred_username="other")
        self.assertIn(self.community, result)


class OrderByRewriteTest(TestCase):
    """order_by() rewrites context prefixes including the descending - prefix."""

    def _get_order_by_strings(self, qs):
        return [str(o) for o in qs.query.order_by]

    def test_ascending_order_by_context_field(self):
        qs = Community.objects.order_by("as2__preferred_username")
        order = self._get_order_by_strings(qs)
        self.assertTrue(
            any("actorcontext" in o and not o.startswith("-") for o in order),
            f"Expected actorcontext ascending in {order}",
        )

    def test_descending_order_by_context_field(self):
        qs = Community.objects.order_by("-as2__preferred_username")
        order = self._get_order_by_strings(qs)
        self.assertTrue(
            any("actorcontext" in o and o.startswith("-") for o in order),
            f"Expected actorcontext descending in {order}",
        )

    def test_mixed_order_by(self):
        qs = Community.objects.order_by("object_id", "-as2__preferred_username")
        order = self._get_order_by_strings(qs)
        self.assertIn("object_id", order)
        self.assertTrue(any(o.startswith("-") and "actorcontext" in o for o in order))

    def test_order_by_lemmy_field(self):
        qs = LemmyObject.objects.order_by("lemmy__locked")
        order = self._get_order_by_strings(qs)
        self.assertTrue(
            any(_LEMMY_CTX_RELATED_NAME in o for o in order),
            f"Expected lemmy context related name in {order}",
        )


class WithContextsTest(TestCase):
    """with_contexts() issues select_related for the named fields."""

    def test_with_contexts_adds_select_related(self):
        qs = Community.objects.with_contexts("as2", "lemmy")
        sr = qs.query.select_related
        self.assertTrue(
            _select_related_has_path(sr, f"reference__{_BASE_AS2_RELATED_NAME}__actorcontext"),
            f"ActorContext path missing from select_related: {sr}",
        )
        self.assertTrue(
            _select_related_has_path(sr, f"reference__{_LEMMY_CTX_RELATED_NAME}"),
            f"LemmyContextModel path missing from select_related: {sr}",
        )

    def test_with_contexts_invalid_name_raises(self):
        with self.assertRaises(ValueError):
            Community.objects.with_contexts("nonexistent")

    def test_with_contexts_returns_queryset(self):
        qs = Community.objects.with_contexts("as2")
        self.assertIsInstance(qs, ContextAwareQuerySet)

    def test_with_contexts_accessible_from_manager(self):
        qs = Community.objects.with_contexts("lemmy")
        self.assertIsInstance(qs, ContextAwareQuerySet)


class ValuesRewriteTest(TestCase):
    """values() and values_list() rewrite context prefixes."""

    def setUp(self):
        domain = DomainFactory(local=True)
        ref = ReferenceFactory(domain=domain)
        ActorFactory(
            reference=ref,
            type=ActorContext.Types.GROUP,
            preferred_username="valtest",
        )
        LemmyContextModel.objects.create(
            reference=ref,
            posting_restricted_to_mods=True,
        )
        self.community = CommunityFactory(reference=ref)

    def test_values_with_context_fields(self):
        qs = Community.objects.filter(pk=self.community.pk).values(
            "as2__preferred_username", "lemmy__posting_restricted_to_mods"
        )
        row = qs.first()
        self.assertIsNotNone(row)
        # Django flattens the rewritten key into a dict key using the full join path
        self.assertIn("valtest", row.values())
        self.assertIn(True, row.values())

    def test_values_list_with_context_fields(self):
        qs = Community.objects.filter(pk=self.community.pk).values_list(
            "as2__preferred_username", flat=False
        )
        row = qs.first()
        self.assertIsNotNone(row)
        self.assertIn("valtest", row)

    def test_values_list_flat(self):
        qs = Community.objects.filter(pk=self.community.pk).values_list(
            "as2__preferred_username", flat=True
        )
        self.assertIn("valtest", list(qs))

    def test_values_with_f_expression(self):
        qs = Community.objects.filter(pk=self.community.pk).values(
            name=F("as2__preferred_username"),
            restricted=F("lemmy__posting_restricted_to_mods"),
        )
        row = qs.first()
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "valtest")
        self.assertEqual(row["restricted"], True)

    def test_annotate_with_f_expression(self):
        qs = Community.objects.filter(pk=self.community.pk).annotate(
            community_name=F("as2__preferred_username"),
        )
        obj = qs.first()
        self.assertEqual(obj.community_name, "valtest")
