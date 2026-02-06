import logging

from activitypub.core.contexts import AS2
from activitypub.core.models import Reference, ActivityContext, ActorContext
from activitypub.publishers import publish
from celery import shared_task

from .models.core import LemmyObject
from .projections import lemmy_projection_selector

logger = logging.getLogger(__name__)


@shared_task
def publish_lemmy_object(lemmy_object_id, viewer_uri: str = str(AS2.Public)):
    obj = LemmyObject.objects.get_subclass(id=lemmy_object_id)
    viewer = Reference.make(viewer_uri)
    for actor_ref in obj.as2.attributed_to.all():
        activity_ref = ActivityContext.generate_reference(domain=obj.reference.domain)
        activity = ActivityContext.make(
            reference=activity_ref,
            type=ActivityContext.Types.CREATE,
            object=obj.reference,
            actor=actor_ref,
        )
        activity.cc.set(obj.as2.audience.all())
        activity.to.add(viewer)
        activity.audience.set(obj.as2.audience.all())

        projection_class = lemmy_projection_selector(reference=activity_ref)
        projection = projection_class(reference=activity_ref, scope={"viewer": viewer})
        projection.build()

        document = projection.get_compacted()

        for audience_ref in obj.as2.audience.all():
            try:
                audience_ref.resolve()
                audience_actor = audience_ref.get_by_context(ActorContext)
                if audience_actor is None:
                    raise AssertionError(f"Could not find actor for {audience_ref}")

                if audience_actor.inbox is None:
                    raise AssertionError(f"{audience_ref} has no inbox")

                publish(data=document, target=audience_actor.inbox, sender=activity.actor)
            except AssertionError as exc:
                logger.warning(str(exc))


__all__ = ("publish_lemmy_object",)
