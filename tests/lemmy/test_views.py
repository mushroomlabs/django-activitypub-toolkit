import uuid

from activitypub.core.factories import (
    ActivityFactory,
    ActorFactory,
    DomainFactory,
    FollowRequestFactory,
    IdentityFactory,
    InstanceFactory,
    ObjectFactory,
    ReferenceFactory,
)
from activitypub.core.models import (
    ActivityContext,
    ActorContext,
    CollectionContext,
    FollowRequest,
    Identity,
    ObjectContext,
    Reference,
)
from activitypub.core.models.base import generate_ulid
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.test import APIClient

from activitypub.adapters.lemmy import models
from activitypub.adapters.lemmy.factories import (
    CommentFactory,
    CommunityFactory,
    PersonFactory,
    PostFactory,
    SiteFactory,
)

User = get_user_model()

CONTENT_TYPE = "application/ld+json"


@override_settings(
    FEDERATION={"DEFAULT_URL": "http://testserver", "FORCE_INSECURE_HTTP": True},
    ALLOWED_HOSTS=["testserver"],
)
class BaseViewTestCase(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        self.domain = DomainFactory(scheme="http", name="testserver", local=True)
        self.instance = InstanceFactory(domain=self.domain)
        self.site = SiteFactory(reference__domain=self.domain)

        # As a side-effect of most interactions, there are tasks that
        # create references to uris from w3.org, which then triggers a
        # nodeinfo query for the domain. By adding the domain entry
        # via a factory, the query is avoided and no network calls are
        # needed

        # FIXME: use proper pytest fixtures
        DomainFactory(scheme="https", name="www.w3.org")


class BaseAuthenticatedViewTestCase(BaseViewTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.defaults["HTTP_HOST"] = "testserver"
        self.identity = IdentityFactory(actor__reference__domain=self.domain)
        self.person = PersonFactory(reference=self.identity.actor.reference)

        # create a Login Token so that the user is authenticated
        login_token = models.LoginToken.make(identity=self.identity)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login_token.token}")


class ResolveObjectTestCase(BaseViewTestCase):
    def setUp(self):
        self.client = APIClient()
        self.domain = DomainFactory(scheme="http", name="testserver", local=True)
        self.instance = InstanceFactory(domain=self.domain)
        self.site = SiteFactory(reference__domain=self.domain)

    def test_can_resolve_person_via_subject_name(self):
        actor = ActorFactory(preferred_username="bob", reference__domain=self.domain)
        person = PersonFactory(reference=actor.reference)
        response = self.client.get("/api/v3/resolve_object", data={"q": "@bob@testserver"})
        self.assertEqual(response.status_code, 200, "Failed to resolve object")
        expected = {
            "person": {
                "person": {
                    "id": person.object_id,
                    "name": "bob",
                    "banned": False,
                    "actor_id": "http://testserver/users/bob",
                    "local": True,
                    "deleted": False,
                    "bot_account": False,
                    "instance_id": self.site.object_id,
                },
                "counts": {"person_id": person.object_id, "post_count": 0, "comment_count": 0},
                "is_admin": False,
            }
        }
        self.assertEqual(response.json(), expected)

    def test_can_resolve_person_via_uri(self):
        """Test resolving a person by their ActivityPub URI"""
        actor = ActorFactory(preferred_username="alice", reference__domain=self.domain)
        PersonFactory(reference=actor.reference)

        response = self.client.get(
            "/api/v3/resolve_object", data={"q": "http://testserver/users/alice"}
        )

        self.assertEqual(response.status_code, 200, "Failed to resolve person by URI")
        self.assertIn("person", response.json())
        self.assertEqual(response.json()["person"]["person"]["name"], "alice")

    def test_resolve_remote_person_via_subject_name(self):
        """Test resolving a remote person via @username@domain"""
        remote_actor_ref = ReferenceFactory(
            path="/u/remote_user",
            domain__name="remote.example.com",
            domain__local=False,
            resolved=True,
        )

        actor = ActorFactory(preferred_username="remote_user", reference=remote_actor_ref)

        PersonFactory(reference=actor.reference)
        response = self.client.get(
            "/api/v3/resolve_object", data={"q": "@remote_user@remote.example.com"}
        )
        self.assertEqual(response.status_code, 200, "Failed to resolve remote person")
        self.assertIn("person", response.json())
        self.assertEqual(response.json()["person"]["person"]["local"], False)

    def test_resolve_nonexistent_person_returns_error(self):
        """Test that resolving a non-existent person returns an error"""
        response = self.client.get("/api/v3/resolve_object", data={"q": "@nonexistent@testserver"})
        self.assertEqual(response.status_code, 400, "Should return error for non-existent person")
        self.assertIn("non_field_errors", response.json())

    def test_resolve_person_invalid_format_returns_error(self):
        """Test that invalid person format returns validation error"""
        response = self.client.get("/api/v3/resolve_object", data={"q": "@invalid"})
        self.assertEqual(response.status_code, 400, "Should return error for invalid format")

    def test_can_resolve_community_via_subject_name(self):
        """Test resolving a community by !community@domain"""
        # Create a community with proper ActivityPub structure
        community_ref = Reference.objects.create(
            uri="http://testserver/c/technology", domain=self.domain
        )

        now = timezone.now()
        ActorContext.make(
            reference=community_ref,
            type=ActorContext.Types.GROUP,
            preferred_username="technology",
            name="Technology Community",
            published=now,
            updated=now,
        )
        models.Community.objects.create(reference=community_ref)

        response = self.client.get("/api/v3/resolve_object", data={"q": "!technology@testserver"})
        self.assertEqual(response.status_code, 200, "Failed to resolve community")
        self.assertIn("community", response.json())
        self.assertEqual(response.json()["community"]["community"]["name"], "technology")

    def test_can_resolve_community_via_uri(self):
        """Test resolving a community by direct URI"""
        community_ref = Reference.objects.create(
            uri="http://testserver/c/gaming", domain=self.domain
        )

        now = timezone.now()
        ActorContext.make(
            reference=community_ref,
            type=ActorContext.Types.GROUP,
            preferred_username="gaming",
            published=now,
            updated=now,
        )

        models.Community.objects.create(reference=community_ref)

        response = self.client.get(
            "/api/v3/resolve_object", data={"q": "http://testserver/c/gaming"}
        )
        self.assertEqual(response.status_code, 200, "Failed to resolve community by URI")
        self.assertIn("community", response.json())

    def test_resolve_remote_community(self):
        """Test resolving a remote community"""
        remote_domain = DomainFactory(scheme="https", name="lemmy.example.com", local=False)
        community_ref = ReferenceFactory(
            path="/c/news",
            domain=remote_domain,
            resolved=True,
        )

        now = timezone.now()
        ActorContext.make(
            reference=community_ref,
            type=ActorContext.Types.GROUP,
            preferred_username="news",
            published=now,
            updated=now,
        )

        models.Community.objects.create(reference=community_ref)

        response = self.client.get(
            "/api/v3/resolve_object", data={"q": "https://lemmy.example.com/c/news"}
        )
        self.assertEqual(response.status_code, 200, "Failed to resolve remote community")
        self.assertIn("community", response.json())

    def test_resolve_nonexistent_community_returns_error(self):
        """Test that resolving a non-existent community returns an error"""
        response = self.client.get("/api/v3/resolve_object", data={"q": "!nonexistent@testserver"})
        self.assertEqual(
            response.status_code, 400, "Should return error for non-existent community"
        )

    def test_can_resolve_post_via_uri(self):
        """Test resolving a post by direct URI"""
        PostFactory(reference__path="/post/1", reference__domain=self.domain)
        response = self.client.get(
            "/api/v3/resolve_object", data={"q": "http://testserver/post/1"}
        )
        self.assertEqual(response.status_code, 200, "Failed to resolve post")
        self.assertIn("post", response.json())

    def test_resolve_remote_post(self):
        """Test resolving a remote post"""
        remote_domain = DomainFactory(scheme="https", name="remote.lemmy.com", local=False)

        PostFactory(reference__path="/post/123", reference__domain=remote_domain)

        response = self.client.get(
            "/api/v3/resolve_object", data={"q": "https://remote.lemmy.com/post/123"}
        )
        self.assertEqual(response.status_code, 200, "Failed to resolve remote post")
        self.assertIn("post", response.json())

    def test_resolve_deleted_post(self):
        """Test that a deleted post can still be resolved"""
        PostFactory(reference__path="/post/deleted", reference__domain=self.domain, deleted=True)
        response = self.client.get(
            "/api/v3/resolve_object", data={"q": "http://testserver/post/deleted"}
        )
        self.assertEqual(response.status_code, 200, "Should resolve deleted post")
        self.assertIn("post", response.json())
        self.assertEqual(response.json()["post"]["post"]["deleted"], True)

    def test_resolve_nonexistent_post_returns_error(self):
        """Test that resolving a non-existent post returns an error"""
        response = self.client.get(
            "/api/v3/resolve_object", data={"q": "http://testserver/post/999999"}
        )
        self.assertEqual(response.status_code, 400, "Should return error for non-existent post")

    def test_can_resolve_comment_via_uri(self):
        """Test resolving a comment by direct URI"""
        # Create community
        community_ref = Reference.make(uri="http://testserver/c/test")
        now = timezone.now()
        ActorContext.make(
            reference=community_ref,
            type=ActorContext.Types.GROUP,
            preferred_username="test",
            published=now,
            updated=now,
        )
        community = models.Community.objects.create(reference=community_ref)

        # Create post
        post_ref = Reference.objects.create(uri="http://testserver/post/1", domain=self.domain)
        ObjectContext.make(
            reference=post_ref,
            type=ObjectContext.Types.PAGE,
            name="Test Post",
            published=now,
            updated=now,
        )
        post = models.Post.objects.create(reference=post_ref, community=community)

        # Create comment
        comment_ref = Reference.objects.create(
            uri="http://testserver/comment/1", domain=self.domain
        )
        ObjectContext.make(
            reference=comment_ref,
            type=ObjectContext.Types.NOTE,
            content="Test comment content",
            published=now,
            updated=now,
        )
        models.Comment.objects.create(reference=comment_ref, post=post)

        response = self.client.get(
            "/api/v3/resolve_object", data={"q": "http://testserver/comment/1"}
        )
        self.assertEqual(response.status_code, 200, "Failed to resolve comment")
        self.assertIn("comment", response.json())

    def test_resolve_remote_comment(self):
        comment_ref = ReferenceFactory(
            domain__name="remote.example.com",
            domain__local=False,
            path="/comment/456",
            resolved=True,
        )
        ObjectFactory(reference=comment_ref)
        CommentFactory(reference=comment_ref)

        response = self.client.get(
            "/api/v3/resolve_object", data={"q": "https://remote.example.com/comment/456"}
        )
        self.assertEqual(response.status_code, 200, "Failed to resolve remote comment")
        self.assertIn("comment", response.json())

    def test_resolve_deleted_comment(self):
        """Test that a deleted comment can still be resolved"""

        CommentFactory(
            reference__path="/comment/deleted", reference__domain=self.domain, deleted=True
        )

        response = self.client.get(
            "/api/v3/resolve_object", data={"q": "http://testserver/comment/deleted"}
        )
        self.assertEqual(response.status_code, 200, "Should resolve deleted comment")
        self.assertIn("comment", response.json())
        self.assertEqual(response.json()["comment"]["comment"]["deleted"], True)

    def test_resolve_nonexistent_comment_returns_error(self):
        """Test that resolving a non-existent comment returns an error"""
        response = self.client.get(
            "/api/v3/resolve_object", data={"q": "http://testserver/comment/999999"}
        )
        self.assertEqual(response.status_code, 400, "Should return error for non-existent comment")

    def test_resolve_empty_query_returns_error(self):
        """Test that empty query string returns validation error"""
        response = self.client.get("/api/v3/resolve_object", data={"q": ""})
        self.assertEqual(response.status_code, 400, "Should return error for empty query")
        self.assertIn("q", response.json())

    def test_resolve_missing_query_returns_error(self):
        """Test that missing query parameter returns validation error"""
        response = self.client.get("/api/v3/resolve_object")
        self.assertEqual(response.status_code, 400, "Should return error for missing query")

    def test_resolve_malformed_subject_name_missing_at(self):
        """Test malformed subject name without @ prefix"""
        response = self.client.get("/api/v3/resolve_object", data={"q": "username@domain"})
        self.assertEqual(
            response.status_code, 400, "Should return error for malformed subject name"
        )

    def test_resolve_unresolved_remote_reference_returns_error(self):
        """Test that unresolved remote reference returns error"""
        response = self.client.get(
            "/api/v3/resolve_object", data={"q": "@unresolved_user@unresolved.example.com"}
        )
        self.assertEqual(
            response.status_code, 400, "Should return error for unresolved remote reference"
        )

    def test_resolve_uri_not_mapped_to_known_object(self):
        """Test URI that doesn't map to any known object type"""
        # Create a reference without any Lemmy object
        Reference.objects.create(uri="http://testserver/unknown/object", domain=self.domain)

        response = self.client.get(
            "/api/v3/resolve_object", data={"q": "http://testserver/unknown/object"}
        )
        self.assertEqual(response.status_code, 400, "Should return error for unmapped URI")


class CreatePostTestCase(BaseAuthenticatedViewTestCase):
    """Test cases for POST /post endpoint (creating posts)"""

    def setUp(self):
        super().setUp()
        # Create a community for posts

        self.community_ref = Reference.objects.create(
            uri="http://testserver/c/test", domain=self.domain
        )
        now = timezone.now()
        ActorContext.make(
            reference=self.community_ref,
            type=ActorContext.Types.GROUP,
            preferred_username="test",
            name="Test Community",
            published=now,
            updated=now,
        )
        self.community = CommunityFactory(reference=self.community_ref)

    def test_create_post_with_minimal_fields(self):
        payload = {
            "name": "Test Post Title",
            "community_id": self.community.object_id,
        }

        response = self.client.post("/api/v3/post", data=payload, format="json")

        self.assertEqual(response.status_code, 200, f"Failed to create post: {response.data}")
        data = response.json()

        self.assertIn("post_view", data)
        post_view = data["post_view"]

        # Verify post data
        self.assertEqual(post_view["post"]["name"], "Test Post Title")
        self.assertEqual(post_view["post"]["community_id"], self.community.object_id)
        self.assertTrue(post_view["post"]["local"])
        self.assertFalse(post_view["post"]["deleted"])

        # Verify the post was created in the database
        post = models.Post.objects.get(object_id=post_view["post"]["id"])
        self.assertIsNotNone(post)
        self.assertEqual(post.community.reference, self.community_ref)

    def test_create_post_with_body(self):
        """Test creating a post with body content"""
        payload = {
            "name": "Post with Body",
            "community_id": self.community.object_id,
            "body": "This is the post body content with **markdown**.",
        }

        response = self.client.post("/api/v3/post", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        post_view = response.json()["post_view"]
        self.assertEqual(
            post_view["post"]["body"], "This is the post body content with **markdown**."
        )

    def test_create_post_with_url(self):
        """Test creating a post with an external URL"""
        payload = {
            "name": "Link Post",
            "community_id": self.community.object_id,
            "url": "https://example.com/article",
        }

        response = self.client.post("/api/v3/post", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        post_view = response.json()["post_view"]
        self.assertEqual(post_view["post"]["url"], "https://example.com/article")

    def test_create_post_with_nsfw_flag(self):
        """Test creating a post marked as NSFW"""
        payload = {
            "name": "NSFW Post",
            "community_id": self.community.object_id,
            "nsfw": True,
        }

        response = self.client.post("/api/v3/post", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        post_view = response.json()["post_view"]
        self.assertTrue(post_view["post"]["nsfw"])

    def test_create_post_with_language(self):
        """Test creating a post with a specific language"""
        lang = models.Language.create_language(
            code="en", iso_639_1="en", iso_639_3="eng", name="English"
        )

        payload = {
            "name": "Post in English",
            "community_id": self.community.object_id,
            "language_id": lang.internal_id,
        }

        response = self.client.post("/api/v3/post", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        post_view = response.json()["post_view"]
        self.assertEqual(post_view["post"]["language_id"], lang.internal_id)

    def test_create_post_with_alt_text(self):
        """Test creating a post with alt text for accessibility"""
        payload = {
            "name": "Image Post",
            "community_id": self.community.object_id,
            "url": "https://example.com/image.jpg",
            "alt_text": "Description of the image",
        }

        response = self.client.post("/api/v3/post", data=payload, format="json")

        self.assertEqual(response.status_code, 200)

    def test_create_post_missing_name_fails(self):
        """Test that creating a post without name fails"""
        payload = {
            "community_id": self.community.object_id,
        }

        response = self.client.post("/api/v3/post", data=payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.json())

    def test_create_post_missing_community_id_fails(self):
        """Test that creating a post without community_id fails"""
        payload = {
            "name": "Post without community",
        }

        response = self.client.post("/api/v3/post", data=payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("community_id", response.json())

    def test_create_post_with_invalid_community_id_fails(self):
        """Test that creating a post with non-existent community fails"""
        payload = {
            "name": "Post with invalid community",
            "community_id": 999999,
        }

        response = self.client.post("/api/v3/post", data=payload, format="json")

        self.assertEqual(response.status_code, 400)

    def test_create_post_returns_aggregates(self):
        """Test that creating a post returns post aggregates (counts)"""
        payload = {
            "name": "Post with Aggregates",
            "community_id": self.community.object_id,
        }

        response = self.client.post("/api/v3/post", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        post_view = response.json()["post_view"]

        # Verify counts are present and initialized to 0
        self.assertIn("counts", post_view)
        counts = post_view["counts"]
        self.assertEqual(counts["score"], 1)
        self.assertEqual(counts["upvotes"], 1)
        self.assertEqual(counts["downvotes"], 0)
        self.assertEqual(counts["comments"], 0)

    def test_create_post_returns_creator_info(self):
        """Test that creating a post returns creator information"""
        payload = {
            "name": "Post with Creator",
            "community_id": self.community.object_id,
        }

        response = self.client.post("/api/v3/post", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        post_view = response.json()["post_view"]

        # Verify creator is present
        self.assertIn("creator", post_view)
        self.assertIn("community", post_view)


class CreateCommentTestCase(BaseAuthenticatedViewTestCase):
    """Test cases for POST /comment endpoint (creating comments)"""

    def setUp(self):
        super().setUp()

        # Create a community for posts
        self.community_ref = Reference.objects.create(
            uri="http://testserver/c/test", domain=self.domain
        )
        now = timezone.now()
        ActorContext.make(
            reference=self.community_ref,
            type=ActorContext.Types.GROUP,
            preferred_username="test",
            name="Test Community",
            published=now,
            updated=now,
        )
        self.community = CommunityFactory(reference=self.community_ref)
        self.post = PostFactory(reference__path="/post/1", reference__domain=self.domain)

    def test_create_comment_with_minimal_fields(self):
        """Test creating a comment with only required fields (content, post_id)"""
        payload = {
            "content": "This is a test comment",
            "post_id": self.post.object_id,
        }

        response = self.client.post("/api/v3/comment", data=payload, format="json")

        self.assertEqual(response.status_code, 200, f"Failed to create comment: {response.data}")
        data = response.json()

        self.assertIn("comment_view", data)
        comment_view = data["comment_view"]

        # Verify comment data
        self.assertEqual(comment_view["comment"]["content"], "This is a test comment")
        self.assertEqual(comment_view["comment"]["post_id"], self.post.object_id)
        self.assertTrue(comment_view["comment"]["local"])
        self.assertFalse(comment_view["comment"]["deleted"])

        # Verify the comment was created in the database
        comment = models.Comment.objects.get(object_id=comment_view["comment"]["id"])
        self.assertIsNotNone(comment)
        self.assertEqual(comment.post.reference, self.post.reference)

    def test_create_comment_with_parent(self):
        """Test creating a reply to another comment"""
        # Create parent comment first
        parent_comment = CommentFactory(
            reference__path="/comment/parent", reference__domain=self.domain
        )

        # Create reply
        payload = {
            "content": "This is a reply",
            "post_id": self.post.object_id,
            "parent_id": parent_comment.object_id,
        }

        response = self.client.post("/api/v3/comment", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        comment_view = response.json()["comment_view"]
        self.assertEqual(comment_view["comment"]["content"], "This is a reply")

    def test_create_comment_with_markdown(self):
        """Test creating a comment with markdown formatting"""
        payload = {
            "content": "Comment with **bold** and *italic* text",
            "post_id": self.post.object_id,
        }

        response = self.client.post("/api/v3/comment", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        comment_view = response.json()["comment_view"]
        self.assertEqual(
            comment_view["comment"]["content"], "Comment with **bold** and *italic* text"
        )

    def test_create_comment_with_language(self):
        """Test creating a comment with a specific language"""

        lang = models.Language.create_language(
            code="es", iso_639_1="es", iso_639_3="spa", name="Spanish"
        )

        payload = {
            "content": "Comentario en español",
            "post_id": self.post.object_id,
            "language_id": lang.internal_id,
        }

        response = self.client.post("/api/v3/comment", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        comment_view = response.json()["comment_view"]
        self.assertEqual(comment_view["comment"]["language_id"], lang.internal_id)

    def test_create_comment_missing_content_fails(self):
        """Test that creating a comment without content fails"""
        payload = {
            "post_id": self.post.object_id,
        }

        response = self.client.post("/api/v3/comment", data=payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("content", response.json())

    def test_create_comment_missing_post_id_fails(self):
        """Test that creating a comment without post_id fails"""
        payload = {
            "content": "Comment without post",
        }

        response = self.client.post("/api/v3/comment", data=payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("post_id", response.json())

    def test_create_comment_with_invalid_post_id_fails(self):
        """Test that creating a comment with non-existent post fails"""
        payload = {
            "content": "Comment on invalid post",
            "post_id": 999999,
        }

        response = self.client.post("/api/v3/comment", data=payload, format="json")

        self.assertEqual(response.status_code, 400)

    def test_create_comment_with_invalid_parent_id_fails(self):
        """Test that creating a comment with non-existent parent fails"""
        payload = {
            "content": "Reply to non-existent comment",
            "post_id": self.post.object_id,
            "parent_id": 999999,
        }

        response = self.client.post("/api/v3/comment", data=payload, format="json")

        self.assertEqual(response.status_code, 400)

    def test_create_comment_returns_aggregates(self):
        """Test that creating a comment returns comment aggregates"""
        payload = {
            "content": "Comment with aggregates",
            "post_id": self.post.object_id,
        }

        response = self.client.post("/api/v3/comment", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        comment_view = response.json()["comment_view"]

        # Verify counts are present
        self.assertIn("counts", comment_view)
        counts = comment_view["counts"]
        self.assertEqual(counts["score"], 1)
        self.assertEqual(counts["upvotes"], 1)
        self.assertEqual(counts["downvotes"], 0)
        self.assertEqual(counts["child_count"], 0)

    def test_create_comment_returns_recipient_ids(self):
        """Test that creating a comment returns recipient_ids (for mentions)"""
        payload = {
            "content": "Comment mentioning @someone",
            "post_id": self.post.object_id,
        }

        response = self.client.post("/api/v3/comment", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Recipient IDs should be present (empty list if no mentions)
        self.assertIn("recipient_ids", data)
        self.assertIsInstance(data["recipient_ids"], list)

    def test_create_comment_returns_creator_and_post_info(self):
        """Test that creating a comment returns creator and post information"""
        payload = {
            "content": "Comment with full context",
            "post_id": self.post.object_id,
        }

        response = self.client.post("/api/v3/comment", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        comment_view = response.json()["comment_view"]

        # Verify related objects are present
        self.assertIn("creator", comment_view)
        self.assertIn("post", comment_view)
        self.assertIn("community", comment_view)


@override_settings(
    FEDERATION={"DEFAULT_URL": "http://testserver", "FORCE_INSECURE_HTTP": True},
    ALLOWED_HOSTS=["testserver"],
)
class ListPostsTestCase(TransactionTestCase):
    """Test cases for GET /post/list endpoint"""

    def setUp(self):
        self.client = APIClient()
        self.domain = DomainFactory(scheme="http", name="testserver", local=True)
        self.instance = InstanceFactory(domain=self.domain)
        self.site = SiteFactory(reference__domain=self.domain)
        self.community = CommunityFactory(reference__domain=self.domain)

    def test_list_posts_returns_posts(self):
        """Test that listing posts returns a list of posts"""
        PostFactory.create_batch(5, community=self.community, reference__domain=self.domain)

        response = self.client.get("/api/v3/post/list")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("posts", data)
        self.assertEqual(len(data["posts"]), 5)

    def test_list_posts_pagination(self):
        """Test pagination with limit and page parameters"""
        PostFactory.create_batch(15, community=self.community, reference__domain=self.domain)

        response = self.client.get("/api/v3/post/list", data={"limit": 5, "page": 1})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["posts"]), 5)

    def test_list_posts_filter_by_community_id(self):
        """Test filtering posts by community_id"""
        community2 = CommunityFactory(reference__domain=self.domain)
        PostFactory.create_batch(3, community=self.community, reference__domain=self.domain)
        PostFactory.create_batch(2, community=community2, reference__domain=self.domain)

        response = self.client.get(
            "/api/v3/post/list", data={"community_id": self.community.object_id}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["posts"]), 3)

    def test_list_posts_filter_by_community_name(self):
        """Test filtering posts by community name"""
        # Create actor context and account for the community
        now = timezone.now()
        actor_context, _ = ActorContext.objects.update_or_create(
            reference=self.community.reference,
            defaults={
                "type": ActorContext.Types.GROUP,
                "preferred_username": "testcommunity",
                "name": "Test Community",
                "published": now,
                "updated": now,
            },
        )
        PostFactory.create_batch(3, community=self.community, reference__domain=self.domain)

        response = self.client.get("/api/v3/post/list", data={"community_name": "testcommunity"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["posts"]), 3)

    def test_list_posts_filter_local_only(self):
        """Test filtering for local posts only"""
        remote_domain = DomainFactory(scheme="https", name="remote.com", local=False)
        PostFactory.create_batch(3, community=self.community, reference__domain=self.domain)
        PostFactory.create_batch(2, community=self.community, reference__domain=remote_domain)

        response = self.client.get("/api/v3/post/list", data={"type_": "Local"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["posts"]), 3)

    def test_list_posts_sort_by_new(self):
        """Test sorting posts by new"""
        PostFactory.create_batch(5, community=self.community, reference__domain=self.domain)

        response = self.client.get("/api/v3/post/list", data={"sort": "New"})

        self.assertEqual(response.status_code, 200)

    def test_list_posts_sort_by_hot(self):
        """Test sorting posts by hot"""
        PostFactory.create_batch(5, community=self.community, reference__domain=self.domain)

        response = self.client.get("/api/v3/post/list", data={"sort": "Hot"})

        self.assertEqual(response.status_code, 200)


class PostLikeTestCase(BaseAuthenticatedViewTestCase):
    def setUp(self):
        super().setUp()
        self.post = PostFactory(reference__domain=self.domain)

    def test_like_post_upvote(self):
        """Test upvoting a post"""
        payload = {"post_id": self.post.object_id, "score": 1}

        response = self.client.post("/api/v3/post/like", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.post, self.person.liked_posts.all())

    def test_like_post_remove_vote(self):
        """Test removing a vote from a post"""
        self.person.liked_posts.add(self.post)

        payload = {"post_id": self.post.object_id, "score": 0}

        response = self.client.post("/api/v3/post/like", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.person.refresh_from_db()
        self.assertNotIn(self.post, self.person.liked_posts.all())

    def test_like_post_downvote(self):
        """Test downvoting a post (removes from liked)"""
        payload = {"post_id": self.post.object_id, "score": -1}

        response = self.client.post("/api/v3/post/like", data=payload, format="json")

        self.assertEqual(response.status_code, 200)

    def test_like_post_requires_authentication(self):
        """Test that liking requires authentication"""
        self.client.credentials()  # Remove credentials

        payload = {"post_id": self.post.object_id, "score": 1}

        response = self.client.post("/api/v3/post/like", data=payload, format="json")

        self.assertEqual(response.status_code, 401)


class SavePostTestCase(BaseAuthenticatedViewTestCase):
    """Test cases for PUT /post/save endpoint"""

    def setUp(self):
        super().setUp()
        self.post = PostFactory(reference__domain=self.domain)

    def test_save_post(self):
        """Test saving a post"""
        payload = {"post_id": self.post.object_id, "save": True}

        response = self.client.put("/api/v3/post/save", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.post, self.identity.user.lemmy_profile.saved_posts.all())

    def test_unsave_post(self):
        """Test unsaving a post"""
        self.identity.user.lemmy_profile.saved_posts.add(self.post)

        payload = {"post_id": self.post.object_id, "save": False}

        response = self.client.put("/api/v3/post/save", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.post, self.identity.user.lemmy_profile.saved_posts.all())

    def test_save_post_requires_authentication(self):
        """Test that saving requires authentication"""
        self.client.credentials()

        payload = {"post_id": self.post.object_id, "save": True}

        response = self.client.put("/api/v3/post/save", data=payload, format="json")

        self.assertEqual(response.status_code, 401)


class DeletePostTestCase(BaseAuthenticatedViewTestCase):
    """Test cases for POST /post/delete endpoint"""

    def setUp(self):
        super().setUp()
        self.post = PostFactory(reference__domain=self.domain)
        # Set creator via the as2 context
        self.post.as2.attributed_to.add(self.person.reference)
        self.post.as2.save()

    def test_delete_post(self):
        """Test deleting a post"""
        payload = {"post_id": self.post.object_id, "deleted": True}

        response = self.client.post("/api/v3/post/delete", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.post.refresh_from_db()
        self.assertTrue(self.post.deleted)

    def test_undelete_post(self):
        """Test undeleting a post"""
        self.post.deleted = True
        self.post.save()

        payload = {"post_id": self.post.object_id, "deleted": False}

        response = self.client.post("/api/v3/post/delete", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.post.refresh_from_db()
        self.assertFalse(self.post.deleted)

    def test_delete_post_by_non_creator_fails(self):
        """Test that non-creator cannot delete post"""

        other_account = IdentityFactory(actor__reference__domain=self.domain)
        PersonFactory(reference=other_account.actor.reference)

        login_token = models.LoginToken.make(identity=other_account)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login_token.token}")

        payload = {"post_id": self.post.object_id, "deleted": True}

        response = self.client.post("/api/v3/post/delete", data=payload, format="json")

        self.assertEqual(response.status_code, 403)


class LockPostTestCase(BaseAuthenticatedViewTestCase):
    """Test cases for POST /post/lock endpoint"""

    def setUp(self):
        super().setUp()
        self.post = PostFactory(reference__domain=self.domain)

        models.LemmyContextModel.objects.create(reference=self.post.reference)

    def test_lock_post(self):
        """Test locking a post"""
        payload = {"post_id": self.post.object_id, "locked": True}

        response = self.client.post("/api/v3/post/lock", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.post.lemmy.locked)

    def test_unlock_post(self):
        """Test unlocking a post"""
        lemmy_context = models.LemmyContextModel.objects.get(reference=self.post.reference)
        lemmy_context.locked = True
        lemmy_context.save()

        payload = {"post_id": self.post.object_id, "locked": False}

        response = self.client.post("/api/v3/post/lock", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        lemmy_context.refresh_from_db()
        self.assertFalse(lemmy_context.locked)


class FeaturePostTestCase(BaseAuthenticatedViewTestCase):
    """Test cases for POST /post/feature endpoint"""

    def setUp(self):
        super().setUp()
        self.post = PostFactory(reference__domain=self.domain)

    def test_feature_post_community(self):
        """Test featuring a post in community"""
        payload = {"post_id": self.post.object_id, "featured": True, "feature_type": "Community"}

        response = self.client.post("/api/v3/post/feature", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.post.refresh_from_db()
        self.assertTrue(self.post.featured_community)

    def test_feature_post_local(self):
        """Test featuring a post locally (site-wide)"""
        payload = {"post_id": self.post.object_id, "featured": True, "feature_type": "Local"}

        response = self.client.post("/api/v3/post/feature", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.post.refresh_from_db()
        self.assertTrue(self.post.featured_local)

    def test_unfeature_post(self):
        """Test unfeaturing a post"""
        self.post.featured_community = True
        self.post.save()

        payload = {"post_id": self.post.object_id, "featured": False, "feature_type": "Community"}

        response = self.client.post("/api/v3/post/feature", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.post.refresh_from_db()
        self.assertFalse(self.post.featured_community)


class MarkPostAsReadTestCase(BaseAuthenticatedViewTestCase):
    """Test cases for POST /post/mark_as_read endpoint"""

    def setUp(self):
        super().setUp()
        self.posts = PostFactory.create_batch(3, reference__domain=self.domain)

    def test_mark_posts_as_read(self):
        """Test marking multiple posts as read"""
        post_ids = [p.object_id for p in self.posts]
        payload = {"post_ids": post_ids, "read": True}

        response = self.client.post("/api/v3/post/mark_as_read", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        for post in self.posts:
            self.assertIn(post, self.identity.user.lemmy_profile.read_posts.all())

    def test_mark_posts_as_unread(self):
        """Test marking posts as unread"""
        for post in self.posts:
            self.identity.user.lemmy_profile.read_posts.add(post)

        post_ids = [p.object_id for p in self.posts]
        payload = {"post_ids": post_ids, "read": False}

        response = self.client.post("/api/v3/post/mark_as_read", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        for post in self.posts:
            self.assertNotIn(post, self.identity.user.lemmy_profile.read_posts.all())


class RemovePostTestCase(BaseAuthenticatedViewTestCase):
    """Test cases for POST /post/remove endpoint"""

    def setUp(self):
        super().setUp()
        self.post = PostFactory(reference__domain=self.domain)

    def test_remove_post(self):
        """Test moderator removing a post"""
        payload = {"post_id": self.post.object_id, "removed": True}

        response = self.client.post("/api/v3/post/remove", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.post.refresh_from_db()
        self.assertTrue(self.post.removed)

    def test_unremoving_post(self):
        """Test unremoving a post"""
        self.post.removed = True
        self.post.save()

        payload = {"post_id": self.post.object_id, "removed": False}

        response = self.client.post("/api/v3/post/remove", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.post.refresh_from_db()
        self.assertFalse(self.post.removed)


class HidePostTestCase(BaseAuthenticatedViewTestCase):
    """Test cases for POST /post/hide endpoint"""

    def setUp(self):
        super().setUp()
        self.posts = PostFactory.create_batch(3, reference__domain=self.domain)

    def test_hide_posts(self):
        """Test hiding multiple posts"""
        post_ids = [p.object_id for p in self.posts]
        payload = {"post_ids": post_ids, "hide": True}

        response = self.client.post("/api/v3/post/hide", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        for post in self.posts:
            self.assertIn(post, self.identity.user.lemmy_profile.hidden_posts.all())

    def test_unhide_posts(self):
        """Test unhiding posts"""
        for post in self.posts:
            self.identity.user.lemmy_profile.hidden_posts.add(post)

        post_ids = [p.object_id for p in self.posts]
        payload = {"post_ids": post_ids, "hide": False}

        response = self.client.post("/api/v3/post/hide", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        for post in self.posts:
            self.assertNotIn(post, self.identity.user.lemmy_profile.hidden_posts.all())


class CreatePostReportTestCase(BaseAuthenticatedViewTestCase):
    """Test cases for POST /post/report endpoint"""

    def setUp(self):
        super().setUp()
        self.post = PostFactory(reference__domain=self.domain)

    def test_create_post_report(self):
        """Test creating a post report"""
        payload = {
            "post_id": self.post.object_id,
            "reason": "This post violates community guidelines",
        }

        response = self.client.post("/api/v3/post/report", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("post_report_view", data)
        post_report_view = data["post_report_view"]

        # Verify report was created
        self.assertIn("post_report", post_report_view)
        self.assertEqual(post_report_view["post_report"]["post_id"], self.post.object_id)
        self.assertEqual(
            post_report_view["post_report"]["reason"], "This post violates community guidelines"
        )
        self.assertFalse(post_report_view["post_report"]["resolved"])
        report = models.Report.objects.first()
        self.assertIsNotNone(report)
        self.assertEqual(report.as2.object, self.post.reference)

    def test_create_post_report_invalid_post_id(self):
        """Test creating a report with invalid post_id"""
        payload = {"post_id": 999999, "reason": "Invalid post"}

        response = self.client.post("/api/v3/post/report", data=payload, format="json")

        self.assertEqual(response.status_code, 404)

    def test_create_post_report_requires_authentication(self):
        """Test that reporting requires authentication"""
        self.client.credentials()  # Remove credentials

        payload = {"post_id": self.post.object_id, "reason": "Test report"}

        response = self.client.post("/api/v3/post/report", data=payload, format="json")

        self.assertEqual(response.status_code, 401)


class ResolvePostReportTestCase(BaseAuthenticatedViewTestCase):
    """Test cases for PUT /post/report/resolve endpoint"""

    def setUp(self):
        super().setUp()
        self.post = PostFactory(reference__domain=self.domain)

        flag_ref = Reference.make(uri=f"{self.post.reference.domain.url}/report/{generate_ulid()}")
        ActivityContext.make(
            reference=flag_ref,
            type=ActivityContext.Types.FLAG,
            actor=self.person.reference,
            object=self.post.reference,
            content="Test report",
            published=timezone.now(),
        )
        self.report = models.Report.objects.create(reference=flag_ref)

    def test_resolve_post_report(self):
        """Test resolving a post report"""
        payload = {"report_id": self.report.object_id, "resolved": True}

        response = self.client.put("/api/v3/post/report/resolve", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("post_report_view", data)
        post_report_view = data["post_report_view"]

        # Verify report was resolved
        self.assertIn("post_report", post_report_view)
        self.assertTrue(post_report_view["post_report"]["resolved"])
        self.assertIsNotNone(post_report_view["post_report"]["resolver_id"])

        # Verify report in database
        self.report.refresh_from_db()
        self.assertTrue(self.report.resolved)
        self.assertIsNotNone(self.report.resolved_by)

    def test_unresolve_post_report(self):
        """Test unresolving a post report"""
        self.report.resolved_by = self.person.reference
        self.report.resolved_on = timezone.now()
        self.report.save()

        payload = {"report_id": self.report.object_id, "resolved": False}

        response = self.client.put("/api/v3/post/report/resolve", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("post_report_view", data)
        post_report_view = data["post_report_view"]

        # Verify report was unresolved
        self.assertFalse(post_report_view["post_report"]["resolved"])
        self.assertIsNone(post_report_view["post_report"]["resolver_id"])

        # Verify report in database
        self.report.refresh_from_db()
        self.assertFalse(self.report.resolved)
        self.assertIsNone(self.report.resolved_by)

    def test_resolve_nonexistent_report(self):
        """Test resolving a non-existent report"""
        payload = {"report_id": 999999, "resolved": True}

        response = self.client.put("/api/v3/post/report/resolve", data=payload, format="json")

        self.assertEqual(response.status_code, 404)

    def test_resolve_report_requires_authentication(self):
        """Test that resolving requires authentication"""
        self.client.credentials()  # Remove credentials

        payload = {"report_id": self.report.object_id, "resolved": True}

        response = self.client.put("/api/v3/post/report/resolve", data=payload, format="json")

        self.assertEqual(response.status_code, 401)


class ListPostReportsTestCase(BaseAuthenticatedViewTestCase):
    """Test cases for GET /post/report/list endpoint"""

    def setUp(self):
        super().setUp()
        self.post = PostFactory(reference__domain=self.domain)

        moderator_account = IdentityFactory(actor__reference__domain=self.domain)
        self.moderator = PersonFactory(reference=moderator_account.actor.reference)

        flag_ref = Reference.make(uri=f"{self.post.reference.domain.url}/report/{generate_ulid()}")
        ActivityContext.make(
            reference=flag_ref,
            type=ActivityContext.Types.FLAG,
            actor=self.person.reference,
            object=self.post.reference,
            content="Test report",
            published=timezone.now(),
        )
        self.report = models.Report.objects.create(reference=flag_ref)

    def test_list_post_reports(self):
        """Test listing post reports"""
        response = self.client.get("/api/v3/post/report/list")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("post_reports", data)
        self.assertIsInstance(data["post_reports"], list)
        self.assertGreaterEqual(len(data["post_reports"]), 1)

        # Check structure of first report
        report_view = data["post_reports"][0]
        self.assertIn("post_report", report_view)
        self.assertIn("post", report_view)
        self.assertIn("community", report_view)
        self.assertIn("creator", report_view)

    def test_list_post_reports_unresolved_only(self):
        """Test listing only unresolved reports"""

        flag_ref = Reference.make(uri=f"{self.post.reference.domain.url}/report/{generate_ulid()}")
        ActivityContext.make(
            reference=flag_ref,
            type=ActivityContext.Types.FLAG,
            actor=self.person.reference,
            object=self.post.reference,
            content="Test report",
            published=timezone.now(),
        )
        models.Report.objects.create(reference=flag_ref, resolved_by=self.moderator.reference)

        # Test unresolved_only=True
        response = self.client.get("/api/v3/post/report/list", {"unresolved_only": True})

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("post_reports", data)
        # Should only return unresolved reports
        for report_view in data["post_reports"]:
            self.assertFalse(report_view["post_report"]["resolved"])

    def test_list_post_reports_by_community(self):
        """Test filtering reports by community"""
        community_id = self.post.community.object_id
        response = self.client.get("/api/v3/post/report/list", {"community_id": community_id})

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("post_reports", data)
        # All returned reports should be for posts in this community
        for report_view in data["post_reports"]:
            self.assertEqual(report_view["community"]["id"], community_id)

    def test_list_post_reports_by_post(self):
        """Test filtering reports by specific post"""
        post_id = self.post.object_id
        response = self.client.get("/api/v3/post/report/list", {"post_id": post_id})

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("post_reports", data)
        # All returned reports should be for this post
        for report_view in data["post_reports"]:
            self.assertEqual(report_view["post"]["id"], post_id)

    def test_list_post_reports_pagination(self):
        """Test pagination of post reports"""
        response = self.client.get("/api/v3/post/report/list", {"page": 1, "limit": 10})

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("post_reports", data)
        self.assertIsInstance(data["post_reports"], list)

    def test_list_post_reports_requires_authentication(self):
        """Test that listing reports requires authentication"""
        self.client.credentials()  # Remove credentials

        response = self.client.get("/api/v3/post/report/list")

        self.assertEqual(response.status_code, 401)


class DeleteCommentTestCase(BaseAuthenticatedViewTestCase):
    """Test cases for POST /comment/delete endpoint"""

    def setUp(self):
        super().setUp()
        self.post = PostFactory(reference__domain=self.domain)

        comment_ref = ReferenceFactory(path="/comment/1", domain=self.domain)
        now = timezone.now()
        ObjectContext.make(
            reference=comment_ref,
            type=ObjectContext.Types.NOTE,
            content="Test comment content",
            published=now,
            updated=now,
        )
        self.comment = models.Comment.objects.create(reference=comment_ref, post=self.post)
        self.comment.as2.attributed_to.add(self.person.reference)
        self.comment.as2.save()

    def test_delete_comment(self):
        """Test deleting a comment"""
        payload = {"comment_id": self.comment.object_id, "deleted": True}

        response = self.client.post("/api/v3/comment/delete", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.comment.refresh_from_db()
        self.assertTrue(self.comment.deleted)

    def test_undelete_comment(self):
        """Test undeleting a comment"""
        self.comment.deleted = True
        self.comment.save()

        payload = {"comment_id": self.comment.object_id, "deleted": False}

        response = self.client.post("/api/v3/comment/delete", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.comment.refresh_from_db()
        self.assertFalse(self.comment.deleted)

    def test_delete_comment_by_non_creator_fails(self):
        """Test that non-creator cannot delete comment"""
        other_account = IdentityFactory(actor__reference__domain=self.domain)
        PersonFactory(reference=other_account.actor.reference)

        login_token = models.LoginToken.make(identity=other_account)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login_token.token}")

        payload = {"comment_id": self.comment.object_id, "deleted": True}

        response = self.client.post("/api/v3/comment/delete", data=payload, format="json")

        self.assertEqual(response.status_code, 403)

    def test_delete_comment_requires_authentication(self):
        """Test that deleting requires authentication"""
        self.client.credentials()

        payload = {"comment_id": self.comment.object_id, "deleted": True}

        response = self.client.post("/api/v3/comment/delete", data=payload, format="json")

        self.assertEqual(response.status_code, 401)


class CommentLikeTestCase(BaseAuthenticatedViewTestCase):
    """Test cases for POST /comment/like endpoint"""

    def setUp(self):
        super().setUp()
        self.post = PostFactory(reference__domain=self.domain)
        self.comment = CommentFactory(reference__domain=self.domain, post=self.post)

    def test_like_comment_upvote(self):
        """Test upvoting a comment"""
        payload = {"comment_id": self.comment.object_id, "score": 1}

        response = self.client.post("/api/v3/comment/like", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.comment, self.person.liked_comments.all())

    def test_like_comment_remove_vote(self):
        """Test removing a vote from a comment"""
        self.person.liked_comments.add(self.comment)

        payload = {"comment_id": self.comment.object_id, "score": 0}

        response = self.client.post("/api/v3/comment/like", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.comment, self.person.liked_comments.all())

    def test_like_comment_downvote(self):
        """Test downvoting a comment (removes from liked)"""
        payload = {"comment_id": self.comment.object_id, "score": -1}

        response = self.client.post("/api/v3/comment/like", data=payload, format="json")

        self.assertEqual(response.status_code, 200)

    def test_like_comment_requires_authentication(self):
        """Test that liking requires authentication"""
        self.client.credentials()

        payload = {"comment_id": self.comment.object_id, "score": 1}

        response = self.client.post("/api/v3/comment/like", data=payload, format="json")

        self.assertEqual(response.status_code, 401)


class SaveCommentTestCase(BaseAuthenticatedViewTestCase):
    """Test cases for PUT /comment/save endpoint"""

    def setUp(self):
        super().setUp()
        self.post = PostFactory(reference__domain=self.domain)
        self.comment = CommentFactory(reference__domain=self.domain, post=self.post)

    def test_save_comment(self):
        """Test saving a comment"""
        payload = {"comment_id": self.comment.object_id, "save": True}

        response = self.client.put("/api/v3/comment/save", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.comment, self.identity.user.lemmy_profile.saved_comments.all())

    def test_unsave_comment(self):
        """Test unsaving a comment"""
        self.identity.user.lemmy_profile.saved_comments.add(self.comment)

        payload = {"comment_id": self.comment.object_id, "save": False}

        response = self.client.put("/api/v3/comment/save", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.comment, self.identity.user.lemmy_profile.saved_comments.all())

    def test_save_comment_requires_authentication(self):
        """Test that saving requires authentication"""
        self.client.credentials()

        payload = {"comment_id": self.comment.object_id, "save": True}

        response = self.client.put("/api/v3/comment/save", data=payload, format="json")

        self.assertEqual(response.status_code, 401)


class RemoveCommentTestCase(BaseAuthenticatedViewTestCase):
    """Test cases for POST /comment/remove endpoint"""

    def setUp(self):
        super().setUp()
        self.post = PostFactory(reference__domain=self.domain)
        self.comment = CommentFactory(reference__domain=self.domain, post=self.post)

    def test_remove_comment(self):
        """Test removing a comment (moderator action)"""
        payload = {"comment_id": self.comment.object_id, "removed": True}

        response = self.client.post("/api/v3/comment/remove", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.comment.refresh_from_db()
        self.assertTrue(self.comment.removed)

    def test_unremoving_comment(self):
        """Test unremoving a comment"""
        self.comment.removed = True
        self.comment.save()

        payload = {"comment_id": self.comment.object_id, "removed": False}

        response = self.client.post("/api/v3/comment/remove", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.comment.refresh_from_db()
        self.assertFalse(self.comment.removed)

    def test_remove_comment_requires_authentication(self):
        """Test that removing requires authentication"""
        self.client.credentials()

        payload = {"comment_id": self.comment.object_id, "removed": True}

        response = self.client.post("/api/v3/comment/remove", data=payload, format="json")

        self.assertEqual(response.status_code, 401)


class ListCommentsTestCase(BaseAuthenticatedViewTestCase):
    """Test cases for GET /comment/list endpoint"""

    def setUp(self):
        super().setUp()
        self.post = PostFactory(reference__domain=self.domain)

        self.comment1 = CommentFactory(reference__domain=self.domain, post=self.post)
        self.comment2 = CommentFactory(reference__domain=self.domain, post=self.post)
        self.comment3 = CommentFactory(reference__domain=self.domain, post=self.post)

    def test_list_comments(self):
        """Test listing all comments"""
        response = self.client.get("/api/v3/comment/list")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("comments", data)
        self.assertGreaterEqual(len(data["comments"]), 3)

    def test_list_comments_by_post(self):
        """Test filtering comments by post"""
        other_post = PostFactory(reference__domain=self.domain)
        CommentFactory(reference__domain=self.domain, post=other_post)

        response = self.client.get(f"/api/v3/comment/list?post_id={self.post.object_id}")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("comments", data)
        for comment_view in data["comments"]:
            self.assertEqual(comment_view["comment"]["post_id"], self.post.object_id)

    def test_list_saved_comments(self):
        """Test listing only saved comments"""
        self.identity.user.lemmy_profile.saved_comments.add(self.comment1)

        response = self.client.get("/api/v3/comment/list?saved_only=true")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("comments", data)
        comment_ids = [c["comment"]["id"] for c in data["comments"]]
        self.assertIn(self.comment1.object_id, comment_ids)

    def test_list_liked_comments(self):
        """Test listing only liked comments"""
        self.person.liked_comments.add(self.comment2)

        response = self.client.get("/api/v3/comment/list?liked_only=true")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("comments", data)
        comment_ids = [c["comment"]["id"] for c in data["comments"]]
        self.assertIn(self.comment2.object_id, comment_ids)

    def test_list_comments_pagination(self):
        """Test comment list pagination"""
        for _ in range(15):
            CommentFactory(reference__domain=self.domain, post=self.post)

        response = self.client.get("/api/v3/comment/list?limit=5&page=1")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("comments", data)
        self.assertLessEqual(len(data["comments"]), 5)


class CreateCommentReportTestCase(BaseAuthenticatedViewTestCase):
    """Test cases for POST /comment/report endpoint"""

    def setUp(self):
        super().setUp()
        self.post = PostFactory(reference__domain=self.domain)
        self.comment = CommentFactory(reference__domain=self.domain, post=self.post)

    def test_create_comment_report(self):
        """Test creating a comment report"""
        payload = {"comment_id": self.comment.object_id, "reason": "This comment is spam"}

        response = self.client.post("/api/v3/comment/report", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("comment_report_view", data)
        comment_report_view = data["comment_report_view"]

        self.assertIn("comment_report", comment_report_view)
        self.assertEqual(
            comment_report_view["comment_report"]["comment_id"], self.comment.object_id
        )
        self.assertEqual(comment_report_view["comment_report"]["reason"], "This comment is spam")
        self.assertFalse(comment_report_view["comment_report"]["resolved"])

        report = models.Report.objects.first()
        self.assertIsNotNone(report)

    def test_create_comment_report_invalid_comment_id(self):
        """Test creating a report with invalid comment_id"""
        payload = {"comment_id": 999999, "reason": "Invalid comment"}

        response = self.client.post("/api/v3/comment/report", data=payload, format="json")

        self.assertEqual(response.status_code, 404)

    def test_create_comment_report_requires_authentication(self):
        """Test that reporting requires authentication"""
        self.client.credentials()

        payload = {"comment_id": self.comment.object_id, "reason": "Test report"}

        response = self.client.post("/api/v3/comment/report", data=payload, format="json")

        self.assertEqual(response.status_code, 401)


class ResolveCommentReportTestCase(BaseAuthenticatedViewTestCase):
    """Test cases for PUT /comment/report/resolve endpoint"""

    def setUp(self):
        super().setUp()
        self.post = PostFactory(reference__domain=self.domain)
        self.comment = CommentFactory(reference__domain=self.domain, post=self.post)
        self.moderator_account = IdentityFactory(actor__reference__domain=self.domain)

        flag_ref = Reference.make(
            uri=f"{self.comment.reference.domain.url}/report/{generate_ulid()}"
        )
        ActivityContext.make(
            reference=flag_ref,
            type=ActivityContext.Types.FLAG,
            actor=self.person.reference,
            object=self.comment.reference,
            content="Test report",
            published=timezone.now(),
        )
        self.report = models.Report.objects.create(reference=flag_ref)

    def test_resolve_comment_report(self):
        """Test resolving a comment report"""
        payload = {"report_id": self.report.object_id, "resolved": True}

        response = self.client.put("/api/v3/comment/report/resolve", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("comment_report_view", data)
        comment_report_view = data["comment_report_view"]

        self.assertIn("comment_report", comment_report_view)
        self.assertTrue(comment_report_view["comment_report"]["resolved"])
        self.assertIsNotNone(comment_report_view["comment_report"]["resolver_id"])

        self.report.refresh_from_db()
        self.assertTrue(self.report.resolved)
        self.assertIsNotNone(self.report.resolved_by)

    def test_unresolve_comment_report(self):
        """Test unresolving a comment report"""
        self.report.resolved_on = timezone.now()
        self.report.resolved_by = self.moderator_account.actor.reference
        self.report.save()

        payload = {"report_id": self.report.object_id, "resolved": False}

        response = self.client.put("/api/v3/comment/report/resolve", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("comment_report_view", data)
        comment_report_view = data["comment_report_view"]

        self.assertFalse(comment_report_view["comment_report"]["resolved"])
        self.assertIsNone(comment_report_view["comment_report"]["resolver_id"])

        self.report.refresh_from_db()
        self.assertFalse(self.report.resolved)
        self.assertIsNone(self.report.resolved_by)

    def test_resolve_nonexistent_report(self):
        """Test resolving a non-existent report"""
        payload = {"report_id": 999999, "resolved": True}

        response = self.client.put("/api/v3/comment/report/resolve", data=payload, format="json")

        self.assertEqual(response.status_code, 404)

    def test_resolve_report_requires_authentication(self):
        """Test that resolving requires authentication"""
        self.client.credentials()

        payload = {"report_id": self.report.object_id, "resolved": True}

        response = self.client.put("/api/v3/comment/report/resolve", data=payload, format="json")

        self.assertEqual(response.status_code, 401)


class ListCommentReportsTestCase(BaseAuthenticatedViewTestCase):
    """Test cases for GET /comment/report/list endpoint"""

    def setUp(self):
        super().setUp()
        self.post = PostFactory(reference__domain=self.domain)
        self.comment = CommentFactory(reference__domain=self.domain, post=self.post)

        flag_ref = Reference.make(
            uri=f"{self.comment.reference.domain.url}/report/{generate_ulid()}"
        )
        ActivityContext.make(
            reference=flag_ref,
            type=ActivityContext.Types.FLAG,
            actor=self.person.reference,
            object=self.comment.reference,
            content="Test report",
            published=timezone.now(),
        )

        self.report = models.Report.objects.create(reference=flag_ref)

    def test_list_comment_reports(self):
        """Test listing comment reports"""
        response = self.client.get("/api/v3/comment/report/list")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("comment_reports", data)
        self.assertIsInstance(data["comment_reports"], list)
        self.assertGreaterEqual(len(data["comment_reports"]), 1)

        report_view = data["comment_reports"][0]
        self.assertIn("comment_report", report_view)
        self.assertIn("comment", report_view)
        self.assertIn("post", report_view)
        self.assertIn("community", report_view)
        self.assertIn("creator", report_view)

    def test_list_comment_reports_unresolved_only(self):
        flag_ref = Reference.make(
            uri=f"{self.comment.reference.domain.url}/report/{generate_ulid()}"
        )
        ActivityContext.make(
            reference=flag_ref,
            type=ActivityContext.Types.FLAG,
            actor=self.person.reference,
            object=self.comment.reference,
            content="Resolved report",
            published=timezone.now(),
        )

        response = self.client.get("/api/v3/comment/report/list", {"unresolved_only": True})

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("comment_reports", data)
        for report_view in data["comment_reports"]:
            self.assertFalse(report_view["comment_report"]["resolved"])

    def test_list_comment_reports_requires_authentication(self):
        """Test that listing requires authentication"""
        self.client.credentials()

        response = self.client.get("/api/v3/comment/report/list")

        self.assertEqual(response.status_code, 401)


class MarkCommentAsReadTestCase(BaseAuthenticatedViewTestCase):
    """Test cases for POST /comment/mark_as_read endpoint"""

    def setUp(self):
        super().setUp()
        self.post = PostFactory(reference__domain=self.domain)
        self.comment = CommentFactory(reference__domain=self.domain, post=self.post)

    def test_mark_comment_as_read(self):
        """Test marking a comment as read"""
        payload = {"comment_reply_id": self.comment.object_id, "read": True}

        response = self.client.post("/api/v3/comment/mark_as_read", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.comment, self.identity.user.lemmy_profile.read_comments.all())

    def test_mark_comment_as_unread(self):
        """Test marking a comment as unread"""
        self.identity.user.lemmy_profile.read_comments.add(self.comment)

        payload = {"comment_reply_id": self.comment.object_id, "read": False}

        response = self.client.post("/api/v3/comment/mark_as_read", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.comment, self.identity.user.lemmy_profile.read_comments.all())

    def test_mark_comment_as_read_requires_authentication(self):
        """Test that marking as read requires authentication"""
        self.client.credentials()

        payload = {"comment_reply_id": self.comment.object_id, "read": True}

        response = self.client.post("/api/v3/comment/mark_as_read", data=payload, format="json")

        self.assertEqual(response.status_code, 401)


class DistinguishCommentTestCase(BaseAuthenticatedViewTestCase):
    """Test cases for POST /comment/distinguish endpoint"""

    def setUp(self):
        super().setUp()
        self.post = PostFactory(reference__domain=self.domain)
        self.comment = CommentFactory(reference__domain=self.domain, post=self.post)

    def test_distinguish_comment(self):
        """Test distinguishing a comment"""
        payload = {"comment_id": self.comment.object_id, "distinguished": True}

        response = self.client.post("/api/v3/comment/distinguish", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.comment.lemmy.refresh_from_db()
        self.assertTrue(self.comment.lemmy.distinguished)

    def test_undistinguish_comment(self):
        """Test undistinguishing a comment"""
        lemmy_ctx = self.comment.lemmy
        lemmy_ctx.distinguished = True
        lemmy_ctx.save()

        payload = {"comment_id": self.comment.object_id, "distinguished": False}

        response = self.client.post("/api/v3/comment/distinguish", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.comment.lemmy.refresh_from_db()
        self.assertFalse(self.comment.lemmy.distinguished)

    def test_distinguish_comment_requires_authentication(self):
        """Test that distinguishing requires authentication"""
        self.client.credentials()

        payload = {"comment_id": self.comment.object_id, "distinguished": True}

        response = self.client.post("/api/v3/comment/distinguish", data=payload, format="json")

        self.assertEqual(response.status_code, 401)


class ListCommentLikesTestCase(BaseAuthenticatedViewTestCase):
    """Test cases for GET /comment/like/list endpoint (admin only)"""

    def setUp(self):
        super().setUp()
        self.post = PostFactory(reference__domain=self.domain)
        self.comment = CommentFactory(reference__domain=self.domain, post=self.post)

        self.person.liked_comments.add(self.comment)

        site = SiteFactory(reference__domain=self.domain)
        site.admins.add(self.person)

    def test_list_comment_likes(self):
        """Test listing comment likes"""
        response = self.client.get(
            f"/api/v3/comment/like/list?comment_id={self.comment.object_id}"
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("comment_likes", data)
        self.assertIsInstance(data["comment_likes"], list)
        self.assertEqual(len(data["comment_likes"]), 1)

    def test_list_comment_likes_requires_authentication(self):
        """Test that listing likes requires authentication"""
        self.client.credentials()

        response = self.client.get(
            f"/api/v3/comment/like/list?comment_id={self.comment.object_id}"
        )

        self.assertEqual(response.status_code, 401)


class PurgeCommentTestCase(BaseAuthenticatedViewTestCase):
    """Test cases for POST /admin/purge/comment endpoint (admin only)"""

    def setUp(self):
        super().setUp()
        self.post = PostFactory(reference__domain=self.domain)
        self.comment = CommentFactory(reference__domain=self.domain, post=self.post)

        site = SiteFactory(reference__domain=self.domain)
        site.admins.add(self.person)

    def test_purge_comment(self):
        """Test purging a comment"""
        comment_id = self.comment.object_id
        payload = {"comment_id": comment_id}

        response = self.client.post("/api/v3/admin/purge/comment", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])

        self.assertFalse(models.Comment.objects.filter(object_id=comment_id).exists())

    def test_purge_comment_requires_authentication(self):
        """Test that purging requires authentication"""
        self.client.credentials()

        payload = {"comment_id": self.comment.object_id}

        response = self.client.post("/api/v3/admin/purge/comment", data=payload, format="json")

        self.assertEqual(response.status_code, 401)


class GetCommunityTestCase(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        self.domain = DomainFactory(scheme="http", name="testserver", local=True)
        self.instance = InstanceFactory(domain=self.domain)
        self.site = SiteFactory(reference__domain=self.domain)
        self.actor = ActorFactory(
            preferred_username="testcommunity", reference__domain=self.domain
        )
        self.community = CommunityFactory(reference=self.actor.reference)

    def test_get_community_by_id(self):
        """Test getting a community by ID"""
        response = self.client.get("/api/v3/community", data={"id": self.community.object_id})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("community_view", data)
        self.assertEqual(data["community_view"]["community"]["id"], self.community.object_id)

    def test_get_community_by_name(self):
        """Test getting a community by name"""
        response = self.client.get("/api/v3/community", data={"name": "testcommunity"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("community_view", data)

    def test_get_community_by_name_with_domain(self):
        """Test getting a community by name@domain format"""
        response = self.client.get("/api/v3/community", data={"name": "testcommunity@testserver"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("community_view", data)

    def test_get_community_without_id_or_name_fails(self):
        """Test that getting a community without id or name fails"""
        response = self.client.get("/api/v3/community", data={})

        self.assertEqual(response.status_code, 400)

    def test_get_nonexistent_community_by_id(self):
        """Test getting a nonexistent community returns 404"""
        response = self.client.get("/api/v3/community", data={"id": 99999})

        self.assertEqual(response.status_code, 404)

    def test_get_nonexistent_community_by_name(self):
        """Test getting a nonexistent community by name returns 404"""
        response = self.client.get("/api/v3/community", data={"name": "nonexistent"})

        self.assertEqual(response.status_code, 404)


class ListCommunitiesTestCase(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        self.domain = DomainFactory(scheme="http", name="testserver", local=True)
        self.instance = InstanceFactory(domain=self.domain)
        self.site = SiteFactory(reference__domain=self.domain)

        self.community1 = CommunityFactory(reference__domain=self.domain)
        self.community2 = CommunityFactory(reference__domain=self.domain)
        self.community3 = CommunityFactory(reference__domain=self.domain)

    def test_list_communities(self):
        """Test listing communities"""
        response = self.client.get("/api/v3/community/list")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("communities", data)
        self.assertGreaterEqual(len(data["communities"]), 3)

    def test_list_communities_pagination(self):
        """Test communities pagination"""
        response = self.client.get("/api/v3/community/list", data={"page": 1, "limit": 2})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("communities", data)

    def test_list_local_communities_only(self):
        """Test filtering local communities"""
        response = self.client.get("/api/v3/community/list", data={"type_": "Local"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("communities", data)
        for community in data["communities"]:
            self.assertTrue(community["community"]["local"])


class FollowCommunityTestCase(BaseAuthenticatedViewTestCase):
    def setUp(self):
        super().setUp()
        self.community = CommunityFactory(reference__domain=self.domain)

    def test_follow_community(self):
        payload = {"community_id": self.community.object_id, "follow": True}

        response = self.client.post("/api/v3/community/follow", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("community_view", data)

        follow_request = FollowRequest.objects.filter(
            follower=self.person.reference, followed=self.community.reference
        ).first()
        self.assertIsNotNone(follow_request)
        self.assertEqual(follow_request.status, FollowRequest.STATUS.submitted)

    def test_unfollow_community(self):
        """Test unfollowing a community"""

        # create the original follow request (we can only unfollow if we have a follow record)
        follow_activity = ActivityFactory(
            type=ActivityContext.Types.FOLLOW,
            actor=self.person.reference,
            object=self.community.reference,
        )

        FollowRequestFactory(
            follower=self.person.reference,
            followed=self.community.reference,
            activity=follow_activity.reference,
            status=FollowRequest.STATUS.accepted,
        )

        followers_collection = self.community.as2.followers.get_by_context(CollectionContext)
        followers_collection.append(self.person.reference)

        payload = {"community_id": self.community.object_id, "follow": False}

        response = self.client.post("/api/v3/community/follow", data=payload, format="json")
        self.assertEqual(response.status_code, 200)

        followers_collection.refresh_from_db()
        self.assertFalse(followers_collection.contains(self.person.reference))

    def test_follow_community_requires_authentication(self):
        """Test that following requires authentication"""
        self.client.credentials()

        payload = {"community_id": self.community.object_id, "follow": True}

        response = self.client.post("/api/v3/community/follow", data=payload, format="json")

        self.assertEqual(response.status_code, 401)


class BlockCommunityTestCase(BaseAuthenticatedViewTestCase):
    def setUp(self):
        super().setUp()
        self.community = CommunityFactory(reference__domain=self.domain)

    def test_block_community(self):
        """Test blocking a community"""
        payload = {"community_id": self.community.object_id, "block": True}

        response = self.client.post("/api/v3/community/block", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("community_view", data)
        self.assertTrue(data["blocked"])

        self.assertTrue(
            self.person.blocked_communities.filter(object_id=self.community.object_id).exists()
        )

    def test_unblock_community(self):
        """Test unblocking a community"""
        self.person.blocked_communities.add(self.community)

        payload = {"community_id": self.community.object_id, "block": False}

        response = self.client.post("/api/v3/community/block", data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["blocked"])

        self.assertFalse(
            self.person.blocked_communities.filter(object_id=self.community.object_id).exists()
        )

    def test_block_community_requires_authentication(self):
        """Test that blocking requires authentication"""
        self.client.credentials()

        payload = {"community_id": self.community.object_id, "block": True}

        response = self.client.post("/api/v3/community/block", data=payload, format="json")

        self.assertEqual(response.status_code, 401)


class GetPersonDetailsTestCase(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        self.domain = DomainFactory(scheme="http", name="testserver", local=True)
        self.site = SiteFactory(reference__domain=self.domain)
        self.actor = ActorFactory(preferred_username="testuser", reference__domain=self.domain)
        self.person = PersonFactory(reference=self.actor.reference)

    def test_get_person_by_id(self):
        """Test getting a person by ID"""
        response = self.client.get("/api/v3/user", data={"person_id": self.person.object_id})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("person_view", data)
        self.assertIn("site", data)
        self.assertIn("comments", data)
        self.assertIn("posts", data)
        self.assertIn("moderates", data)
        self.assertEqual(data["person_view"]["person"]["id"], self.person.object_id)

    def test_get_person_by_username(self):
        """Test getting a person by username"""
        response = self.client.get("/api/v3/user", data={"username": "testuser"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("person_view", data)
        self.assertEqual(data["person_view"]["person"]["name"], "testuser")

    def test_get_person_by_username_with_domain(self):
        """Test getting a person by username@domain format"""
        response = self.client.get("/api/v3/user", data={"username": "testuser@testserver"})
        data = response.json()
        self.assertIn("person_view", data)

    def test_get_person_without_id_or_username_fails(self):
        """Test that getting a person without id or username fails"""
        response = self.client.get("/api/v3/user", data={})

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data["error"], "no_id_given")

    def test_get_nonexistent_person_by_id(self):
        """Test getting a nonexistent person returns 404"""
        response = self.client.get("/api/v3/user", data={"person_id": 99999})

        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertEqual(data["error"], "couldnt_find_person")

    def test_get_nonexistent_person_by_username(self):
        """Test getting a nonexistent person by username returns 404"""
        response = self.client.get("/api/v3/user", data={"username": "nonexistent"})

        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertEqual(data["error"], "couldnt_find_person")

    def test_get_person_returns_empty_lists_when_no_content(self):
        """Test that empty lists are returned when person has no posts/comments"""
        response = self.client.get("/api/v3/user", data={"person_id": self.person.object_id})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["posts"]), 0)
        self.assertEqual(len(data["comments"]), 0)
        self.assertEqual(len(data["moderates"]), 0)


@override_settings(
    FEDERATION={"DEFAULT_URL": "http://testserver", "FORCE_INSECURE_HTTP": True},
    ALLOWED_HOSTS=["testserver"],
)
class SearchViewTestCase(TransactionTestCase):
    """Test cases for GET /api/v3/search endpoint"""

    def setUp(self):
        self.client = APIClient()
        self.domain = DomainFactory(scheme="http", name="testserver", local=True)
        self.instance = InstanceFactory(domain=self.domain)
        self.site = SiteFactory(reference__domain=self.domain)

    def test_search_returns_empty_results_for_no_matches(self):
        """Test that search returns empty results when no content matches"""
        response = self.client.get("/api/v3/search", data={"q": "nonexistent_content_xyz"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["comments"], [])
        self.assertEqual(data["posts"], [])
        self.assertEqual(data["communities"], [])
        self.assertEqual(data["users"], [])

    def test_search_missing_query_returns_error(self):
        """Test that missing query parameter returns validation error"""
        response = self.client.get("/api/v3/search")

        self.assertEqual(response.status_code, 400)
        self.assertIn("q", response.json())

    def test_search_empty_query_returns_error(self):
        """Test that empty query string returns validation error"""
        response = self.client.get("/api/v3/search", data={"q": ""})

        self.assertEqual(response.status_code, 400)

    def test_search_person_by_webfinger_address(self):
        """Test searching for a person by @user@domain"""
        actor = ActorFactory(preferred_username="searchuser", reference__domain=self.domain)
        person = PersonFactory(reference=actor.reference)

        response = self.client.get("/api/v3/search", data={"q": "@searchuser@testserver"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["users"]), 1)
        self.assertEqual(data["users"][0]["person"]["id"], person.object_id)

    def test_search_community_by_webfinger_address(self):
        """Test searching for a community by !community@domain"""
        community_ref = Reference.objects.create(
            uri="http://testserver/c/searchcommunity", domain=self.domain
        )

        now = timezone.now()
        ActorContext.make(
            reference=community_ref,
            type=ActorContext.Types.GROUP,
            preferred_username="searchcommunity",
            name="Search Test Community",
            published=now,
            updated=now,
        )
        community = models.Community.objects.create(reference=community_ref)

        response = self.client.get("/api/v3/search", data={"q": "!searchcommunity@testserver"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["communities"]), 1)
        self.assertEqual(data["communities"][0]["community"]["id"], community.object_id)

    def test_search_person_by_url(self):
        """Test searching for a person by direct URL"""
        actor = ActorFactory(preferred_username="urluser", reference__domain=self.domain)
        person = PersonFactory(reference=actor.reference)

        response = self.client.get("/api/v3/search", data={"q": "http://testserver/users/urluser"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["users"]), 1)
        self.assertEqual(data["users"][0]["person"]["id"], person.object_id)

    def test_search_post_by_url(self):
        """Test searching for a post by direct URL"""
        post = PostFactory(reference__path="/post/searchtest", reference__domain=self.domain)

        response = self.client.get(
            "/api/v3/search", data={"q": "http://testserver/post/searchtest"}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["posts"]), 1)
        self.assertEqual(data["posts"][0]["post"]["id"], post.object_id)

    def test_search_with_type_filter_users(self):
        """Test search with type_=Users filter"""
        actor = ActorFactory(preferred_username="typefilteruser", reference__domain=self.domain)
        PersonFactory(reference=actor.reference)

        response = self.client.get(
            "/api/v3/search", data={"q": "@typefilteruser@testserver", "type_": "Users"}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["type_"], "Users")
        self.assertEqual(len(data["users"]), 1)

    def test_search_with_type_filter_communities(self):
        """Test search with type_=Communities filter"""
        community_ref = Reference.objects.create(
            uri="http://testserver/c/typefiltercommunity", domain=self.domain
        )

        now = timezone.now()
        ActorContext.make(
            reference=community_ref,
            type=ActorContext.Types.GROUP,
            preferred_username="typefiltercommunity",
            published=now,
            updated=now,
        )
        models.Community.objects.create(reference=community_ref)

        response = self.client.get(
            "/api/v3/search", data={"q": "!typefiltercommunity@testserver", "type_": "Communities"}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["type_"], "Communities")
        self.assertEqual(len(data["communities"]), 1)

    def test_search_remote_webfinger_triggers_lookup(self):
        """Test that searching for unknown remote actor triggers webfinger lookup"""
        # This should return empty results but trigger an async lookup
        response = self.client.get("/api/v3/search", data={"q": "@unknown@remote.example.com"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Should return empty results since the account doesn't exist yet
        self.assertEqual(data["users"], [])

    def test_search_remote_url_triggers_resolution(self):
        """Test that searching for unknown remote URL triggers resolution"""
        response = self.client.get(
            "/api/v3/search", data={"q": "https://remote.example.com/post/123"}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Should return empty results since the object doesn't exist yet
        self.assertEqual(data["posts"], [])

    def test_search_with_pagination(self):
        """Test search pagination parameters"""
        response = self.client.get("/api/v3/search", data={"q": "test", "page": 1, "limit": 5})

        self.assertEqual(response.status_code, 200)

    def test_search_invalid_type_returns_error(self):
        """Test that invalid type_ value returns error"""
        response = self.client.get("/api/v3/search", data={"q": "test", "type_": "InvalidType"})

        self.assertEqual(response.status_code, 400)

    def test_search_malformed_webfinger_returns_empty(self):
        """Test that malformed webfinger addresses return empty results"""
        response = self.client.get("/api/v3/search", data={"q": "@invalid"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["users"], [])

    def test_search_community_by_url(self):
        """Test searching for a community by direct URL"""
        community_ref = Reference.objects.create(
            uri="http://testserver/c/urlcommunity", domain=self.domain
        )

        now = timezone.now()
        ActorContext.make(
            reference=community_ref,
            type=ActorContext.Types.GROUP,
            preferred_username="urlcommunity",
            published=now,
            updated=now,
        )
        community = models.Community.objects.create(reference=community_ref)

        response = self.client.get(
            "/api/v3/search", data={"q": "http://testserver/c/urlcommunity"}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["communities"]), 1)
        self.assertEqual(data["communities"][0]["community"]["id"], community.object_id)

    def test_search_comment_by_url(self):
        """Test searching for a comment by direct URL"""
        comment = CommentFactory(
            reference__path="/comment/searchtest", reference__domain=self.domain
        )

        response = self.client.get(
            "/api/v3/search", data={"q": "http://testserver/comment/searchtest"}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["comments"]), 1)
        self.assertEqual(data["comments"][0]["comment"]["id"], comment.object_id)


@override_settings(
    FEDERATION={"DEFAULT_URL": "http://testserver", "FORCE_INSECURE_HTTP": True},
    ALLOWED_HOSTS=["testserver"],
)
class UserRegistrationTestCase(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        self.domain = DomainFactory(scheme="http", name="testserver", local=True)
        self.instance = InstanceFactory(domain=self.domain)
        self.site = SiteFactory(reference__domain=self.domain)

    def test_user_registration_creates_follow_collections(self):
        """Test that user registration creates following and followers collections"""
        payload = {
            "username": "testuser",
            "password": "testpass123",
            "password_verify": "testpass123",
            "email": "test@example.com",
        }

        response = self.client.post(
            "/api/v3/user/register", data=payload, format="json", headers={"Host": "testserver"}
        )
        self.assertEqual(response.status_code, 200)

        # Check that the user was created
        account = Identity.objects.get(
            actor__preferred_username="testuser", actor__reference__domain=self.domain
        )
        person = models.Person.objects.get(reference=account.actor.reference)

        # Check that following and followers collections exist
        actor = person.as2
        self.assertIsNotNone(actor.following)
        self.assertIsNotNone(actor.followers)

        # Check that the collections are actual CollectionContext objects
        following_collection = actor.following.get_by_context(CollectionContext)
        followers_collection = actor.followers.get_by_context(CollectionContext)

        self.assertIsNotNone(following_collection)
        self.assertIsNotNone(followers_collection)

        # Check that collections are empty initially
        self.assertEqual(following_collection.total_items, 0)
        self.assertEqual(followers_collection.total_items, 0)


@override_settings(
    FEDERATION={"DEFAULT_URL": "http://testserver", "FORCE_INSECURE_HTTP": True},
    ALLOWED_HOSTS=["testserver"],
)
class FederatedInstancesTestCase(TransactionTestCase):
    """Test cases for GET /api/v3/federated_instances"""

    def setUp(self):
        self.client = APIClient()
        self.local_domain = DomainFactory(scheme="http", name="testserver", local=True)
        self.local_instance = InstanceFactory(domain=self.local_domain)
        self.local_site = SiteFactory(reference__domain=self.local_domain)
        self.local_site_settings = models.LocalSite.objects.create(
            site=self.local_site, federation_enabled=True
        )

    def test_federated_instances_empty(self):
        """Test endpoint returns empty lists when no federation has occurred"""
        response = self.client.get("/api/v3/federated_instances")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("federated_instances", data)
        fed_instances = data["federated_instances"]

        self.assertEqual(len(fed_instances["linked"]), 0)
        self.assertEqual(len(fed_instances["allowed"]), 0)
        self.assertEqual(len(fed_instances["blocked"]), 0)

    def test_federated_instances_with_remote_sites(self):
        """Test endpoint returns remote federated instances"""
        # Create remote domains and sites
        remote_domain1 = DomainFactory(scheme="https", name="lemmy.example.com", local=False)
        InstanceFactory(domain=remote_domain1, software="lemmy", version="0.19.0")
        SiteFactory(reference__domain=remote_domain1)

        remote_domain2 = DomainFactory(scheme="https", name="mastodon.example.com", local=False)
        InstanceFactory(domain=remote_domain2, software="mastodon", version="4.2.0")
        SiteFactory(reference__domain=remote_domain2)

        response = self.client.get("/api/v3/federated_instances")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        fed_instances = data["federated_instances"]
        self.assertEqual(len(fed_instances["linked"]), 2)

        # Check that domains are included
        domains = [inst["domain"] for inst in fed_instances["linked"]]
        self.assertIn("lemmy.example.com", domains)
        self.assertIn("mastodon.example.com", domains)

        # Check that software/version are included
        for inst in fed_instances["linked"]:
            if inst["domain"] == "lemmy.example.com":
                self.assertEqual(inst["software"], "lemmy")
                self.assertEqual(inst["version"], "0.19.0")
            elif inst["domain"] == "mastodon.example.com":
                self.assertEqual(inst["software"], "mastodon")
                self.assertEqual(inst["version"], "4.2.0")

    def test_federated_instances_with_allowed_and_blocked(self):
        """Test endpoint returns allowed and blocked instances"""
        # Create remote sites
        allowed_domain = DomainFactory(scheme="https", name="allowed.example.com", local=False)
        SiteFactory(reference__domain=allowed_domain)

        blocked_domain = DomainFactory(scheme="https", name="blocked.example.com", local=False)
        SiteFactory(reference__domain=blocked_domain)

        # Add to allowed/blocked lists
        self.local_site.allowed_instances.add(allowed_domain)
        self.local_site.blocked_instances.add(blocked_domain)

        response = self.client.get("/api/v3/federated_instances")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        fed_instances = data["federated_instances"]

        # Check allowed
        self.assertEqual(len(fed_instances["allowed"]), 1)
        self.assertEqual(fed_instances["allowed"][0]["domain"], "allowed.example.com")

        # Check blocked
        self.assertEqual(len(fed_instances["blocked"]), 1)
        self.assertEqual(fed_instances["blocked"][0]["domain"], "blocked.example.com")

    def test_federated_instances_when_federation_disabled(self):
        """Test endpoint returns null when federation is disabled"""
        self.local_site_settings.federation_enabled = False
        self.local_site_settings.save()

        response = self.client.get("/api/v3/federated_instances")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIsNone(data["federated_instances"])

    def test_federated_instances_with_federation_state(self):
        """Test endpoint includes federation_state when tracking data exists"""
        # Create remote site with federation tracking data
        remote_domain = DomainFactory(scheme="https", name="tracked.example.com", local=False)
        remote_site = SiteFactory(reference__domain=remote_domain)

        # Set federation state data
        notification_id = uuid.uuid4()
        remote_site.last_successful_notification_id = notification_id
        remote_site.last_successful_published_time = timezone.now()
        remote_site.fail_count = 2
        remote_site.last_retry = timezone.now()
        remote_site.save()

        response = self.client.get("/api/v3/federated_instances")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        fed_instances = data["federated_instances"]
        tracked_inst = fed_instances["linked"][0]

        # Check federation_state is included
        self.assertIn("federation_state", tracked_inst)
        self.assertIsNotNone(tracked_inst["federation_state"])

        fed_state = tracked_inst["federation_state"]
        self.assertEqual(fed_state["instance_id"], remote_site.object_id)
        self.assertEqual(fed_state["fail_count"], 2)
        self.assertIsNotNone(fed_state["last_successful_published_time"])
        self.assertIsNotNone(fed_state["next_retry"])  # Calculated property


class AuthenticationTokenTestCase(BaseAuthenticatedViewTestCase):
    def test_list_logins_requires_auth(self):
        """Test that list_logins requires authentication"""
        models.LoginToken.objects.all().delete()
        response = self.client.get("/api/v3/user/list_logins")
        self.assertEqual(response.status_code, 401)  # Unauthorized/Forbidden without auth

    def test_list_logins_empty(self):
        """Test that a new user has no login tokens"""
        models.LoginToken.objects.all().delete()
        response = self.client.get("/api/v3/user/list_logins")
        self.assertEqual(response.status_code, 401)

    def test_list_logins_after_login(self):
        response = self.client.get("/api/v3/user/list_logins")
        self.assertEqual(response.status_code, 200)

        tokens = response.json()
        self.assertIsInstance(tokens, list)
        self.assertGreaterEqual(len(tokens), 1)

        # Check token structure
        login_token = tokens[0]
        self.assertIn("user_id", login_token)
        self.assertIn("published", login_token)
        self.assertIn("ip", login_token)
        self.assertIn("user_agent", login_token)

    def test_list_logins_includes_ip_and_user_agent(self):
        """Test that IP and user agent are captured"""
        models.LoginToken.objects.all().delete()
        login_token = models.LoginToken.make(identity=self.identity, user_agent="TestBrowser/1.0")

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login_token.token}")
        response = self.client.get("/api/v3/user/list_logins")
        self.assertEqual(response.status_code, 200)

        tokens = response.json()
        self.assertEqual(len(tokens), 1)
        our_token = tokens[0]
        self.assertEqual(our_token["user_agent"], "TestBrowser/1.0")

    def test_validate_auth_valid_token(self):
        """Test that valid token returns 200"""
        response = self.client.get("/api/v3/user/validate_auth")
        self.assertEqual(response.status_code, 200)

    def test_validate_auth_no_token(self):
        """Test that missing token returns 400"""
        models.LoginToken.objects.all().delete()
        response = self.client.get("/api/v3/user/validate_auth")
        self.assertEqual(response.status_code, 401)

    def test_validate_auth_invalid_token(self):
        """Test that invalid token returns 400"""
        self.client.credentials(HTTP_AUTHORIZATION="Bearer invalid_token_here")
        response = self.client.get("/api/v3/user/validate_auth")
        self.assertEqual(response.status_code, 401)  # JWT auth will reject first

    def test_validate_auth_blacklisted_token(self):
        # Logout (blacklists token)
        logout_response = self.client.post("/api/v3/user/logout")
        self.assertEqual(logout_response.status_code, 200)

        # Try to validate the blacklisted token
        response = self.client.get("/api/v3/user/validate_auth")
        self.assertEqual(response.status_code, 401)

    def test_logout_requires_auth(self):
        """Test that logout requires authentication"""
        models.LoginToken.objects.all().delete()
        response = self.client.post("/api/v3/user/logout")
        self.assertEqual(response.status_code, 401)  # Unauthorized/Forbidden without auth

    def test_logout_blacklists_token(self):
        """Test that logout invalidates the current token"""
        # Logout
        response = self.client.post("/api/v3/user/logout")
        self.assertEqual(response.status_code, 200)

        # Try to use the token again
        response = self.client.get("/api/v3/user/validate_auth")
        self.assertEqual(response.status_code, 401)

    def test_logout_token_cannot_be_reused(self):
        """Test that after logout, token is permanently invalid"""
        # Logout
        self.client.post("/api/v3/user/logout")

        # Try to make any authenticated request
        response = self.client.get("/api/v3/user/list_logins")
        self.assertEqual(response.status_code, 401)

    @freeze_time("1970-01-15 00:00:00")
    def test_multiple_concurrent_logins(self):
        """Test that user can have multiple active tokens"""
        models.LoginToken.objects.all().delete()
        with freeze_time("1970-01-01"):
            token1 = models.LoginToken.make(identity=self.identity)
        with freeze_time("1970-01-02"):
            token2 = models.LoginToken.make(identity=self.identity)

        self.assertNotEqual(token1, token2)

        # Both tokens should be valid
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token1.token}")
        response1 = self.client.get("/api/v3/user/validate_auth")
        self.assertEqual(response1.status_code, 200)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token2.token}")
        response2 = self.client.get("/api/v3/user/validate_auth")
        self.assertEqual(response2.status_code, 200)

        # List logins should show both
        response = self.client.get("/api/v3/user/list_logins")
        tokens = response.json()
        self.assertGreaterEqual(len(tokens), 2)

    @freeze_time("1970-01-01 12:34:56")
    def test_logout_only_affects_current_token(self):
        """Test that logging out one token doesn't affect others"""

        token1 = models.LoginToken.make(identity=self.identity)

        with freeze_time("1970-01-01 12:12:12"):
            token2 = models.LoginToken.make(identity=self.identity)

        # Logout token1
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token1.token}")
        self.client.post("/api/v3/user/logout")

        # token1 should be invalid
        response = self.client.get("/api/v3/user/validate_auth")
        self.assertEqual(response.status_code, 401)

        # token2 should still be valid
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token2.token}")
        response = self.client.get("/api/v3/user/validate_auth")
        self.assertEqual(response.status_code, 200)

    def test_list_logins_only_shows_active_tokens(self):
        """Test that blacklisted tokens don't appear in list_logins"""
        models.LoginToken.objects.all().delete()

        with freeze_time("1970-01-01 12:34:56"):
            token1 = models.LoginToken.make(identity=self.identity, user_agent="Web Browser")

        with freeze_time("1970-01-01 12:56:34"):
            token2 = models.LoginToken.make(identity=self.identity, user_agent="Mobile App")

        # Logout token1
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token1.token}")
        self.client.post("/api/v3/user/logout")

        # List logins with token2
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token2.token}")
        response = self.client.get("/api/v3/user/list_logins")
        tokens = response.json()

        self.assertEqual(len(tokens), 1)
