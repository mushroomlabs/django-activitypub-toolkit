from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, status
from rest_framework.decorators import api_view
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.views import APIView

from activitypub.core.models import (
    Activity,
    ActivityContext,
    ActorContext,
    Domain,
    FollowRequest,
    Identity,
    Reference,
)
from activitypub.core.tasks import resolve_reference, webfinger_lookup

from .. import filters, models, pagination, permissions, serializers
from ..exceptions import NoIdGiven, PersonNotFound


def get_site(request):
    hostname = request._request.META.get("HTTP_HOST")
    if not hostname:
        domain = Domain.get_default()
    else:
        scheme = Domain.SchemeTypes.HTTPS if request.is_secure() else Domain.SchemeTypes.HTTPS
        domain = Domain.objects.get(scheme=scheme, name=hostname)
    return models.LocalSite.objects.filter(site__reference__domain=domain).first()


class LemmyAPIView(APIView):
    def get_person(self):
        if not self.request.user.is_authenticated:
            return None

        try:
            identity = Identity.objects.select_related("actor").get(user=self.request.user)
            person, _ = models.Person.objects.get_or_create(reference=identity.actor.reference)
            return person
        except (Identity.DoesNotExist, Identity.MultipleObjectsReturned):
            return None


class LemmyListAPIView(generics.ListAPIView, LemmyAPIView):
    PAGE_SIZE = 50

    def list(self, request, *args, **kw):
        queryset = super().get_queryset()
        queryset = self.filter_queryset(queryset)

        paginated_queryset = self.paginate_queryset(queryset)

        serializer = self.get_serializer(paginated_queryset, many=True)
        return self.get_paginated_response(serializer.data)


class LemmyObjectAPIView(generics.RetrieveUpdateAPIView):
    model = None

    def get_object(self, *args, **kw):
        return get_object_or_404(self.model, object_id=self.kwargs["id"])


class LocalSiteView(generics.RetrieveUpdateAPIView):
    """
    Gets the site, and your user data

    GET: /api/v3/site
    """

    serializer_class = serializers.LocalSiteViewSerializer
    permission_classes = (permissions.IsSiteAdminOrReadOnly,)

    def get_object(self, *args, **kw):
        return get_site(self.request)

    def get(self, request, *args, **kw):
        site_serializer = self.get_serializer(instance=self.get_object())
        data = site_serializer.data

        if request.user.is_authenticated:
            user_profile, _ = models.UserProfile.objects.get_or_create(user=request.user)
            user_settings, _ = models.UserSettings.objects.get_or_create(user=request.user)
            local_user_serializer = serializers.LocalUserViewSerializer(instance=user_profile)
            user_profile_serializer = serializers.UserProfileSerializer(instance=user_profile)

            data.update(
                {
                    "my_user": {
                        "local_user_view": local_user_serializer.data,
                        "discussion_languages": [
                            lang.internal_id for lang in user_settings.languages.all()
                        ],
                        **user_profile_serializer.data,
                    }
                }
            )
        return Response(data)


class SiteBlockView(generics.CreateAPIView):
    """Block an instance"""

    serializer_class = serializers.LocalSiteBlockedUrlSerializer
    permission_classes = (permissions.IsSiteAdmin,)

    def get_object(self, *args, **kw):
        return get_site(self.request)


