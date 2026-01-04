import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from . import tasks
from .exceptions import RejectedFollowRequest
from .models.ap import ActivityPubServer, Actor, FollowRequest
from .models.as2 import ActivityContext, BaseAs2ObjectContext, ObjectContext
from .models.collections import CollectionContext
from .models.linked_data import Domain, Notification
from .settings import app_settings
from .signals import notification_accepted, reference_field_changed

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=Domain)
def set_default_port_for_domain(sender, **kw):
    instance = kw["instance"]

    if instance.scheme == instance.SchemeTypes.HTTP and instance.port is None:
        instance.port = 80

    if instance.scheme == instance.SchemeTypes.HTTPS and instance.port is None:
        instance.port = 443


@receiver(post_save, sender=Domain)
def on_new_remote_domain_fetch_nodeinfo(sender, **kw):
    domain = kw["instance"]

    if kw["created"] and not domain.local:
        tasks.fetch_nodeinfo.delay(domain_id=domain.id)


@receiver(post_save, sender=Domain)
def on_new_local_domain_setup_nodeinfo(sender, **kw):
    domain = kw["instance"]

    if kw["created"] and domain.local:
        ActivityPubServer.objects.create(domain=domain)


@receiver(pre_save, sender=BaseAs2ObjectContext)
@receiver(pre_save, sender=ObjectContext)
def on_ap_object_create_define_related_collections(sender, **kw):
    instance = kw["instance"]
    reference = instance.reference

    if reference.is_remote:
        return

    if type(instance) is ObjectContext:
        if not instance.replies:
            instance.replies = CollectionContext.generate_reference(reference.domain)
            CollectionContext.make(instance.replies, name=f"Replies for {reference.uri}")
        if not instance.shares:
            instance.shares = CollectionContext.generate_reference(reference.domain)
            CollectionContext.make(instance.shares, name=f"Shares for {reference.uri}")
        if not instance.likes:
            instance.likes = CollectionContext.generate_reference(reference.domain)
            CollectionContext.make(instance.likes, name=f"Likes for {reference.uri}")


@receiver(reference_field_changed, sender=BaseAs2ObjectContext.in_reply_to.through)
@receiver(reference_field_changed, sender=ObjectContext.in_reply_to.through)
def on_new_reply_add_to_replies_collection(sender, **kw):
    action = kw["action"]
    instance = kw["instance"]
    pk_set = kw["pk_set"]

    if action == "post_add":
        for pk in pk_set:
            try:
                as2_object = BaseAs2ObjectContext.objects.get_subclass(id=pk)
                if as2_object.reference.is_local and as2_object.replies is not None:
                    collection = as2_object.replies.get_by_context(CollectionContext)
                    collection.append(item=instance.reference)
            except Exception as exc:
                logger.warning(exc)


@receiver(post_save, sender=FollowRequest)
def on_follow_request_received_check_policies(sender, **kw):
    follow_request = kw["instance"]

    if not kw["created"] or follow_request.status != FollowRequest.STATUS.submitted:
        return

    if not follow_request.followed.is_local:
        return

    try:
        for reject_policy in app_settings.REJECT_FOLLOW_REQUEST_POLICIES:
            reject_policy(follower=follow_request.follower, target=follow_request.followed)
    except RejectedFollowRequest as e:
        logger.info(f"Follow request rejected: {str(e)}")
        follow_request.reject()
        return

    to_follow = follow_request.followed.get_by_context(Actor)

    if to_follow is not None and not to_follow.manually_approves_followers:
        follow_request.accept()


@receiver(post_save, sender=FollowRequest)
def on_follow_request_created_post_activity(sender, **kw):
    follow_request = kw["instance"]

    if not kw["created"]:
        return

    activity = ActivityContext.make(
        reference=follow_request.activity,
        type=ActivityContext.Types.FOLLOW,
        actor=follow_request.follower,
        object=follow_request.followed,
        published=timezone.now(),
    )
    activity.to.add(follow_request.followed)
    tasks.process_standard_activity_flows.delay(activity.reference.uri)
    tasks.post_activity.delay(activity.reference.uri)


@receiver(post_save, sender=Notification)
def on_notification_created_send_to_target(sender, **kw):
    if not kw["created"]:
        return

    instance = kw["instance"]

    if instance.target.is_local:
        return

    tasks.send_notification.delay(instance.id)


@receiver(notification_accepted, sender=Notification)
def on_notification_accepted_process_standard_flows(sender, **kw):
    notification = kw["notification"]

    tasks.process_standard_activity_flows(activity_uri=notification.resource.uri)


__all__ = (
    "on_new_remote_domain_fetch_nodeinfo",
    "on_new_local_domain_setup_nodeinfo",
    "on_follow_request_received_check_policies",
    "on_follow_request_created_post_activity",
    "on_notification_accepted_process_standard_flows",
    "on_notification_created_send_to_target",
    "set_default_port_for_domain",
)
