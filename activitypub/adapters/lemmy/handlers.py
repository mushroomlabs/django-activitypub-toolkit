import logging

from django.contrib.auth import get_user_model
from django.db.models import F
from django.db.models.signals import post_save
from django.dispatch import receiver

from activitypub.core.models import ActivityContext, ActorContext, CollectionContext, Domain
from activitypub.core.signals import activity_done, reference_loaded

from .models.aggregates import (
    FollowerCount,
    RankingScore,
    ReactionCount,
    ReplyCount,
    SubmissionCount,
    UserActivity,
)
from .models.core import (
    Comment,
    Community,
    Person,
    Post,
    Report,
    Site,
    UserProfile,
    UserSettings,
)

logger = logging.getLogger(__name__)
User = get_user_model()


@receiver(post_save, sender=User)
def on_new_user_create_profile(sender, **kw):
    if kw["created"]:
        user = kw["instance"]
        UserProfile.objects.create(user=user)
        UserSettings.objects.create(user=user)


@receiver(post_save, sender=Community)
def on_local_community_created_create_followers_collection(sender, **kw):
    community = kw["instance"]

    if kw["created"] and community.reference.is_local:
        actor = ActorContext.make(reference=community.reference)
        if actor.followers is None:
            followers_ref = CollectionContext.generate_reference(domain=actor.reference.domain)
            actor.followers = followers_ref
            actor.save()

        if actor.followers.get_by_context(CollectionContext) is None:
            CollectionContext.make(reference=actor.followers)


@receiver(post_save, sender=Person)
def on_person_created_create_aggregates_record(sender, **kw):
    person = kw["instance"]

    if kw["created"]:
        FollowerCount.objects.get_or_create(reference=person.reference)
        SubmissionCount.objects.get_or_create(reference=person.reference)


@receiver(post_save, sender=Person)
def on_local_person_created_create_follow_collections(sender, **kw):
    person = kw["instance"]

    if kw["created"] and person.reference.is_local:
        actor = ActorContext.make(reference=person.reference)
        if actor.following is None:
            following_ref = CollectionContext.generate_reference(domain=actor.reference.domain)
            actor.following = following_ref
            actor.save()

        if actor.followers is None:
            followers_ref = CollectionContext.generate_reference(domain=actor.reference.domain)
            actor.followers = followers_ref
            actor.save()

        if actor.following.get_by_context(CollectionContext) is None:
            CollectionContext.make(reference=actor.following)

        if actor.followers.get_by_context(CollectionContext) is None:
            CollectionContext.make(reference=actor.followers)


@receiver(post_save, sender=Community)
def on_community_created_create_aggregates_record(sender, **kw):
    community = kw["instance"]

    if kw["created"]:
        FollowerCount.objects.get_or_create(reference=community.reference)
        SubmissionCount.objects.get_or_create(reference=community.reference)
        UserActivity.objects.get_or_create(reference=community.reference)


@receiver(post_save, sender=Post)
def on_post_created_create_aggregates_record(sender, **kw):
    post = kw["instance"]

    if kw["created"]:
        ReactionCount.objects.get_or_create(reference=post.reference)
        ReplyCount.objects.get_or_create(reference=post.reference)
        for ranking_type in RankingScore.Types:
            RankingScore.objects.get_or_create(type=ranking_type, reference=post.reference)


@receiver(post_save, sender=Comment)
def on_comment_created_update_aggregates(sender, **kw):
    comment = kw["instance"]

    if kw["created"]:
        ReactionCount.objects.get_or_create(reference=comment.reference)
        ReplyCount.objects.get_or_create(reference=comment.reference)
        for ranking_type in RankingScore.Types:
            RankingScore.objects.get_or_create(type=ranking_type, reference=comment.reference)

        ReplyCount.objects.update_or_create(
            reference=comment.post.reference,
            defaults={"replies": F("replies") + 1, "latest_reply": comment.as2.published},
            create_defaults={"replies": 1},
        )


@receiver(post_save, sender=Site)
def on_site_created_create_aggregates_record(sender, **kw):
    site = kw["instance"]

    if kw["created"]:
        UserActivity.objects.get_or_create(reference=site.reference)
        SubmissionCount.objects.get_or_create(reference=site.reference)