class UserRegistrationView(APIView):
    """Register a new user"""

    serializer_class = serializers.UserRegistrationSerializer

    def post(self, *args, **kw):
        serializer = self.serializer_class(
            data=self.request.data, context={"request": self.request}
        )
        if serializer.is_valid():
            result = serializer.save()
            return Response(result)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserLoginView(APIView):
    """
    Login a user
    """

    serializer_class = serializers.LoginSerializer

    def post(self, *args, **kw):
        serializer = self.serializer_class(
            data=self.request.data, context={"request": self.request, "view": self}
        )

        if serializer.is_valid():
            return Response(serializer.validated_data)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ResolveObjectView(LemmyAPIView):
    """
    Resolve a Lemmy query string (e.g., @user@domain, !community@domain, or URI) to an object.

    Returns existing resolved objects or validation error if not found.
    """

    def get(self, request):
        context = {"request": request, "view": self}
        serializer = serializers.ResolveObjectSerializer(
            data=request.query_params, context=context
        )
        if serializer.is_valid():
            return Response(serializer.data)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class SearchView(LemmyAPIView):
    """
    Search for content in Lemmy.

    GET /api/v3/search

    Supports:
    - Webfinger addresses: @user@domain, !community@domain (triggers async resolution)
    - Direct URLs: https://example.com/post/123
    - Plain text search: searches local database for matching posts, comments, communities, users
    """

    def get(self, request):
        context = {"request": request, "view": self}
        serializer = serializers.SearchSerializer(data=request.query_params, context=context)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        query = serializer.validated_data["q"].strip()
        search_type = serializer.validated_data.get("type_", serializers.SearchType.ALL)
        page = serializer.validated_data.get("page", 1)
        limit = serializer.validated_data.get("limit", 10)
        community_filter = serializer.validated_data.get("community")
        creator_filter = serializer.validated_data.get("creator_id")

        offset = (page - 1) * limit

        results = {
            "type_": search_type,
            "comments": [],
            "posts": [],
            "communities": [],
            "users": [],
        }

        # Check if it's a webfinger address (@user@domain or !community@domain)
        is_webfinger = query.startswith("@") or query.startswith("!")

        if is_webfinger:
            results = self._search_webfinger(query, search_type, results)
        elif query.startswith("http://") or query.startswith("https://"):
            results = self._search_url(query, search_type, results)
        else:
            results = self._search_text(
                query, search_type, results, offset, limit, community_filter, creator_filter
            )

        response_serializer = serializers.SearchResponseSerializer(results, context=context)
        return Response(response_serializer.data)

    def _search_webfinger(self, query, search_type, results):
        """Search for actors via webfinger address."""
        try:
            # Parse the webfinger address
            prefix = query[0]  # @ or !
            rest = query[1:]

            if "@" not in rest:
                return results

            username, domain_name = rest.rsplit("@", 1)

            # Check if account already exists locally
            actor = ActorContext.objects.filter(
                preferred_username=username, reference__domain__name=domain_name
            ).first()

            if actor is None:
                # Trigger async webfinger lookup
                webfinger_lookup.delay(f"{username}@{domain_name}")
                return results

            reference = actor.reference

            # Return person or community based on prefix and search type
            if prefix == "@":
                if search_type in (serializers.SearchType.ALL, serializers.SearchType.USERS):
                    person = models.Person.objects.filter(reference=reference).first()
                    if person:
                        results["users"] = [person]
            elif prefix == "!":
                if search_type in (serializers.SearchType.ALL, serializers.SearchType.COMMUNITIES):
                    community = models.Community.objects.filter(reference=reference).first()
                    if community:
                        results["communities"] = [community]

        except (ValueError, IndexError):
            pass

        return results

    def _search_url(self, query, search_type, results):
        """Search for objects by direct URL."""
        try:
            reference = Reference.objects.filter(uri=query).first()

            if reference is None:
                # Create reference and trigger async resolution
                reference = Reference.make(uri=query)
                resolve_reference(uri=query)
                return results

            # Look for matching objects
            if search_type in (serializers.SearchType.ALL, serializers.SearchType.POSTS):
                post = models.Post.objects.filter(reference=reference).first()
                if post:
                    results["posts"] = [post]
                    return results

            if search_type in (serializers.SearchType.ALL, serializers.SearchType.COMMENTS):
                comment = models.Comment.objects.filter(reference=reference).first()
                if comment:
                    results["comments"] = [comment]
                    return results

            if search_type in (serializers.SearchType.ALL, serializers.SearchType.COMMUNITIES):
                community = models.Community.objects.filter(reference=reference).first()
                if community:
                    results["communities"] = [community]
                    return results

            if search_type in (serializers.SearchType.ALL, serializers.SearchType.USERS):
                person = models.Person.objects.filter(reference=reference).first()
                if person:
                    results["users"] = [person]
                    return results

        except Exception:
            pass

        return results

    def _search_text(
        self, query, search_type, results, offset, limit, community_filter, creator_filter
    ):
        """Search local database for matching content using filter classes."""
        # Build filter params from the search query
        filter_params = {"q": query}
        if community_filter:
            filter_params["community"] = community_filter

        # Search posts by title
        if search_type in (serializers.SearchType.ALL, serializers.SearchType.POSTS):
            post_filter = filters.PostSearchFilter(
                data=filter_params,
                queryset=models.Post.objects.select_related("community", "postaggregates"),
            )
            results["posts"] = list(post_filter.qs[offset : offset + limit])

        # Search comments - content is stored in source ObjectContext, not directly queryable
        # Return empty for now - a proper implementation would require raw SQL or denormalization
        if search_type in (serializers.SearchType.ALL, serializers.SearchType.COMMENTS):
            results["comments"] = []

        # Search communities by name, summary, or username
        if search_type in (serializers.SearchType.ALL, serializers.SearchType.COMMUNITIES):
            community_filter_instance = filters.CommunitySearchFilter(
                data=filter_params,
                queryset=models.Community.objects.select_related("communityaggregates"),
            )
            results["communities"] = list(community_filter_instance.qs[offset : offset + limit])

        # Search users by name or username
        if search_type in (serializers.SearchType.ALL, serializers.SearchType.USERS):
            person_filter = filters.PersonSearchFilter(
                data=filter_params,
                queryset=models.Person.objects.all(),
            )
            results["users"] = list(person_filter.qs[offset : offset + limit])

        return results


class CreatePostView(generics.CreateAPIView, generics.RetrieveAPIView):
    """
    Create a new post.

    POST /api/v3/post
    """

    permission_classes = (IsAuthenticatedOrReadOnly,)

    def get_object(self):
        post_id = self.request.GET.get("id")
        return post_id and get_object_or_404(models.Post, object_id=post_id)

    def get(self, request):
        post = self.get_object()
        context = {"request": request, "view": self}
        serializer = serializers.PostViewSerializer(instance=post, context=context)
        return Response({"post_view": serializer.data})

    def post(self, request):
        context = {"request": request, "view": self}
        serializer = serializers.CreatePostSerializer(data=request.data, context=context)
        if serializer.is_valid():
            post = serializer.save()
            response_serializer = serializers.PostResponseSerializer(
                {"post_view": post}, context=context
            )
            return Response(response_serializer.data)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CreateCommentView(APIView):
    """
    Create a new comment.

    POST /api/v3/comment

    Required fields:
    - content: Comment content
    - post_id: Post to comment on
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = serializers.CreateCommentSerializer(
            data=request.data, context={"request": request}
        )
        if serializer.is_valid():
            comment = serializer.save()

            response_serializer = serializers.CommentResponseSerializer(
                {
                    "comment_view": comment,
                    "recipient_ids": [],
                }
            )
            return Response(response_serializer.data)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class DeleteCommentView(LemmyAPIView):
    """
    POST /api/v3/comment/delete

    Delete a comment.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = serializers.DeleteCommentSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        comment = serializer.validated_data["comment"]
        deleted = serializer.validated_data["deleted"]

        if comment.creator != self.get_person():
            return Response(
                {"error": "Only the creator can delete this comment"},
                status=status.HTTP_403_FORBIDDEN,
            )

        comment.deleted = deleted
        comment.save()

        response_serializer = serializers.CommentResponseSerializer(
            {"comment_view": comment, "recipient_ids": []}
        )
        return Response(response_serializer.data)


