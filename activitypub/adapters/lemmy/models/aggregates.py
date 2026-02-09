from django.db import models
from django.utils import timezone
from model_utils.models import TimeStampedModel

from activitypub.core.models import Reference


class ReactionCount(TimeStampedModel):
    reference = models.OneToOneField(
        Reference, related_name="reaction_count", on_delete=models.CASCADE, primary_key=True
    )
    upvotes = models.BigIntegerField(default=1)
    downvotes = models.BigIntegerField(default=0)

    @property
    def score(self):
        return self.upvotes - self.downvotes


class RankingScore(TimeStampedModel):
    class Types(models.IntegerChoices):
        TOP = (0, "Top")
        HOT = (1, "Hot")
        ACTIVE = (2, "Active")
        CONTROVERSY = (3, "Controversy")
        SCALED = (4, "Scaled")

    type = models.SmallIntegerField(choices=Types.choices)
    reference = models.ForeignKey(Reference, related_name="rankings", on_delete=models.CASCADE)
    score = models.FloatField(default=0.0)

    @property
    def hours_since_published(self):
        delta = timezone.now() - self.created
        return delta.days * 24 + int(delta.seconds / 60)

    def calculate(self):
        calculators = {
            self.Types.TOP: self._calculate_top,
            self.Types.HOT: self._calculate_hot,
            self.Types.ACTIVE: self._calculate_active,
            self.Types.CONTROVERSY: self._calculate_controversy,
            self.Types.SCALED: self._calculate_scaled,
        }
        self.score = calculators[self.type]()

    def _calculate_top(self):
        try:
            return self.reference.reaction_count.score
        except Reference.reaction_count.RelatedObjectDoesNotExist:
            return 0

    def _calculate_hot(self):
        try:
            voting_score = self.reference.reaction_count.score
        except Reference.reaction_count.RelatedObjectDoesNotExist:
            voting_score = 0

        decay = (self.hours_since_published + 2) ** (1.8)
        return (voting_score + 2) / decay

    def _calculate_active(self):
        pass

    def _calculate_controversy(self):
        try:
            reaction = self.reference.reaction_count
        except Reference.reaction_count.RelatedObjectDoesNotExist:
            return 0.0

        if reaction.upvotes <= 0 or reaction.downvotes <= 0:
            return 0.0

        total = reaction.upvotes + reaction.downvotes
        # Higher score when votes are more evenly split
        return total / (abs(total - reaction.downvotes * 2) + 1)

    def _calculate_scaled(self):
        pass


class UserActivity(TimeStampedModel):
    reference = models.OneToOneField(
        Reference, related_name="user_activity_report", on_delete=models.CASCADE, primary_key=True
    )
    active_day = models.BigIntegerField(default=0)
    active_week = models.BigIntegerField(default=0)
    active_month = models.BigIntegerField(default=0)
    active_half_year = models.BigIntegerField(default=0)


class FollowerCount(TimeStampedModel):
    reference = models.OneToOneField(
        Reference, related_name="follower_count", on_delete=models.CASCADE, primary_key=True
    )
    total = models.BigIntegerField(default=0)
    local = models.BigIntegerField(default=0)


class ReplyCount(TimeStampedModel):
    reference = models.OneToOneField(
        Reference, related_name="reply_count", on_delete=models.CASCADE
    )
    replies = models.IntegerField(default=0)
    latest_reply = models.DateTimeField(null=True)


class SubmissionCount(TimeStampedModel):
    reference = models.OneToOneField(
        Reference, related_name="submission_count", on_delete=models.CASCADE
    )
    posts = models.BigIntegerField(default=0)
    comments = models.IntegerField(default=0)


__all__ = (
    "FollowerCount",
    "RankingScore",
    "ReactionCount",
    "ReplyCount",
    "SubmissionCount",
    "UserActivity",
)
