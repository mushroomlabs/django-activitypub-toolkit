import logging

from django.db.models.signals import post_save, pre_save, m2m_changed
from django.dispatch import receiver

from . import tasks
from .models import Activity, CoreType, Domain, Object, FollowRequest
from .signals import activity_received


logger = logging.getLogger(__name__)


@receiver(post_save, sender=Domain)
def on_domain_created_fetch_nodeinfo(sender, **kw):
    domain = kw["instance"]

    if kw["created"]:
        tasks.fetch_nodeinfo.delay(domain_name=domain.name)


@receiver(pre_save, sender=Activity)
@receiver(pre_save, sender=Object)
def on_ap_object_create_define_related_collections(sender, **kw):
    instance = kw["instance"]
    reference = instance.reference

    if reference is None:
        return

    if reference.is_remote:
        return

    if type(instance) is Object or instance.type == Activity.Types.QUESTION:
        if not instance.replies:
            instance.replies = reference.domain.build_collection(
                paginated=True, name=f"Replies to {reference.uri}"
            )

        if not instance.shares:
            instance.shares = reference.domain.build_collection(
                paginated=True, name=f"shares for {reference.uri}"
            )

        if not instance.likes:
            instance.likes = reference.domain.build_collection(
                paginated=True, name=f"Likes for {reference.uri}"
            )


@receiver(m2m_changed, sender=CoreType.in_reply_to.through)
def on_new_reply_add_to_replies_collection(sender, **kw):
    action = kw["action"]
    instance = kw["instance"]
    pk_set = kw["pk_set"]
    if action == "post_add":
        for pk in pk_set:
            try:
                as2_item = CoreType.objects.get_subclass(id=pk)
                if as2_item.reference.is_local and as2_item.replies is not None:
                    as2_item.replies.append(instance)
            except Exception as exc:
                logger.warning(exc)


@receiver(activity_received, sender=Activity)
def on_activity_received_process_standard_flows(sender, **kw):
    activity = kw["activity"]

    tasks.process_standard_activity_flows(activity_uri=activity.uri)


@receiver(post_save, sender=FollowRequest)
def on_follow_request_created_check_if_it_can_be_accepted(sender, **kw):
    follow_request = kw["instance"]

    if kw["created"] and follow_request.status == FollowRequest.STATUS.pending:
        to_follow = follow_request.followed
        if not to_follow.manually_approves_followers:
            follow_request.accept()


__all__ = (
    "on_domain_created_fetch_nodeinfo",
    "on_ap_object_create_define_related_collections",
    "on_activity_received_process_standard_flows",
    "on_follow_request_created_check_if_it_can_be_accepted",
)