class RemoveCommentView(APIView):
    """
    POST /api/v3/comment/remove

    A moderator remove for a comment.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = serializers.RemoveCommentSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        comment = serializer.validated_data["comment"]
        removed = serializer.validated_data["removed"]

        comment.removed = removed
        comment.save()

        response_serializer = serializers.CommentResponseSerializer(
            {"comment_view": comment, "recipient_ids": []}
        )
        return Response(response_serializer.data)


class CommentLikeView(LemmyAPIView):
    """
    POST /api/v3/comment/like

    Like / vote on a comment.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = serializers.CommentLikeSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        person = self.get_person()

        if not person:
            return Response("No identified actor", status=status.HTTP_400_BAD_REQUEST)

        comment = serializer.validated_data["comment"]
        score = serializer.validated_data["score"]

        if score == 1:
            person.liked_comments.add(comment)
        elif score == -1:
            person.liked_comments.remove(comment)
        elif score == 0:
            person.liked_comments.remove(comment)

        response_serializer = serializers.CommentResponseSerializer(
            {"comment_view": comment, "recipient_ids": []}
        )
        return Response(response_serializer.data)


class SaveCommentView(LemmyAPIView):
    """
    PUT /api/v3/comment/save

    Save a comment.
    """

    permission_classes = (IsAuthenticated,)

    def put(self, request):
        serializer = serializers.SaveCommentSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        comment = serializer.validated_data["comment"]
        save = serializer.validated_data["save"]
        profile = self.request.user.lemmy_profile

        if save:
            profile.saved_comments.add(comment)
        else:
            profile.saved_comments.remove(comment)

        response_serializer = serializers.CommentResponseSerializer(
            {"comment_view": comment, "recipient_ids": []}
        )
        return Response(response_serializer.data)


class ListCommentsView(LemmyListAPIView):
    """
    GET /api/v3/comment/list

    Get / fetch comments, with various filters.
    """

    queryset = models.Comment.objects.all()
    serializer_class = serializers.CommentViewSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = filters.CommentFilter
    pagination_class = pagination.CommentPagination

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.select_related("post").order_by("-id")


class ListPostsView(LemmyListAPIView):
    """
    GET /api/v3/post/list

    Get / fetch posts, with various filters.
    """

    queryset = models.Post.objects.all()
    serializer_class = serializers.PostViewSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = filters.PostFilter
    pagination_class = pagination.PostPagination

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.select_related("community", "postaggregates")


class PostLikeView(LemmyAPIView):
    """
    POST /api/v3/post/like

    Like / vote on a post.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = serializers.PostLikeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        person = self.get_person()

        post = serializer.validated_data["post"]
        score = serializer.validated_data["score"]

        if score == 1:
            person.liked_posts.add(post)
        elif score == -1:
            person.liked_posts.remove(post)
        elif score == 0:
            person.liked_posts.remove(post)

        response_serializer = serializers.PostResponseSerializer({"post_view": post})
        return Response(response_serializer.data)


class SavePostView(APIView):
    """
    PUT /api/v3/post/save

    Save a post.
    """

    permission_classes = (IsAuthenticated,)

    def put(self, request):
        serializer = serializers.SavePostSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        post = serializer.validated_data["post"]
        save = serializer.validated_data["save"]
        profile = request.user.lemmy_profile

        if save:
            profile.saved_posts.add(post)
        else:
            profile.saved_posts.remove(post)

        response_serializer = serializers.PostResponseSerializer({"post_view": post})
        return Response(response_serializer.data)


class DeletePostView(APIView):
    """
    POST /api/v3/post/delete

    Delete a post.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = serializers.DeletePostSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        post = serializer.validated_data["post"]
        deleted = serializer.validated_data["deleted"]
        profile = request.user.lemmy_profile

        if post.creator != profile.person:
            return Response(
                {"error": "Only the creator can delete this post"},
                status=status.HTTP_403_FORBIDDEN,
            )

        post.deleted = deleted
        post.save()

        response_serializer = serializers.PostResponseSerializer({"post_view": post})
        return Response(response_serializer.data)


class LockPostView(APIView):
    """
    POST /api/v3/post/lock

    A moderator can lock a post ( IE disable new comments ).
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = serializers.LockPostSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        post = serializer.validated_data["post"]
        locked = serializer.validated_data["locked"]

        lemmy_context = models.LemmyContextModel.objects.get(reference=post.reference)
        lemmy_context.locked = locked
        lemmy_context.save()

        response_serializer = serializers.PostResponseSerializer({"post_view": post})
        return Response(response_serializer.data)


class FeaturePostView(APIView):
    """
    POST /api/v3/post/feature

    A moderator can feature a community post ( IE stick it to the top of a community ).
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = serializers.FeaturePostSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        post = serializer.validated_data["post"]
        featured = serializer.validated_data["featured"]
        feature_type = serializer.validated_data["feature_type"]

        if feature_type == "Community":
            post.featured_community = featured
        elif feature_type == "Local":
            post.featured_local = featured

        post.save()

        response_serializer = serializers.PostResponseSerializer({"post_view": post})
        return Response(response_serializer.data)


