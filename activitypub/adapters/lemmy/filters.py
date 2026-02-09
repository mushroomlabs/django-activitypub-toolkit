from datetime import timedelta

from django.db.models import F, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from django_filters import rest_framework as filters

from activitypub.core.models import ActorContext, Identity, ObjectContext

from . import models
from .choices import ListingTypes, SortOrderTypes


def ranking_subquery(ranking_type):
    """Create a subquery to get the ranking score for a specific type."""
    return Coalesce(
        Subquery(
            models.RankingScore.objects.filter(
                reference=OuterRef("reference"), type=ranking_type
            ).values("score")[:1]
        ),
        Value(0.0),
    )


def reply_count_subquery(field="replies"):
    """Create a subquery to get reply count."""
    return Coalesce(
        Subquery(
            models.ReplyCount.objects.filter(reference=OuterRef("reference")).values(field)[:1]
        ),
        Value(0),
    )


class LemmyFilterSet(filters.FilterSet):
    """
    Base FilterSet for Lemmy that provides safe access to actor reference.

    Lemmy assumes one identity per authenticated user. This base class
    provides a method to safely retrieve the actor reference without
    depending on middleware.
    """

    def get_actor_reference(self):
        """
        Get the actor reference for the authenticated user.

        Returns None if:
        - User is not authenticated
        - User has no identity
        - User has multiple identities (edge case)
        """
        if not self.request.user.is_authenticated:
            return None

        try:
            identity = Identity.objects.select_related("actor").get(user=self.request.user)
            return identity.actor.reference
        except (Identity.DoesNotExist, Identity.MultipleObjectsReturned):
            return None


class PostFilter(LemmyFilterSet):
    type_ = filters.ChoiceFilter(
        field_name="type", choices=ListingTypes.choices, method="filter_listing_type"
    )
    sort = filters.ChoiceFilter(choices=SortOrderTypes.choices, method="apply_sort")
    community_id = filters.NumberFilter(field_name="community__object_id")
    community_name = filters.CharFilter(method="filter_community_name")
    saved_only = filters.BooleanFilter(method="filter_saved_only")
    liked_only = filters.BooleanFilter(method="filter_liked_only")
    disliked_only = filters.BooleanFilter(method="filter_disliked_only")
    show_hidden = filters.BooleanFilter(method="filter_show_hidden")
    show_read = filters.BooleanFilter(method="filter_show_read")
    show_nsfw = filters.BooleanFilter(method="filter_show_nsfw")

    class Meta:
        model = models.Post
        fields = [
            "type_",
            "sort",
            "community_id",
            "community_name",
            "saved_only",
            "liked_only",
            "disliked_only",
            "show_hidden",
            "show_read",
            "show_nsfw",
        ]

    def filter_listing_type(self, queryset, name, value):
        if value == ListingTypes.LOCAL:
            return queryset.filter(reference__domain__local=True)

        actor_ref = self.get_actor_reference()

        if value == ListingTypes.SUBSCRIBED and actor_ref:
            return queryset.filter(community__community_data__subscribers__reference=actor_ref)

        if value == ListingTypes.MODERATOR and actor_ref:
            return queryset.filter(community__community_data__moderated_by__reference=actor_ref)
        return queryset

    def filter_community_name(self, queryset, name, value):
        if not value:
            return queryset
        actors = ActorContext.objects.filter(preferred_username=value)
        communities = models.Community.objects.filter(
            reference__in=[actor.reference for actor in actors]
        )
        return queryset.filter(community__in=communities)

    def filter_saved_only(self, queryset, name, value):
        if value and self.request.user.is_authenticated:
            return queryset.filter(saved_by=self.request.user.lemmy_profile)
        return queryset

    def filter_liked_only(self, queryset, name, value):
        if value:
            actor_ref = self.get_actor_reference()
            if actor_ref:
                return queryset.filter(liked_by__reference=actor_ref)
        return queryset

    def filter_disliked_only(self, queryset, name, value):
        if value and self.request.user.is_authenticated:
            liked_posts = self.request.user.lemmy_profile.liked_posts.all()
            return queryset.exclude(id__in=liked_posts)
        return queryset

    def filter_show_hidden(self, queryset, name, value):
        if not value and self.request.user.is_authenticated:
            return queryset.exclude(hidden_by=self.request.user.lemmy_profile)
        return queryset

    def filter_show_read(self, queryset, name, value):
        if not value and self.request.user.is_authenticated:
            return queryset.exclude(read_by=self.request.user.lemmy_profile)
        return queryset

    def filter_show_nsfw(self, queryset, name, value):
        if not value:
            nsfw_refs = ObjectContext.objects.filter(sensitive=True).values_list(
                "reference", flat=True
            )
            return queryset.exclude(reference__in=nsfw_refs)
        return queryset

    def apply_sort(self, queryset, name, value):
        now = timezone.now()
        published_path = "reference__activitypub_baseas2objectcontext_context__published"

        if value == SortOrderTypes.NEW:
            return queryset.order_by(f"-{published_path}")

        if value == SortOrderTypes.OLD:
            return queryset.order_by(published_path)

        if value == SortOrderTypes.MOST_COMMENTS:
            return queryset.annotate(comment_count=reply_count_subquery()).order_by(
                "-comment_count"
            )

        if value == SortOrderTypes.NEW_COMMENTS:
            return queryset.annotate(
                newest_comment=reply_count_subquery(field="latest_reply")
            ).order_by("-newest_comment")

        ranking_types = {
            SortOrderTypes.ACTIVE: models.RankingScore.Types.ACTIVE,
            SortOrderTypes.HOT: models.RankingScore.Types.HOT,
            SortOrderTypes.CONTROVERSIAL: models.RankingScore.Types.CONTROVERSY,
            SortOrderTypes.SCALED: models.RankingScore.Types.SCALED,
        }

        if value in ranking_types:
            return queryset.annotate(rank_score=ranking_subquery(ranking_types[value])).order_by(
                "-rank_score"
            )

        time_filters = {
            SortOrderTypes.TOP_HOUR: timedelta(hours=1),
            SortOrderTypes.TOP_SIXHOUR: timedelta(hours=6),
            SortOrderTypes.TOP_TWELVEHOUR: timedelta(hours=12),
            SortOrderTypes.TOP_DAY: timedelta(days=1),
            SortOrderTypes.TOP_WEEK: timedelta(weeks=1),
            SortOrderTypes.TOP_MONTH: timedelta(days=30),
            SortOrderTypes.TOP_THREEMONTHS: timedelta(days=90),
            SortOrderTypes.TOP_SIXMONTHS: timedelta(days=180),
            SortOrderTypes.TOP_NINEMONTHS: timedelta(days=270),
            SortOrderTypes.TOP_YEAR: timedelta(days=365),
        }

        if value in time_filters:
            cutoff = now - time_filters[value]
            return (
                queryset.filter(**{f"{published_path}__gte": cutoff})
                .annotate(
                    vote_score=Coalesce(F("reference__reaction_count__upvotes"), Value(0))
                    - Coalesce(F("reference__reaction_count__downvotes"), Value(0))
                )
                .order_by("-vote_score")
            )

        if value == SortOrderTypes.TOP_ALL:
            return queryset.annotate(
                vote_score=Coalesce(F("reference__reaction_count__upvotes"), Value(0))
                - Coalesce(F("reference__reaction_count__downvotes"), Value(0))
            ).order_by("-vote_score")

        return queryset.order_by(f"-{published_path}")


