from activitypub.core.factories import DomainFactory, IdentityFactory, InstanceFactory
from activitypub.core.models import ObjectContext
from django.test import RequestFactory, TransactionTestCase, override_settings

from activitypub.adapters.lemmy import models
from activitypub.adapters.lemmy.choices import ListingTypes, SortOrderTypes
from activitypub.adapters.lemmy.factories import (
    CommentFactory,
    CommunityFactory,
    PersonFactory,
    PostFactory,
    SiteFactory,
)
from activitypub.adapters.lemmy.filters import CommentFilter, PostFilter


@override_settings(
    FEDERATION={"DEFAULT_URL": "http://testserver", "FORCE_INSECURE_HTTP": True},
    ALLOWED_HOSTS=["testserver"],
)
class PostFilterTestCase(TransactionTestCase):
    """Test cases for PostFilter"""

    def setUp(self):
        self.factory = RequestFactory()
        self.domain = DomainFactory(scheme="http", name="testserver", local=True)
        self.instance = InstanceFactory(domain=self.domain)
        self.site = SiteFactory(reference__domain=self.domain)
        self.community = CommunityFactory(reference__domain=self.domain)
        self.identity = IdentityFactory(actor__reference__domain=self.domain)
        self.person = PersonFactory(reference=self.identity.actor.reference)

    def test_filter_by_community_id(self):
        """Test filtering posts by community_id"""
        community2 = CommunityFactory(reference__domain=self.domain)
        post1 = PostFactory(community=self.community, reference__domain=self.domain)
        post2 = PostFactory(community=self.community, reference__domain=self.domain)
        post3 = PostFactory(community=community2, reference__domain=self.domain)

        request = self.factory.get("/", {"community_id": self.community.object_id})
        filterset = PostFilter(request.GET, queryset=models.Post.objects.all(), request=request)

        self.assertTrue(filterset.is_valid())
        filtered_qs = filterset.qs
        self.assertEqual(filtered_qs.count(), 2)
        self.assertIn(post1, filtered_qs)
        self.assertIn(post2, filtered_qs)
        self.assertNotIn(post3, filtered_qs)

    def test_filter_by_listing_type_local(self):
        """Test filtering for local posts only"""
        remote_domain = DomainFactory(scheme="https", name="remote.com", local=False)
        local_post1 = PostFactory(community=self.community, reference__domain=self.domain)
        local_post2 = PostFactory(community=self.community, reference__domain=self.domain)
        remote_post = PostFactory(community=self.community, reference__domain=remote_domain)

        request = self.factory.get("/", {"type_": ListingTypes.LOCAL})
        filterset = PostFilter(request.GET, queryset=models.Post.objects.all(), request=request)

        self.assertTrue(filterset.is_valid())
        filtered_qs = filterset.qs
        self.assertEqual(filtered_qs.count(), 2)
        self.assertIn(local_post1, filtered_qs)
        self.assertIn(local_post2, filtered_qs)
        self.assertNotIn(remote_post, filtered_qs)

    def test_filter_by_listing_type_subscribed(self):
        """Test filtering for subscribed community posts"""
        # Create posts in different communities
        subscribed_community = CommunityFactory(reference__domain=self.domain)
        other_community = CommunityFactory(reference__domain=self.domain)

        PostFactory(community=subscribed_community, reference__domain=self.domain)
        PostFactory(community=other_community, reference__domain=self.domain)

        # TODO: Set up proper follower relationship using CollectionContext
        # For now, test the filter logic works when no subscriptions

        request = self.factory.get("/", {"type_": ListingTypes.SUBSCRIBED})
        request.user = self.identity.user
        filterset = PostFilter(request.GET, queryset=models.Post.objects.all(), request=request)

        self.assertTrue(filterset.is_valid())
        filtered_qs = filterset.qs
        # Should return empty if not subscribed to any communities
        self.assertEqual(filtered_qs.count(), 0)

    def test_filter_saved_only(self):
        post1 = PostFactory(community=self.community, reference__domain=self.domain)
        post2 = PostFactory(community=self.community, reference__domain=self.domain)
        post3 = PostFactory(community=self.community, reference__domain=self.domain)

        # Save posts 1 and 2
        self.identity.user.lemmy_profile.saved_posts.add(post1, post2)

        request = self.factory.get("/", {"saved_only": True})
        request.user = self.identity.user
        filterset = PostFilter(request.GET, queryset=models.Post.objects.all(), request=request)

        self.assertTrue(filterset.is_valid())
        filtered_qs = filterset.qs
        self.assertEqual(filtered_qs.count(), 2)
        self.assertIn(post1, filtered_qs)
        self.assertIn(post2, filtered_qs)
        self.assertNotIn(post3, filtered_qs)

    def test_filter_liked_only(self):
        IdentityFactory(actor__reference__domain=self.domain)

        post1 = PostFactory(community=self.community, reference__domain=self.domain)
        post2 = PostFactory(community=self.community, reference__domain=self.domain)
        post3 = PostFactory(community=self.community, reference__domain=self.domain)

        # Like posts 1 and 3
        self.person.liked_posts.add(post1, post3)

        request = self.factory.get("/", {"liked_only": True})
        request.user = self.identity.user

        filterset = PostFilter(request.GET, queryset=models.Post.objects.all(), request=request)

        self.assertTrue(filterset.is_valid())
        filtered_qs = filterset.qs
        self.assertEqual(filtered_qs.count(), 2)
        self.assertIn(post1, filtered_qs)
        self.assertNotIn(post2, filtered_qs)
        self.assertIn(post3, filtered_qs)

    def test_filter_show_hidden(self):
        """Test filtering hidden posts"""
        post1 = PostFactory(community=self.community, reference__domain=self.domain)
        post2 = PostFactory(community=self.community, reference__domain=self.domain)
        post3 = PostFactory(community=self.community, reference__domain=self.domain)

        # Hide post2
        self.identity.user.lemmy_profile.hidden_posts.add(post2)

        # Test with show_hidden=False (default behavior - exclude hidden)
        request = self.factory.get("/", {"show_hidden": False})
        request.user = self.identity.user

        filterset = PostFilter(request.GET, queryset=models.Post.objects.all(), request=request)

        self.assertTrue(filterset.is_valid())
        filtered_qs = filterset.qs
        self.assertEqual(filtered_qs.count(), 2)
        self.assertIn(post1, filtered_qs)
        self.assertNotIn(post2, filtered_qs)
        self.assertIn(post3, filtered_qs)

        request = self.factory.get("/", {"show_hidden": True})
        request.user = self.identity.user

        filterset = PostFilter(request.GET, queryset=models.Post.objects.all(), request=request)

        self.assertTrue(filterset.is_valid())
        filtered_qs = filterset.qs
        self.assertEqual(filtered_qs.count(), 3)

    def test_filter_show_read(self):
        post1 = PostFactory(community=self.community, reference__domain=self.domain)
        post2 = PostFactory(community=self.community, reference__domain=self.domain)
        post3 = PostFactory(community=self.community, reference__domain=self.domain)

        # Mark post1 as read
        self.identity.user.lemmy_profile.read_posts.add(post1)

        # Test with show_read=False (exclude read posts)
        request = self.factory.get("/", {"show_read": False})
        request.user = self.identity.user

        filterset = PostFilter(request.GET, queryset=models.Post.objects.all(), request=request)

        self.assertTrue(filterset.is_valid())
        filtered_qs = filterset.qs
        self.assertEqual(filtered_qs.count(), 2)
        self.assertNotIn(post1, filtered_qs)
        self.assertIn(post2, filtered_qs)
        self.assertIn(post3, filtered_qs)

    def test_filter_show_nsfw(self):
        """Test filtering NSFW posts"""
        post1 = PostFactory(community=self.community, reference__domain=self.domain)
        post2 = PostFactory(community=self.community, reference__domain=self.domain)
        post3 = PostFactory(community=self.community, reference__domain=self.domain)

        # Mark post2 as NSFW via ObjectContext
        obj_context, _ = ObjectContext.objects.get_or_create(
            reference=post2.reference,
            defaults={"type": ObjectContext.Types.PAGE, "name": "Test Post"},
        )
        obj_context.sensitive = True
        obj_context.save()

        # Test with show_nsfw=False (exclude NSFW)
        request = self.factory.get("/", {"show_nsfw": False})
        filterset = PostFilter(request.GET, queryset=models.Post.objects.all(), request=request)

        self.assertTrue(filterset.is_valid())
        filtered_qs = filterset.qs
        self.assertEqual(filtered_qs.count(), 2)
        self.assertIn(post1, filtered_qs)
        self.assertNotIn(post2, filtered_qs)
        self.assertIn(post3, filtered_qs)

        # Test with show_nsfw=True (include NSFW)
        request = self.factory.get("/", {"show_nsfw": True})
        filterset = PostFilter(request.GET, queryset=models.Post.objects.all(), request=request)

        self.assertTrue(filterset.is_valid())
        filtered_qs = filterset.qs
        self.assertEqual(filtered_qs.count(), 3)

    def test_sort_by_new(self):
        """Test sorting posts by new"""
        PostFactory(community=self.community, reference__domain=self.domain)
        PostFactory(community=self.community, reference__domain=self.domain)
        PostFactory(community=self.community, reference__domain=self.domain)

        request = self.factory.get("/", {"sort": SortOrderTypes.NEW})
        filterset = PostFilter(request.GET, queryset=models.Post.objects.all(), request=request)

        self.assertTrue(filterset.is_valid())
        filtered_qs = filterset.qs
        # Should be ordered by published date descending
        self.assertEqual(filtered_qs.count(), 3)

    def test_sort_by_hot(self):
        """Test sorting posts by hot"""
        PostFactory(community=self.community, reference__domain=self.domain)
        PostFactory(community=self.community, reference__domain=self.domain)

        request = self.factory.get("/", {"sort": SortOrderTypes.HOT})
        filterset = PostFilter(request.GET, queryset=models.Post.objects.all(), request=request)

        self.assertTrue(filterset.is_valid())
        filtered_qs = filterset.qs
        # Should be ordered by hot_rank
        self.assertEqual(filtered_qs.count(), 2)

    def test_sort_by_top_day(self):
        """Test sorting posts by top day"""
        PostFactory(community=self.community, reference__domain=self.domain)
        PostFactory(community=self.community, reference__domain=self.domain)

        request = self.factory.get("/", {"sort": SortOrderTypes.TOP_DAY})
        filterset = PostFilter(request.GET, queryset=models.Post.objects.all(), request=request)

        self.assertTrue(filterset.is_valid())
        filtered_qs = filterset.qs
        # Should be ordered by score within last day
        self.assertEqual(filtered_qs.count(), 2)

    def test_multiple_filters_combined(self):
        """Test combining multiple filters"""

        community2 = CommunityFactory(reference__domain=self.domain)

        post1 = PostFactory(community=self.community, reference__domain=self.domain)
        post2 = PostFactory(community=self.community, reference__domain=self.domain)
        post3 = PostFactory(community=community2, reference__domain=self.domain)

        # Save only post1
        self.identity.user.lemmy_profile.saved_posts.add(post1)

        # Filter by community AND saved_only
        request = self.factory.get(
            "/", {"community_id": self.community.object_id, "saved_only": True}
        )
        request.user = self.identity.user

        filterset = PostFilter(request.GET, queryset=models.Post.objects.all(), request=request)

        self.assertTrue(filterset.is_valid())
        filtered_qs = filterset.qs
        self.assertEqual(filtered_qs.count(), 1)
        self.assertIn(post1, filtered_qs)
        self.assertNotIn(post2, filtered_qs)
        self.assertNotIn(post3, filtered_qs)

    def test_no_filters_applied(self):
        """Test that no filters returns all posts"""
        PostFactory(community=self.community, reference__domain=self.domain)
        PostFactory(community=self.community, reference__domain=self.domain)
        PostFactory(community=self.community, reference__domain=self.domain)

        request = self.factory.get("/", {})
        filterset = PostFilter(request.GET, queryset=models.Post.objects.all(), request=request)

        self.assertTrue(filterset.is_valid())
        filtered_qs = filterset.qs
        self.assertEqual(filtered_qs.count(), 3)