@receiver(activity_done)
def on_vote_update_aggregates(sender, **kw):
    activity = kw["activity"]

    if activity.type not in [ActivityContext.Types.LIKE, ActivityContext.Types.DISLIKE]:
        return

    if activity.object is None:
        return

    reaction_count, _ = ReactionCount.objects.get_or_create(reference=activity.object)

    if activity.type == ActivityContext.Types.LIKE:
        reaction_count.upvotes += 1
    else:
        reaction_count.downvotes += 1
    reaction_count.save()

    ranking_types = [RankingScore.Types.TOP, RankingScore.Types.CONTROVERSY]
    for ranking in RankingScore.objects.filter(reference=activity.object, type__in=ranking_types):
        ranking.calculate()
        ranking.save()


@receiver(activity_done)
def on_flag_create_report(sender, **kw):
    activity = kw["activity"]

    if activity.type != ActivityContext.Types.FLAG:
        return

    Report.objects.get_or_create(reference=activity.reference)


@receiver(activity_done)
def on_block_update_person(sender, **kw):
    activity = kw["activity"]

    if activity.type != ActivityContext.Types.BLOCK:
        return

    if activity.actor is None or activity.object is None:
        return

    person = Person.objects.filter(reference=activity.actor).first()
    if person is None:
        return

    community = Community.objects.filter(reference=activity.object).first()
    if community is not None:
        person.blocked_communities.add(community)
        return

    domain = Domain.objects.filter(name=activity.object.domain.name).first()
    if domain is not None:
        person.blocked_instances.add(domain)


@receiver(activity_done)
def on_undo_revert_action(sender, **kw):
    activity = kw["activity"]

    if activity.type != ActivityContext.Types.UNDO:
        return

    if activity.object is None:
        return

    original = activity.object.get_by_context(ActivityContext)
    if original is None:
        return

    match original.type:
        case ActivityContext.Types.LIKE | ActivityContext.Types.DISLIKE:
            _undo_vote(original)
        case ActivityContext.Types.BLOCK:
            _undo_block(original)


def _undo_vote(original: ActivityContext):
    if original.object is None:
        return

    try:
        reaction_count = ReactionCount.objects.get(reference=original.object)
    except ReactionCount.DoesNotExist:
        return

    if original.type == ActivityContext.Types.LIKE:
        reaction_count.upvotes = max(0, reaction_count.upvotes - 1)
    else:
        reaction_count.downvotes = max(0, reaction_count.downvotes - 1)

    reaction_count.save()

    ranking_types = [RankingScore.Types.TOP, RankingScore.Types.CONTROVERSY]
    for ranking in RankingScore.objects.filter(reference=original.object, type__in=ranking_types):
        ranking.calculate()
        ranking.save()


def _undo_block(original: ActivityContext):
    if original.actor is None or original.object is None:
        return

    person = Person.objects.filter(reference=original.actor).first()
    if person is None:
        return

    community = Community.objects.filter(reference=original.object).first()
    if community is not None:
        person.blocked_communities.remove(community)
        return

    domain = Domain.objects.filter(name=original.object.domain.name).first()
    if domain is not None:
        person.blocked_instances.remove(domain)


@receiver(reference_loaded)
def on_reference_loaded_create_lemmy_objects(sender, **kw):
    reference = kw["reference"]

    for lemmy_model in [Community, Comment, Post, Person, Site]:
        lemmy_model.resolve(reference)


__all__ = (
    "on_new_user_create_profile",
    "on_person_created_create_aggregates_record",
    "on_local_community_created_create_followers_collection",
    "on_local_person_created_create_follow_collections",
    "on_person_created_create_aggregates_record",
    "on_community_created_create_aggregates_record",
    "on_post_created_create_aggregates_record",
    "on_comment_created_update_aggregates",
    "on_site_created_create_aggregates_record",
    "on_vote_update_aggregates",
    "on_flag_create_report",
    "on_block_update_person",
    "on_undo_revert_action",
    "on_reference_loaded_create_lemmy_objects",
)
