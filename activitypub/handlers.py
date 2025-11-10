import logging

from django.db.models.signals import m2m_changed, post_save, pre_save
from django.dispatch import receiver

from . import tasks
from .models.ap import ActivityPubServer, Actor, FollowRequest
from .models.as2 import BaseAs2ObjectContext, ObjectContext
from .models.collections import CollectionContext
from .models.linked_data import Domain, Notification
from .signals import notification_accepted

logger = logging.getLogger(__name__)


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


@receiver(m2m_changed, sender=BaseAs2ObjectContext.in_reply_to.through)
@receiver(m2m_changed, sender=ObjectContext.in_reply_to.through)
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
def on_follow_request_created_check_if_it_can_be_accepted(sender, **kw):
    follow_request = kw["instance"]

    if kw["created"] and follow_request.status == FollowRequest.STATUS.pending:
        to_follow = follow_request.activity.object.get_by_context(Actor)
        if not to_follow.manually_approves_followers:
            follow_request.accept()


@receiver(notification_accepted, sender=Notification)
def on_notification_accepted_process_standard_flows(sender, **kw):
    notification = kw["notification"]

    tasks.process_standard_activity_flows(activity_uri=notification.resource.uri)


__all__ = (
    "on_new_remote_domain_fetch_nodeinfo",
    "on_new_local_domain_setup_nodeinfo",
    "on_follow_request_created_check_if_it_can_be_accepted",
    "on_notification_accepted_process_standard_flows",
)
