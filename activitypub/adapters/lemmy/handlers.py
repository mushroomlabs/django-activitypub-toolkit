import logging

from activitypub.core.models import ActorContext, CollectionContext
from activitypub.core.signals import reference_loaded
from django.contrib.auth import get_user_model
from django.db.models import F
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import (
    Comment,
    CommentAggregates,
    Community,
    CommunityAggregates,
    Person,
    PersonAggregates,
    Post,
    PostAggregates,
    Report,
    Site,
    SiteReportedStatistics,
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
        PersonAggregates.objects.get_or_create(person=person)


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
        CommunityAggregates.objects.get_or_create(community=community)


@receiver(post_save, sender=Post)
def on_post_created_create_aggregates_record(sender, **kw):
    post = kw["instance"]

    if kw["created"]:
        PostAggregates.objects.create(post=post)


@receiver(post_save, sender=Comment)
def on_comment_created_update_aggregates(sender, **kw):
    comment = kw["instance"]

    if kw["created"]:
        CommentAggregates.objects.create(comment=comment)
        PostAggregates.objects.update_or_create(
            post=comment.post,
            defaults={"comments": F("comments") + 1},
            create_defaults={"comments": 1},
        )


@receiver(post_save, sender=Site)
def on_site_created_create_aggregates_record(sender, **kw):
    site = kw["instance"]

    if kw["created"]:
        SiteReportedStatistics.objects.create(site=site)


@receiver(reference_loaded)
def on_reference_loaded_create_lemmy_objects(sender, **kw):
    reference = kw["reference"]

    for lemmy_model in [Community, Comment, Post, Person, Site, Report]:
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
    "on_reference_loaded_create_lemmy_objects",
)