class CommentFilter(LemmyFilterSet):
    type_ = filters.ChoiceFilter(
        field_name="type", choices=ListingTypes.choices, method="filter_listing_type"
    )
    sort = filters.ChoiceFilter(choices=SortOrderTypes.choices, method="apply_sort")
    post_id = filters.NumberFilter(field_name="post__object_id")
    community_id = filters.NumberFilter(field_name="post__post_data__community__object_id")
    community_name = filters.CharFilter(method="filter_community_name")
    saved_only = filters.BooleanFilter(method="filter_saved_only")
    liked_only = filters.BooleanFilter(method="filter_liked_only")
    disliked_only = filters.BooleanFilter(method="filter_disliked_only")

    class Meta:
        model = models.Comment
        fields = [
            "type_",
            "sort",
            "post_id",
            "community_id",
            "community_name",
            "saved_only",
            "liked_only",
            "disliked_only",
        ]

    def get_person(self):
        if not self.request.user.is_authenticated:
            return None

        try:
            identity = Identity.objects.select_related("actor").get(user=self.request.user)
            person, _ = models.Person.objects.get_or_create(reference=identity.actor.reference)
            return person
        except (Identity.DoesNotExist, Identity.MultipleObjectsReturned):
            return None

    def filter_listing_type(self, queryset, name, value):
        if value == ListingTypes.LOCAL:
            return queryset.filter(reference__domain__local=True)

        actor_ref = self.get_actor_reference()

        if value == ListingTypes.SUBSCRIBED and actor_ref:
            return queryset.filter(
                post__post_data__community__community_data__subscribers=actor_ref
            )

        if value == ListingTypes.MODERATOR and actor_ref:
            return queryset.filter(
                post__post_data__community__community_data__moderated_by=actor_ref
            )
        return queryset

    def filter_community_name(self, queryset, name, value):
        if not value:
            return queryset
        actors = ActorContext.objects.filter(preferred_username=value)
        communities = models.Community.objects.filter(
            reference__in=[actor.reference for actor in actors]
        )
        return queryset.filter(post__community__in=communities)

    def filter_saved_only(self, queryset, name, value):
        if value and self.request.user.is_authenticated:
            return queryset.filter(saved_by=self.request.user.lemmy_profile)
        return queryset

    def filter_liked_only(self, queryset, name, value):
        if value and self.request.user.is_authenticated:
            self.person = self.get_person()
            return queryset.filter(liked_by=self.person)
        return queryset

    def filter_disliked_only(self, queryset, name, value):
        if value and self.request.user.is_authenticated:
            person = self.get_person()
            return (
                queryset
                if person is None
                else queryset.exclude(id__in=person.liked_comments.all())
            )
        return queryset

    def apply_sort(self, queryset, name, value):
        now = timezone.now()
        published_path = "reference__activitypub_baseas2objectcontext_context__published"

        if value == SortOrderTypes.NEW:
            return queryset.order_by(f"-{published_path}")

        if value == SortOrderTypes.OLD:
            return queryset.order_by(published_path)

        ranking_types = {
            SortOrderTypes.HOT: models.RankingScore.Types.HOT,
            SortOrderTypes.CONTROVERSIAL: models.RankingScore.Types.CONTROVERSY,
        }

        if value in ranking_types:
            return queryset.annotate(rank_score=ranking_subquery(ranking_types[value])).order_by(
                "-rank_score"
            )

        time_filters = {
            SortOrderTypes.TOP_HOUR: timedelta(hours=1),
            SortOrderTypes.TOP_SIXHOUR: timedelta(hours=6),
            SortOrderTypes.TOP_TWELVEHOUR: timedelta(hours=12),
            SortOrderTypes.TOP_DAY: timedelta(days=1),
            SortOrderTypes.TOP_WEEK: timedelta(weeks=1),
            SortOrderTypes.TOP_MONTH: timedelta(days=30),
            SortOrderTypes.TOP_THREEMONTHS: timedelta(days=90),
            SortOrderTypes.TOP_SIXMONTHS: timedelta(days=180),
            SortOrderTypes.TOP_NINEMONTHS: timedelta(days=270),
            SortOrderTypes.TOP_YEAR: timedelta(days=365),
        }

        if value in time_filters:
            cutoff = now - time_filters[value]
            return (
                queryset.filter(**{f"{published_path}__gte": cutoff})
                .annotate(
                    vote_score=Coalesce(F("reference__reaction_count__upvotes"), Value(0))
                    - Coalesce(F("reference__reaction_count__downvotes"), Value(0))
                )
                .order_by("-vote_score")
            )

        if value == SortOrderTypes.TOP_ALL:
            return queryset.annotate(
                vote_score=Coalesce(F("reference__reaction_count__upvotes"), Value(0))
                - Coalesce(F("reference__reaction_count__downvotes"), Value(0))
            ).order_by("-vote_score")

        return queryset.order_by(f"-{published_path}")


