from django.db import models
from django.utils import timezone

from .core import Comment, Community, Person, Post, Site


class AggregateModelMixin:
    @property
    def hours_since_published(self):
        delta = timezone.now() - self.published
        return delta.days * 24 + int(delta.seconds / 60)

    def recalculate_ranks(self):
        decay = (self.hours_since_published + 2) ** (1.8)
        self.hot_rank = (self.score + 2) / decay
        self.save()


class CommentAggregates(models.Model, AggregateModelMixin):
    comment = models.OneToOneField(Comment, models.CASCADE, primary_key=True)
    score = models.BigIntegerField(default=1)
    upvotes = models.BigIntegerField(default=1)
    downvotes = models.BigIntegerField(default=0)
    published = models.DateTimeField(auto_now_add=True)
    child_count = models.IntegerField(default=0)
    hot_rank = models.FloatField(default=0.0)
    controversy_rank = models.FloatField(default=0.0)


class CommunityAggregates(models.Model):
    community = models.OneToOneField(Community, on_delete=models.CASCADE, primary_key=True)
    subscribers = models.BigIntegerField(default=0)
    posts = models.BigIntegerField(default=0)
    comments = models.BigIntegerField(default=0)
    published = models.DateTimeField(auto_now_add=True)
    users_active_day = models.BigIntegerField(default=0)
    users_active_week = models.BigIntegerField(default=0)
    users_active_month = models.BigIntegerField(default=0)
    users_active_half_year = models.BigIntegerField(default=0)
    hot_rank = models.FloatField(default=0.0)
    subscribers_local = models.BigIntegerField(default=0)


class PostAggregates(models.Model, AggregateModelMixin):
    post = models.OneToOneField(Post, on_delete=models.CASCADE, primary_key=True)
    comments = models.BigIntegerField(default=0)
    score = models.BigIntegerField(default=1)
    upvotes = models.BigIntegerField(default=1)
    downvotes = models.BigIntegerField(default=0)
    published = models.DateTimeField(auto_now_add=True)
    newest_comment_time_necro = models.DateTimeField(null=True, editable=False)
    newest_comment_time = models.DateTimeField(null=True, editable=False)
    featured_community = models.BooleanField(default=False)
    featured_local = models.BooleanField(default=False)
    hot_rank = models.FloatField(default=0.0)
    hot_rank_active = models.FloatField(default=0.0)
    controversy_rank = models.FloatField(default=0.0)
    scaled_rank = models.FloatField(default=0.0)


class PersonPostAggregates(models.Model):
    person = models.ForeignKey(Person, models.CASCADE)
    post = models.ForeignKey(Post, models.CASCADE)
    read_comments = models.BigIntegerField(default=0)
    published = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("person", "post")


class PersonAggregates(models.Model):
    person = models.OneToOneField(
        Person, related_name="counts", on_delete=models.CASCADE, primary_key=True
    )
    post_count = models.PositiveIntegerField(default=0)
    post_score = models.IntegerField(default=0)
    comment_count = models.PositiveIntegerField(default=0)
    comment_score = models.IntegerField(default=0)


class SiteReportedStatistics(models.Model):
    site = models.OneToOneField(
        Site, related_name="statistics", on_delete=models.CASCADE, primary_key=True
    )
    users = models.PositiveIntegerField(default=0)
    posts = models.PositiveIntegerField(default=0)
    comments = models.PositiveIntegerField(default=0)
    communities = models.PositiveIntegerField(default=0)
    users_active_day = models.PositiveIntegerField(default=0)
    users_active_week = models.PositiveIntegerField(default=0)
    users_active_month = models.PositiveIntegerField(default=0)
    users_active_half_year = models.PositiveIntegerField(default=0)


__all__ = (
    "CommentAggregates",
    "CommunityAggregates",
    "PostAggregates",
    "PersonAggregates",
    "PersonPostAggregates",
    "SiteReportedStatistics",
)
