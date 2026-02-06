import logging

from activitypub.core.exceptions import RejectedFollowRequest
from activitypub.core.models import Reference

from .models import Community

logger = logging.getLogger(__name__)


def can_follow_community(follower: Reference, target: Reference):
    """
    Validate follow request for Lemmy communities.

    Args:
        follower: Reference to the actor who wants to follow target
        target: Reference to the target being followed (Community)

    Raises:
        RejectedFollowRequest: If the follow should be rejected
    """

    community = Community.objects.filter(reference=target).first()

    if community is None:
        return

    if community.site:
        person_domain = follower.domain
        if community.site.blocked_instances.filter(id=person_domain.id).exists():
            raise RejectedFollowRequest(
                f"{follower.domain} is blocked by {target.domain} instance"
            )

    if community.visibility == Community.VisibilityTypes.LOCAL:
        if not follower.is_local:
            raise RejectedFollowRequest("This is a local-only community")

    if community.removed or community.deleted:
        raise RejectedFollowRequest("This community is not available")