class CommunityFilter(LemmyFilterSet):
    type_ = filters.ChoiceFilter(
        field_name="type", choices=ListingTypes.choices, method="filter_listing_type"
    )
    sort = filters.ChoiceFilter(choices=SortOrderTypes.choices, method="apply_sort")
    show_nsfw = filters.BooleanFilter(method="filter_show_nsfw")

    class Meta:
        model = models.Community
        fields = ["type_", "sort", "show_nsfw"]

    def filter_listing_type(self, queryset, name, value):
        if value == ListingTypes.LOCAL:
            return queryset.filter(reference__domain__local=True)

        if value == ListingTypes.SUBSCRIBED:
            return queryset.filter(
                reference__in=self.request.user.lemmy_profile.subscribed_communities.values(
                    "reference"
                )
            )
        return queryset

    def filter_show_nsfw(self, queryset, name, value):
        if not value:
            return queryset.filter(lemmy__nsfw=False)
        return queryset

    def apply_sort(self, queryset, name, value):
        now = timezone.now()
        published_path = "reference__activitypub_baseas2objectcontext_context__published"

        if value == SortOrderTypes.NEW:
            return queryset.order_by(f"-{published_path}")

        if value == SortOrderTypes.OLD:
            return queryset.order_by(published_path)

        if value in [SortOrderTypes.ACTIVE, SortOrderTypes.HOT]:
            return queryset.annotate(
                rank_score=ranking_subquery(models.RankingScore.Types.HOT)
            ).order_by("-rank_score")

        time_filters = {
            SortOrderTypes.TOP_HOUR: timedelta(hours=1),
            SortOrderTypes.TOP_SIXHOUR: timedelta(hours=6),
            SortOrderTypes.TOP_TWELVEHOUR: timedelta(hours=12),
            SortOrderTypes.TOP_DAY: timedelta(days=1),
            SortOrderTypes.TOP_WEEK: timedelta(weeks=1),
            SortOrderTypes.TOP_MONTH: timedelta(days=30),
            SortOrderTypes.TOP_THREEMONTHS: timedelta(days=90),
            SortOrderTypes.TOP_SIXMONTHS: timedelta(days=180),
            SortOrderTypes.TOP_NINEMONTHS: timedelta(days=270),
            SortOrderTypes.TOP_YEAR: timedelta(days=365),
        }

        if value in time_filters:
            cutoff = now - time_filters[value]
            return (
                queryset.filter(**{f"{published_path}__gte": cutoff})
                .annotate(
                    subscriber_count=Coalesce(F("reference__follower_count__total"), Value(0))
                )
                .order_by("-subscriber_count")
            )

        if value == SortOrderTypes.TOP_ALL:
            return queryset.annotate(
                subscriber_count=Coalesce(F("reference__follower_count__total"), Value(0))
            ).order_by("-subscriber_count")

        return queryset.order_by(f"-{published_path}")