class MarkPostAsReadView(APIView):
    """
    POST /api/v3/post/mark_as_read

    Mark a post as read.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = serializers.MarkPostAsReadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        post_ids = serializer.validated_data["post_ids"]
        read = serializer.validated_data["read"]
        profile = request.user.lemmy_profile

        posts = models.Post.objects.filter(object_id__in=post_ids)

        if read:
            profile.read_posts.add(*posts)
        else:
            profile.read_posts.remove(*posts)

        return Response({"success": True})


class RemovePostView(APIView):
    """
    POST /api/v3/post/remove

    A moderator remove for a post.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = serializers.RemovePostSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        post = serializer.validated_data["post"]
        removed = serializer.validated_data["removed"]

        post.removed = removed
        post.save()

        response_serializer = serializers.PostResponseSerializer({"post_view": post})
        return Response(response_serializer.data)


class HidePostView(APIView):
    """
    POST /api/v3/post/hide

    Hide a post from list views.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = serializers.HidePostSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        post_ids = serializer.validated_data["post_ids"]
        hide = serializer.validated_data["hide"]
        profile = request.user.lemmy_profile

        posts = models.Post.objects.filter(object_id__in=post_ids)

        if hide:
            profile.hidden_posts.add(*posts)
        else:
            profile.hidden_posts.remove(*posts)

        return Response({"success": True})


# Report views
class CreatePostReportView(LemmyAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = serializers.CreatePostReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reporter = self.get_person()

        post = get_object_or_404(models.Post, object_id=serializer.validated_data["post_id"])

        # Create Flag activity
        flag_ref = ActivityContext.generate_reference(domain=reporter.reference.domain)
        ActivityContext.make(
            reference=flag_ref,
            type=ActivityContext.Types.FLAG,
            actor=reporter.reference,
            object=post.reference,
            content=serializer.validated_data["reason"],
            published=timezone.now(),
        )

        post_creator = post.creator if post else None
        community = post.community if post else None

        report = models.Report.objects.create(reference=flag_ref)

        post_report_view_data = {
            "post_report": report,
            "post": post,
            "community": community,
            "creator": reporter,
            "post_creator": post_creator,
            "creator_banned_from_community": False,  # TODO: Implement community ban check
            "creator_is_moderator": False,  # TODO: Implement moderator check
            "creator_is_admin": reporter.is_admin if reporter and reporter.site else False,
            "subscribed": False,  # TODO: Implement subscription check
            "saved": False,  # TODO: Implement saved check
            "read": False,  # TODO: Implement read check
            "hidden": False,  # TODO: Implement hidden check
            "creator_blocked": False,  # TODO: Implement block check
            "my_vote": None,  # TODO: Implement vote check
            "unread_comments": 0,  # TODO: Implement unread comments count
            "counts": serializers.PostAggregatesSerializer(post.postaggregates).data
            if post and hasattr(post, "postaggregates")
            else None,
            "resolver": reporter,
        }

        response_serializer = serializers.PostReportResponseSerializer(
            {"post_report_view": post_report_view_data}
        )

        return Response(response_serializer.data)


class ResolvePostReportView(LemmyAPIView):
    permission_classes = [permissions.CanManageReports]

    def put(self, request):
        serializer = serializers.ResolvePostReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        resolver = self.get_person()

        report = get_object_or_404(models.Report, object_id=serializer.validated_data["report_id"])

        if serializer.validated_data["resolved"]:
            report.resolved_by = resolver.reference
            report.resolved_on = timezone.now()
        else:
            report.resolved_by = None
            report.resolved_on = None
        report.save()

        flag_activity = report.reference.get_by_context(ActivityContext)

        reporter_ref = flag_activity.actor
        reporter = models.Person.objects.filter(reference=reporter_ref).first()

        post_ref = flag_activity.object
        post = models.Post.objects.filter(reference=post_ref).first()

        post_creator = post.creator if post else None
        community = post.community if post else None

        post_report_view_data = {
            "post_report": report,
            "post": post,
            "community": community,
            "creator": reporter,
            "post_creator": post_creator,
            "creator_banned_from_community": False,  # TODO: Implement community ban check
            "creator_is_moderator": False,  # TODO: Implement moderator check
            "creator_is_admin": reporter.is_admin if reporter and reporter.site else False,
            "subscribed": False,  # TODO: Implement subscription check
            "saved": False,  # TODO: Implement saved check
            "read": False,  # TODO: Implement read check
            "hidden": False,  # TODO: Implement hidden check
            "creator_blocked": False,  # TODO: Implement block check
            "my_vote": None,  # TODO: Implement vote check
            "unread_comments": 0,  # TODO: Implement unread comments count
            "counts": serializers.PostAggregatesSerializer(post.postaggregates).data
            if post and hasattr(post, "postaggregates")
            else None,
            "resolver": resolver,
        }

        response_serializer = serializers.PostReportResponseSerializer(
            {"post_report_view": post_report_view_data}
        )

        return Response(response_serializer.data)


class ListPostReportsView(APIView):
    permission_classes = [permissions.CanManageReports]

    def get(self, request):
        serializer = serializers.ListPostReportsSerializer(data=request.GET)
        serializer.is_valid(raise_exception=True)

        # TODO: Check if user is moderator/admin

        queryset = models.Report.objects.all()

        # Filter by unresolved only
        if serializer.validated_data.get("unresolved_only", False):
            queryset = queryset.filter(resolved_by=False)

        # Filter by community
        if serializer.validated_data.get("community"):
            community = get_object_or_404(
                models.Community, object_id=serializer.validated_data["community"]
            )
            # TODO: Filter reports by community - this requires joining through the Flag activity

        # Filter by post
        if serializer.validated_data.get("post"):
            post = get_object_or_404(models.Post, object_id=serializer.validated_data["post"])
            # TODO: Filter reports by post - this requires joining through the Flag activity

        # Pagination
        page = serializer.validated_data.get("page", 1)
        limit = serializer.validated_data.get("limit", 10)
        offset = (page - 1) * limit
        queryset = queryset[offset : offset + limit]

        # Build response
        reports_data = []
        for report in queryset:
            flag_activity = report.reference.get_by_context(ActivityContext)
            reporter_ref = flag_activity.actor
            reporter = models.Person.objects.filter(reference=reporter_ref).first()

            post_ref = flag_activity.object
            post = models.Post.objects.filter(reference=post_ref).first()

            post_creator = post.creator if post else None
            community = post.community if post else None

            resolver_ref = report.resolved_by
            resolver = (
                resolver_ref and models.Person.objects.filter(reference=resolver_ref).first()
            )

            post_report_view_data = {
                "post_report": report,
                "post": post,
                "community": community,
                "creator": reporter,
                "post_creator": post_creator,
                "creator_banned_from_community": False,  # TODO: Implement community ban check
                "creator_is_moderator": False,  # TODO: Implement moderator check
                "creator_is_admin": reporter.is_admin if reporter and reporter.site else False,
                "subscribed": False,  # TODO: Implement subscription check
                "saved": False,  # TODO: Implement saved check
                "read": False,  # TODO: Implement read check
                "hidden": False,  # TODO: Implement hidden check
                "creator_blocked": False,  # TODO: Implement block check
                "my_vote": None,  # TODO: Implement vote check
                "unread_comments": 0,  # TODO: Implement unread comments count
                "counts": serializers.PostAggregatesSerializer(post.postaggregates).data
                if post and hasattr(post, "postaggregates")
                else None,
                "resolver": resolver,
            }
            reports_data.append(post_report_view_data)

        response_serializer = serializers.ListPostReportsResponseSerializer(
            {"post_reports": reports_data}
        )

        return Response(response_serializer.data)


class CreateCommentReportView(LemmyAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = serializers.CreateCommentReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        comment = get_object_or_404(
            models.Comment, object_id=serializer.validated_data["comment_id"]
        )
        reporter = self.get_person()

        flag_ref = ActivityContext.generate_reference(domain=reporter.reference.domain)
        ActivityContext.make(
            reference=flag_ref,
            type=ActivityContext.Types.FLAG,
            actor=reporter.reference,
            object=comment.reference,
            content=serializer.validated_data["reason"],
            published=timezone.now(),
        )

        report = models.Report.objects.create(reference=flag_ref)

        comment_report_view_data = {
            "comment_report": report,
            "comment": comment.comment_data,
            "post": comment.comment_data.post,
            "community": comment.comment_data.post.post_data.community,
            "creator": reporter,
            "comment_creator": comment.comment_data.creator,
            "creator_banned_from_community": False,
            "creator_is_moderator": False,
            "creator_is_admin": reporter.is_admin if reporter and reporter.site else False,
            "creator_blocked": False,
            "subscribed": "NotSubscribed",
            "saved": False,
            "my_vote": None,
            "counts": serializers.CommentAggregatesSerializer(
                comment.comment_data.commentaggregates
            ).data,
            "resolver": None,
        }

        response_serializer = serializers.CommentReportResponseSerializer(
            {"comment_report_view": comment_report_view_data}
        )

        return Response(response_serializer.data)


class ResolveCommentReportView(LemmyAPIView):
    permission_classes = [permissions.CanManageReports]

    def put(self, request):
        serializer = serializers.ResolveCommentReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        report = get_object_or_404(models.Report, object_id=serializer.validated_data["report_id"])
        resolved = serializer.validated_data["resolved"]

        resolver = self.get_person()

        if resolved:
            report.resolved_by = resolver.reference
            report.resolved_on = timezone.now()
        else:
            report.resolved_by = None
            report.resolved_on = None
        report.save()

        flag_activity = report.reference.get_by_context(ActivityContext)
        reporter_ref = flag_activity.actor
        reporter = models.Person.objects.filter(reference=reporter_ref).first()

        comment_ref = flag_activity.object
        comment = models.Comment.objects.filter(reference=comment_ref).first()

        comment_creator = comment.creator if comment else None
        post = comment and comment.post and getattr(comment.post, "post_data", None)
        community = post.community if post else None

        comment_report_view_data = {
            "comment_report": report,
            "comment": comment,
            "post": post,
            "community": community,
            "creator": reporter,
            "comment_creator": comment_creator,
            "creator_banned_from_community": False,
            "creator_is_moderator": False,
            "creator_is_admin": reporter.is_admin if reporter and reporter.site else False,
            "creator_blocked": False,
            "subscribed": "NotSubscribed",
            "saved": False,
            "my_vote": None,
            "counts": serializers.CommentAggregatesSerializer(comment.commentaggregates).data
            if comment and hasattr(comment, "commentaggregates")
            else None,
            "resolver": resolver,
        }

        response_serializer = serializers.CommentReportResponseSerializer(
            {"comment_report_view": comment_report_view_data}
        )

        return Response(response_serializer.data)


class ListCommentReportsView(APIView):
    permission_classes = [permissions.CanManageReports]

    def get(self, request):
        serializer = serializers.ListCommentReportsSerializer(data=request.GET)
        serializer.is_valid(raise_exception=True)

        queryset = models.Report.objects.all()

        if serializer.validated_data.get("unresolved_only", False):
            queryset = queryset.filter(resolved_by=None)

        page = serializer.validated_data.get("page", 1)
        limit = serializer.validated_data.get("limit", 10)
        offset = (page - 1) * limit
        queryset = queryset[offset : offset + limit]

        reports_data = []
        for report in queryset:
            flag_activity = report.reference.get_by_context(ActivityContext)
            reporter_ref = flag_activity.actor
            reporter = models.Person.objects.filter(reference=reporter_ref).first()

            comment_ref = flag_activity.object
            comment = models.Comment.objects.filter(reference=comment_ref).first()

            if not comment:
                continue

            comment_creator = comment.creator if comment else None
            post = (
                comment
                and comment.post
                and models.Post.objects.filter(reference=comment.post.reference).first()
            )
            community = (
                post
                and post.community
                and models.Community.objects.filter(reference=post.community.reference).first()
            )

            resolver = (
                report.resolved_by
                and models.Person.objects.filter(reference=report.resolved_by).first()
            )

            comment_report_view_data = {
                "comment_report": report,
                "comment": comment,
                "post": post,
                "community": community,
                "creator": reporter,
                "comment_creator": comment_creator,
                "creator_banned_from_community": False,
                "creator_is_moderator": False,
                "creator_is_admin": reporter.is_admin if reporter and reporter.site else False,
                "creator_blocked": False,
                "subscribed": "NotSubscribed",
                "saved": False,
                "my_vote": None,
                "counts": serializers.CommentAggregatesSerializer(comment.commentaggregates).data
                if comment and hasattr(comment, "commentaggregates")
                else None,
                "resolver": resolver,
            }
            reports_data.append(comment_report_view_data)

        response_serializer = serializers.ListCommentReportsResponseSerializer(
            {"comment_reports": reports_data}
        )

        return Response(response_serializer.data)


# Site metadata view
class GetSiteMetadataView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # This endpoint is not implemented due to architectural concerns
        # It would require background processing and caching for proper implementation
        return Response(
            {"error": "Service temporarily unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


# Like list view (admin only)
class ListPostLikesView(APIView):
    permission_classes = [permissions.IsSiteAdmin]

    def get(self, request):
        serializer = serializers.ListPostLikesSerializer(data=request.GET)
        serializer.is_valid(raise_exception=True)

        post_id = serializer.validated_data["post"]
        post = get_object_or_404(models.Post, id=post_id)

        # Get all users who liked this post
        liked_users = post.liked_by.all()

        # Build vote data for each liker
        likes_data = []
        for user in liked_users:
            vote_data = {
                "creator": user,
                "score": 1,  # Likes are +1
            }
            likes_data.append(vote_data)

        response_serializer = serializers.ListPostLikesResponseSerializer(
            {"post_likes": likes_data}
        )

        return Response(response_serializer.data)


class MarkCommentAsReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = serializers.MarkCommentAsReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        comment = get_object_or_404(
            models.Comment, object_id=serializer.validated_data["comment_reply_id"]
        )
        read = serializer.validated_data["read"]
        profile = request.user.lemmy_profile

        if read:
            profile.read_comments.add(comment)
        else:
            profile.read_comments.remove(comment)

        response_serializer = serializers.CommentReplyResponseSerializer(
            {"comment_reply_view": comment}
        )
        return Response(response_serializer.data)


class DistinguishCommentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = serializers.DistinguishCommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        comment = serializer.validated_data["comment"]
        distinguished = serializer.validated_data["distinguished"]

        lemmy_ctx = comment.lemmy
        lemmy_ctx.distinguished = distinguished
        lemmy_ctx.save()

        response_serializer = serializers.CommentResponseSerializer(
            {"comment_view": comment, "recipient_ids": []}
        )
        return Response(response_serializer.data)


class ListCommentLikesView(LemmyAPIView):
    permission_classes = [permissions.IsSiteAdmin]

    def get(self, request):
        serializer = serializers.ListCommentLikesSerializer(data=request.GET)
        serializer.is_valid(raise_exception=True)

        comment_id = serializer.validated_data["comment_id"]
        comment = get_object_or_404(models.Comment, object_id=comment_id)

        liked_users = comment.liked_by.all()

        likes_data = []
        for user in liked_users:
            vote_data = {
                "creator": user,
                "score": 1,
            }
            likes_data.append(vote_data)

        response_serializer = serializers.ListCommentLikesResponseSerializer(
            {"comment_likes": likes_data}
        )

        return Response(response_serializer.data)


class PurgeCommentView(APIView):
    permission_classes = [permissions.IsSiteAdmin]

    def post(self, request):
        serializer = serializers.PurgeCommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        comment = serializer.validated_data["comment"]
        comment.delete()

        return Response({"success": True})


# Community views
class CommunityView(generics.RetrieveAPIView, generics.CreateAPIView, LemmyAPIView):
    """
    GET /api/v3/community

    Get / fetch a community by id or name.
    """

    def get_object(self, *args, **kw):
        data = self.request.query_params
        if "id" in data:
            return models.Community.objects.filter(object_id=data["id"]).first()

        elif "name" in data:
            name = data["name"]
            if "@" in name:
                username, domain_name = name.rsplit("@", 1)
                actor = ActorContext.objects.filter(
                    preferred_username=username, reference__domain__name=domain_name
                ).first()
                return models.Community.objects.filter(reference=actor.reference).first()
            else:
                actor = ActorContext.objects.filter(
                    reference__in=models.Community.objects.values_list("reference", flat=True),
                    preferred_username=name,
                ).first()

            if actor is None:
                webfinger_lookup.delay(name)
                return None

            return models.Community.objects.filter(reference=actor.reference).first()
        else:
            return None

    def get(self, request):
        if "id" not in request.query_params and "name" not in request.query_params:
            return Response({"error": "no_id_given"}, status=status.HTTP_400_BAD_REQUEST)

        community = self.get_object()
        if not community:
            return Response({"error": "couldnt_find_community"}, status=status.HTTP_404_NOT_FOUND)

        serializer = serializers.GetCommunityResponseSerializer(
            instance=community, context={"request": request, "view": self}
        )
        return Response(serializer.data)

    def post(self, request):
        serializer = serializers.CreateCommunitySerializer(
            data=request.data, context={"request": request, "view": self}
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        community = serializer.save()
        response_serializer = serializers.GetCommunityResponseSerializer(
            community, context={"request": request, "view": self}
        )
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class ListCommunitiesView(LemmyListAPIView):
    """
    GET /api/v3/community/list

    List communities, with various filters.
    """

    queryset = models.Community.objects.all()
    serializer_class = serializers.CommunityViewSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = filters.CommunityFilter
    pagination_class = pagination.CommunityPagination

    def get_queryset(self, *args, **kw):
        queryset = super().get_queryset(*args, **kw)
        return queryset.select_related("communityaggregates")


class FollowCommunityView(LemmyAPIView):
    """
    POST /api/v3/community/follow

    Follow / subscribe to a community.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = serializers.FollowCommunitySerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        community = serializer.validated_data["community"]
        follow = serializer.validated_data["follow"]

        person = self.get_person()

        if not person:
            return Response({"error": "Could not find person"}, status=status.HTTP_400_BAD_REQUEST)

        domain = person.reference.domain

        if follow:
            FollowRequest.objects.create(
                follower=person.reference,
                followed=community.reference,
                activity=Activity.generate_reference(domain=domain),
            )
            person.subscribed_communities.add(community)
        else:
            person.subscribed_communities.remove(community)
            try:
                follow_request = FollowRequest.finalized.get(
                    follower=person.reference, followed=community.reference
                )
                follow_ref = follow_request.activity
                undo_ref = Activity.generate_reference(domain)
                undo_activity = Activity.make(
                    reference=undo_ref,
                    type=ActivityContext.Types.UNDO,
                    actor=person.reference,
                    object=follow_ref,
                    published=timezone.now(),
                )
                undo_activity.to.add(community.reference)
                undo_activity.do()
            except FollowRequest.DoesNotExist:
                pass

        response_serializer = serializers.CommunityViewSerializer(
            community, context={"request": request, "view": self}
        )
        return Response({"community_view": response_serializer.data})


