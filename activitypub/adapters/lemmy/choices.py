from django.db import models


class ListingTypes(models.TextChoices):
    ALL = "All"
    LOCAL = "Local"
    SUBSCRIBED = "Subscribed"
    MODERATOR = "ModeratorView"


class PostListingModes(models.TextChoices):
    LIST = "List"
    CARD = "Card"
    SMALLCARD = "SmallCard"


class SortOrderTypes(models.TextChoices):
    ACTIVE = "Active"
    HOT = "Hot"
    NEW = "New"
    OLD = "Old"
    TOP_DAY = "TopDay"
    TOP_WEEK = "TopWeek"
    TOP_MONTH = "TopMonth"
    TOP_YEAR = "TopYear"
    TOP_ALL = "TopAll"
    MOST_COMMENTS = "MostComments"
    NEW_COMMENTS = "NewComments"
    TOP_HOUR = "TopHour"
    TOP_SIXHOUR = "TopSixHour"
    TOP_TWELVEHOUR = "TopTwelveHour"
    TOP_THREEMONTHS = "TopThreeMonths"
    TOP_SIXMONTHS = "TopSixMonths"
    TOP_NINEMONTHS = "TopNineMonths"
    CONTROVERSIAL = "Controversial"
    SCALED = "Scaled"


class PostFeatureType(models.TextChoices):
    LOCAL = "Local"
    COMMUNITY = "Community"


class SearchType(models.TextChoices):
    ALL = "All"
    COMMENTS = "Comments"
    POSTS = "Posts"
    COMMUNITIES = "Communities"
    USERS = "Users"
    URL = "Url"


class SubscriptionStatus(models.TextChoices):
    UNSUBSCRIBED = "NotSubscribed"
    PENDING = "Pending"
    SUBSCRIBED = "Subscribed"