# Query path constants for searching through Reference -> Context models
OBJECT_CONTEXT_PATH = "reference__activitypub_baseas2objectcontext_context"
ACTOR_CONTEXT_PATH = f"{OBJECT_CONTEXT_PATH}__actorcontext"


class PostSearchFilter(LemmyFilterSet):
    q = filters.CharFilter(method="filter_search")
    community_id = filters.NumberFilter(field_name="community__object_id")
    sort = filters.ChoiceFilter(choices=SortOrderTypes.choices, method="apply_sort")

    class Meta:
        model = models.Post
        fields = ["q", "community_id", "sort"]

    def filter_search(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(Q(**{f"{OBJECT_CONTEXT_PATH}__name__icontains": value})).exclude(
            Q(deleted=True) | Q(removed=True)
        )

    def apply_sort(self, queryset, name, value):
        published_path = "reference__activitypub_baseas2objectcontext_context__published"

        if value == SortOrderTypes.NEW:
            return queryset.order_by(f"-{published_path}")

        if value == SortOrderTypes.OLD:
            return queryset.order_by(published_path)

        if value == SortOrderTypes.TOP_ALL:
            return queryset.annotate(
                vote_score=Coalesce(F("reference__reaction_count__upvotes"), Value(0))
                - Coalesce(F("reference__reaction_count__downvotes"), Value(0))
            ).order_by("-vote_score")

        return queryset.order_by(f"-{published_path}")


class CommunitySearchFilter(LemmyFilterSet):
    q = filters.CharFilter(method="filter_search")
    sort = filters.ChoiceFilter(choices=SortOrderTypes.choices, method="apply_sort")

    class Meta:
        model = models.Community
        fields = ["q", "sort"]

    def filter_search(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(**{f"{OBJECT_CONTEXT_PATH}__name__icontains": value})
            | Q(**{f"{OBJECT_CONTEXT_PATH}__summary__icontains": value})
            | Q(**{f"{ACTOR_CONTEXT_PATH}__preferred_username__icontains": value})
        ).exclude(Q(deleted=True) | Q(removed=True))

    def apply_sort(self, queryset, name, value):
        published_path = "reference__activitypub_baseas2objectcontext_context__published"

        if value == SortOrderTypes.NEW:
            return queryset.order_by(f"-{published_path}")

        if value == SortOrderTypes.OLD:
            return queryset.order_by(published_path)

        if value == SortOrderTypes.TOP_ALL:
            return queryset.annotate(
                subscriber_count=Coalesce(F("reference__follower_count__total"), Value(0))
            ).order_by("-subscriber_count")

        return queryset.order_by(f"-{published_path}")


class PersonSearchFilter(LemmyFilterSet):
    q = filters.CharFilter(method="filter_search")
    sort = filters.ChoiceFilter(choices=SortOrderTypes.choices, method="apply_sort")

    class Meta:
        model = models.Person
        fields = ["q", "sort"]

    def filter_search(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(**{f"{OBJECT_CONTEXT_PATH}__name__icontains": value})
            | Q(**{f"{ACTOR_CONTEXT_PATH}__preferred_username__icontains": value})
        )

    def apply_sort(self, queryset, name, value):
        order_map = {
            SortOrderTypes.NEW: f"-{OBJECT_CONTEXT_PATH}__published",
            SortOrderTypes.OLD: f"{OBJECT_CONTEXT_PATH}__published",
        }
        if value in order_map:
            return queryset.order_by(order_map[value])
        return queryset