class BlockCommunityView(LemmyAPIView):
    """
    POST /api/v3/community/block

    Block a community.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        context = {"request": request, "view": self}
        serializer = serializers.BlockCommunitySerializer(data=request.data, context=context)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        person = self.get_person()

        if not person:
            return Response("could not identify actor", status=status.HTTP_400_BAD_REQUEST)

        community = serializer.validated_data["community"]
        block = serializer.validated_data["block"]

        if block:
            person.blocked_communities.add(community)
        else:
            person.blocked_communities.remove(community)

        response_data = {"community_view": community, "blocked": block}
        response_serializer = serializers.BlockCommunityResponseSerializer(
            response_data, context=context
        )
        return Response(response_serializer.data)


class GetPersonDetailsView(APIView):
    """
    GET /api/v3/user

    Get the details for a person.
    """

    def get(self, request):
        serializer = serializers.GetPersonDetailsSerializer(data=request.query_params)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        # Validate that either person_id or username is provided
        if not data.get("person_id") and not data.get("username"):
            raise NoIdGiven()

        # Look up person
        person = self._get_person(data)
        if not person:
            raise PersonNotFound()

        # Get person's home site
        site = person.site

        # Get pagination params
        page = data.get("page", 1)
        limit = data.get("limit", 10)
        offset = (page - 1) * limit

        # Get posts by this person (filtered/sorted/paginated)
        posts = self._get_posts(person, data, request, offset, limit)

        # Get comments by this person (filtered/sorted/paginated)
        comments = self._get_comments(person, data, request, offset, limit)

        # Get communities where person is moderator
        moderates = self._get_moderated_communities(person)

        # Build response
        response_data = {
            "person_view": person,
            "site": site,
            "posts": posts,
            "comments": comments,
            "moderates": moderates,
        }

        response_serializer = serializers.GetPersonDetailsResponseSerializer(
            response_data, context={"request": request}
        )
        return Response(response_serializer.data)

    def _get_person(self, data):
        """Look up person by ID or username (supports user@domain format)"""
        if data.get("person_id"):
            return models.Person.objects.filter(object_id=data["person_id"]).first()

        username = data.get("username", "").strip()
        if not username:
            return None

        actor = None

        # Handle federated format: user@domain
        if "@" in username:
            parts = username.rsplit("@", 1)
            if len(parts) == 2:
                uname, domain_name = parts
                actor = ActorContext.objects.filter(
                    preferred_username=uname, reference__domain__name=domain_name
                ).first()
        else:
            actor = ActorContext.objects.filter(
                preferred_username=username, reference__domain__local=True
            ).first()

        return actor and models.Person.objects.filter(reference=actor.reference).first()

    def _get_posts(self, person, params, request, offset, limit):
        # Find posts where attributed_to includes this person
        posts = models.Post.objects.filter(reference__in=person.as2.attributed_to.all())

        # Apply saved_only filter (only if viewing own profile)
        if params.get("saved_only"):
            viewing_profile = request.user.lemmy_profile
            if viewing_profile and viewing_profile.person == person:
                posts = posts.filter(saved_by=viewing_profile)
            else:
                posts = posts.none()

        # Apply community filter
        if params.get("community"):
            posts = posts.filter(community__object_id=params["community"])

        # Apply sorting
        sort = params.get("sort", "New")
        posts = self._apply_sort(posts, sort, "post")

        # Apply pagination
        return list(posts[offset : offset + limit])

    def _get_comments(self, person, params, request, offset, limit):
        # Find comments where attributed_to includes this person
        comments = models.Comment.objects.filter(reference__in=person.as2.attributed_to.all())

        # Apply saved_only filter (only if viewing own profile)
        if params.get("saved_only"):
            viewing_profile = request.user.lemmy_profile
            if viewing_profile and viewing_profile.person == person:
                comments = comments.filter(saved_by=viewing_profile)
            else:
                comments = comments.none()

        # Apply community filter
        if params.get("community"):
            comments = comments.filter(post__post_data__community__object_id=params["community"])

        # Apply sorting
        sort = params.get("sort", "New")
        comments = self._apply_sort(comments, sort, "comment")

        # Apply pagination
        return list(comments[offset : offset + limit])

    def _apply_sort(self, queryset, sort, content_type):
        """Apply sorting to queryset"""
        if content_type == "post":
            order_map = {
                "New": "-postaggregates__published",
                "Old": "postaggregates__published",
                "Hot": "-postaggregates__hot_rank",
                "TopAll": "-postaggregates__score",
            }
            default = "-postaggregates__published"
        else:  # comment
            order_map = {
                "New": "-commentaggregates__published",
                "Old": "commentaggregates__published",
                "Hot": "-commentaggregates__hot_rank",
                "TopAll": "-commentaggregates__score",
            }
            default = "-commentaggregates__published"

        order_field = order_map.get(sort, default)
        return queryset.order_by(order_field)

    def _get_moderated_communities(self, person):
        """Get communities where this person is a moderator"""

        communities = models.Community.objects.filter(
            reference__activitypub_lemmy_adapter_lemmycontextmodel_context__moderators=person.reference
        )

        return [{"community": community, "moderator": person} for community in communities]


@api_view(["GET"])
def echo(request):
    return Response(
        {
            "method": request.method,
            "path": request.path,
            "qs": request.GET,
            "payload": request.POST,
        }
    )


@api_view(["GET"])
def unread_count(request):
    return Response(
        {
            "replies": 0,
            "mentions": 0,
            "private_messages": 0,
        }
    )


class GetFederatedInstancesView(APIView):
    """
    GET /api/v3/federated_instances

    Returns instances this server federates with, organized by:
    - linked: All instances we've exchanged ActivityPub messages with
    - allowed: Explicitly allowed instances (if using allowlist)
    - blocked: Explicitly blocked instances
    """

    def get(self, request):
        local_site = get_site(request)

        # If federation is disabled, return null
        if not local_site or not local_site.federation_enabled:
            return Response({"federated_instances": None})

        site = local_site.site

        # Get explicitly allowed/blocked domains from the local site
        allowed_domains = site.allowed_instances.all()
        blocked_domains = site.blocked_instances.all()

        # Get all remote federated instances
        linked_sites = (
            models.Site.objects.filter(reference__domain__local=False)
            .select_related("reference__domain")
            .prefetch_related("reference__domain__instance")
        )

        # Filter sites by allowed/blocked domains
        allowed_sites = linked_sites.filter(reference__domain__in=allowed_domains)
        blocked_sites = linked_sites.filter(reference__domain__in=blocked_domains)

        return Response(
            {
                "federated_instances": {
                    "linked": serializers.InstanceWithFederationStateSerializer(
                        linked_sites, many=True
                    ).data,
                    "allowed": serializers.InstanceWithFederationStateSerializer(
                        allowed_sites, many=True
                    ).data,
                    "blocked": serializers.InstanceWithFederationStateSerializer(
                        blocked_sites, many=True
                    ).data,
                }
            }
        )


class ListLoginsView(generics.ListAPIView):
    """
    GET /api/v3/user/list_logins

    Returns list of active login tokens for the authenticated user.
    """

    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.LoginTokenSerializer

    def get_queryset(self, *args, **kw):
        return models.LoginToken.objects.filter(user=self.request.user)


class ValidateAuthView(APIView):
    """
    GET /api/v3/user/validate_auth

    Validates if current JWT is valid and active.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        # If authentication succeeded, token is valid
        return Response(status=status.HTTP_200_OK)


class LogoutView(APIView):
    """
    POST /api/v3/user/logout

    Invalidates the current authentication token by removing it from the database.
    Requires authentication.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.auth

        # Removing the token is equivalent to rmeoving the session
        models.LoginToken.objects.filter(token=token).delete()
        return Response(status=status.HTTP_200_OK)
