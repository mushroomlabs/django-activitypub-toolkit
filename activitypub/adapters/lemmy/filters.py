from datetime import timedelta

from activitypub.core.models import ActorContext, Identity, ObjectContext
from django.db.models import Q
from django.utils import timezone
from django_filters import rest_framework as filters

from . import models
from .choices import ListingTypes, SortOrderTypes


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
        order_map = {
            SortOrderTypes.ACTIVE: "-postaggregates__hot_rank_active",
            SortOrderTypes.HOT: "-postaggregates__hot_rank",
            SortOrderTypes.NEW: "-reference__activitypub_baseas2objectcontext_context__published",
            SortOrderTypes.OLD: "reference__activitypub_baseas2objectcontext_context__published",
            SortOrderTypes.MOST_COMMENTS: "-postaggregates__comments",
            SortOrderTypes.NEW_COMMENTS: "-postaggregates__newest_comment_time",
            SortOrderTypes.CONTROVERSIAL: "-postaggregates__controversy_rank",
            SortOrderTypes.SCALED: "-postaggregates__scaled_rank",
        }

        if value in order_map:
            return queryset.order_by(order_map[value])

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
            return queryset.filter(postaggregates__published__gte=cutoff).order_by(
                "-postaggregates__score"
            )

        if value == SortOrderTypes.TOP_ALL:
            return queryset.order_by("-postaggregates__score")

        return queryset.order_by("-postaggregates__published")


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
        order_map = {
            SortOrderTypes.HOT: "-commentaggregates__hot_rank",
            SortOrderTypes.NEW: "-commentaggregates__published",
            SortOrderTypes.OLD: "commentaggregates__published",
            SortOrderTypes.CONTROVERSIAL: "-commentaggregates__controversy_rank",
        }

        if value in order_map:
            return queryset.order_by(order_map[value])

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
            return queryset.filter(commentaggregates__published__gte=cutoff).order_by(
                "-commentaggregates__score"
            )

        if value == SortOrderTypes.TOP_ALL:
            return queryset.order_by("-commentaggregates__score")

        return queryset.order_by("-commentaggregates__published")


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
        order_map = {
            SortOrderTypes.ACTIVE: "-communityaggregates__hot_rank",
            SortOrderTypes.HOT: "-communityaggregates__hot_rank",
            SortOrderTypes.NEW: "-communityaggregates__published",
            SortOrderTypes.OLD: "communityaggregates__published",
        }

        if value in order_map:
            return queryset.order_by(order_map[value])

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
            return queryset.filter(communityaggregates__published__gte=cutoff).order_by(
                "-communityaggregates__subscribers"
            )

        if value == SortOrderTypes.TOP_ALL:
            return queryset.order_by("-communityaggregates__subscribers")

        return queryset.order_by("-communityaggregates__published")


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
        order_map = {
            SortOrderTypes.NEW: "-postaggregates__published",
            SortOrderTypes.OLD: "postaggregates__published",
            SortOrderTypes.TOP_ALL: "-postaggregates__score",
        }
        if value in order_map:
            return queryset.order_by(order_map[value])
        return queryset.order_by("-postaggregates__published")


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
        order_map = {
            SortOrderTypes.NEW: "-communityaggregates__published",
            SortOrderTypes.OLD: "communityaggregates__published",
            SortOrderTypes.TOP_ALL: "-communityaggregates__subscribers",
        }
        if value in order_map:
            return queryset.order_by(order_map[value])
        return queryset.order_by("-communityaggregates__published")


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