@override_settings(
    FEDERATION={"DEFAULT_URL": "http://testserver", "FORCE_INSECURE_HTTP": True},
    ALLOWED_HOSTS=["testserver"],
)
class CommentFilterTestCase(TransactionTestCase):
    """Test cases for CommentFilter"""

    def setUp(self):
        self.factory = RequestFactory()
        self.domain = DomainFactory(scheme="http", name="testserver", local=True)
        self.instance = InstanceFactory(domain=self.domain)
        self.site = SiteFactory(reference__domain=self.domain)
        self.community = CommunityFactory(reference__domain=self.domain)
        self.post = PostFactory(community=self.community, reference__domain=self.domain)
        self.identity = IdentityFactory(actor__reference__domain=self.domain)
        self.person = PersonFactory(reference=self.identity.actor.reference)

    def test_filter_by_post_id(self):
        post2 = PostFactory(community=self.community, reference__domain=self.domain)

        comment1 = CommentFactory(post=self.post, reference__domain=self.domain)
        comment2 = CommentFactory(post=self.post, reference__domain=self.domain)
        comment3 = CommentFactory(post=post2, reference__domain=self.domain)

        request = self.factory.get("/", {"post_id": self.post.object_id})
        filterset = CommentFilter(
            request.GET, queryset=models.Comment.objects.all(), request=request
        )

        self.assertTrue(filterset.is_valid())
        filtered_qs = filterset.qs
        self.assertEqual(filtered_qs.count(), 2)
        self.assertIn(comment1, filtered_qs)
        self.assertIn(comment2, filtered_qs)
        self.assertNotIn(comment3, filtered_qs)

    def test_filter_by_community_id(self):
        """Test filtering comments by community_id"""
        community2 = CommunityFactory(reference__domain=self.domain)
        post2 = PostFactory(community=community2, reference__domain=self.domain)

        comment1 = CommentFactory(post=self.post, reference__domain=self.domain)
        comment2 = CommentFactory(post=self.post, reference__domain=self.domain)
        comment3 = CommentFactory(post=post2, reference__domain=self.domain)

        request = self.factory.get("/", {"community_id": self.community.object_id})
        filterset = CommentFilter(
            request.GET, queryset=models.Comment.objects.all(), request=request
        )

        self.assertTrue(filterset.is_valid())
        filtered_qs = filterset.qs
        self.assertEqual(filtered_qs.count(), 2)
        self.assertIn(comment1, filtered_qs)
        self.assertIn(comment2, filtered_qs)
        self.assertNotIn(comment3, filtered_qs)

    def test_filter_saved_only(self):
        """Test filtering for saved comments only"""
        comment1 = CommentFactory(post=self.post, reference__domain=self.domain)
        comment2 = CommentFactory(post=self.post, reference__domain=self.domain)
        comment3 = CommentFactory(post=self.post, reference__domain=self.domain)

        # Save comment1
        self.identity.user.lemmy_profile.saved_comments.add(comment1)

        request = self.factory.get("/", {"saved_only": True})
        request.user = self.identity.user

        filterset = CommentFilter(
            request.GET, queryset=models.Comment.objects.all(), request=request
        )

        self.assertTrue(filterset.is_valid())
        filtered_qs = filterset.qs
        self.assertEqual(filtered_qs.count(), 1)
        self.assertIn(comment1, filtered_qs)
        self.assertNotIn(comment2, filtered_qs)
        self.assertNotIn(comment3, filtered_qs)

    def test_filter_liked_only(self):
        """Test filtering for liked comments only"""

        comment1 = CommentFactory(post=self.post, reference__domain=self.domain)
        comment2 = CommentFactory(post=self.post, reference__domain=self.domain)

        # Like comment2
        self.person.liked_comments.add(comment2)

        request = self.factory.get("/", {"liked_only": True})
        request.user = self.identity.user

        filterset = CommentFilter(
            request.GET, queryset=models.Comment.objects.all(), request=request
        )

        self.assertTrue(filterset.is_valid())
        filtered_qs = filterset.qs
        self.assertEqual(filtered_qs.count(), 1)
        self.assertNotIn(comment1, filtered_qs)
        self.assertIn(comment2, filtered_qs)

    def test_filter_by_listing_type_local(self):
        """Test filtering for local comments only"""
        remote_domain = DomainFactory(scheme="https", name="remote.com", local=False)

        local_comment = CommentFactory(post=self.post, reference__domain=self.domain)
        remote_comment = CommentFactory(post=self.post, reference__domain=remote_domain)

        request = self.factory.get("/", {"type_": ListingTypes.LOCAL})
        filterset = CommentFilter(
            request.GET, queryset=models.Comment.objects.all(), request=request
        )

        self.assertTrue(filterset.is_valid())
        filtered_qs = filterset.qs
        self.assertEqual(filtered_qs.count(), 1)
        self.assertIn(local_comment, filtered_qs)
        self.assertNotIn(remote_comment, filtered_qs)

    def test_sort_by_new(self):
        """Test sorting comments by new"""
        CommentFactory(post=self.post, reference__domain=self.domain)
        CommentFactory(post=self.post, reference__domain=self.domain)

        request = self.factory.get("/", {"sort": SortOrderTypes.NEW})
        filterset = CommentFilter(
            request.GET, queryset=models.Comment.objects.all(), request=request
        )

        self.assertTrue(filterset.is_valid())
        filtered_qs = filterset.qs
        self.assertEqual(filtered_qs.count(), 2)

    def test_sort_by_hot(self):
        """Test sorting comments by hot"""
        CommentFactory(post=self.post, reference__domain=self.domain)
        CommentFactory(post=self.post, reference__domain=self.domain)

        request = self.factory.get("/", {"sort": SortOrderTypes.HOT})
        filterset = CommentFilter(
            request.GET, queryset=models.Comment.objects.all(), request=request
        )

        self.assertTrue(filterset.is_valid())
        filtered_qs = filterset.qs
        self.assertEqual(filtered_qs.count(), 2)
