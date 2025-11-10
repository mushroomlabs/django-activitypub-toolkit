import logging

import requests
from celery import shared_task
from django.db import transaction

from .exceptions import DropMessage, UnprocessableJsonLd
from .frames import FrameRegistry
from .models import (
    Activity,
    CollectionContext,
    LinkedDataDocument,
    Notification,
    NotificationProcessResult,
    Reference,
)
from .models.ap import ActivityPubServer, Actor
from .models.secv1 import SecV1Context
from .schemas import AS2
from .serializers import LinkedDataSerializer
from .settings import app_settings
from .signals import notification_accepted

logger = logging.getLogger(__name__)


@shared_task
def clear_processed_messages():
    Notification.objects.filter(processed=True).delete()


@shared_task
def resolve_reference(uri, force=False):
    try:
        reference = Reference.objects.get(uri=uri)
        with transaction.atomic():
            reference.resolve(force=force)
    except Reference.DoesNotExist:
        logger.exception(f"Reference {uri} does not exist")
    except Exception as exc:
        logger.exception(f"Failed to resolve item on {uri}: {exc}")


@shared_task
def process_incoming_notification(notification_id):
    try:
        notification = Notification.objects.get(id=notification_id)
        document = LinkedDataDocument.objects.get(reference=notification.resource)

        for processor in app_settings.MESSAGE_PROCESSORS:
            processor.process_incoming(document.data)

        # Load context models from the document
        document.load()
        notification.sender.resolve()
        notification_accepted.send(notification=notification, sender=Notification)
        box = CollectionContext.objects.get(reference=notification.target)
        box.append(item=notification.resource)
        return notification.results.create(result=NotificationProcessResult.Types.OK)
    except CollectionContext.DoesNotExist:
        return notification.results.create(result=NotificationProcessResult.Types.BAD_TARGET)
    except UnprocessableJsonLd:
        return notification.results.create(result=NotificationProcessResult.Types.BAD_REQUEST)
    except DropMessage:
        return notification.results.create(result=NotificationProcessResult.Types.DROPPED)
    except (Notification.DoesNotExist, LinkedDataDocument.DoesNotExist):
        logger.warning("Not found")
        return


@shared_task
def send_notification(notification_id):
    """ """
    try:
        notification = Notification.objects.get(id=notification_id)

        signing_key = SecV1Context.valid.filter(owner__uri=notification.sender.uri).first()

        assert signing_key is not None, "Could not find valid key pair for sender"

        inbox_owner = Actor.objects.filter(outbox=notification.target).first()

        viewer = inbox_owner and inbox_owner.reference or Reference.make(str(AS2.Public))

        serializer = LinkedDataSerializer(
            instance=notification.resource, context={"viewer": viewer}
        )
        document = FrameRegistry.auto_frame(serializer).to_framed_document()

        for adapter in app_settings.MESSAGE_PROCESSORS:
            adapter.process_outgoing(document)

        logger.info(f"Sending message to {notification.recipient.uri}")
        headers = {"Content-Type": "application/activity+json"}
        response = requests.post(
            notification.target.uri,
            json=notification.document,
            headers=headers,
            auth=signing_key.signed_request_auth,
        )
        assert response.status_code != 401
        response.raise_for_status()
        return notification.results.create(result=NotificationProcessResult.Types.OK)
    except AssertionError:
        return notification.results.create(result=NotificationProcessResult.Types.UNAUTHENTICATED)
    except requests.HTTPError:
        return notification.results.create(result=NotificationProcessResult.Types.BAD_REQUEST)


@shared_task
def fetch_nodeinfo(domain_id):
    try:
        instance, _ = ActivityPubServer.objects.get_or_create(domain_id=domain_id)
        instance.get_nodeinfo()
    except ActivityPubServer.DoesNotExist:
        logger.warning(f"Domain {domain_id} does not exist")


@shared_task
def process_standard_activity_flows(activity_uri):
    try:
        activity = Activity.objects.get(reference__uri=activity_uri)
        activity.do()
    except Activity.DoesNotExist:
        logger.warning(f"Activity {activity_uri} does not exist")


# @shared_task
# def post_activity(activity_uri):
#     try:
#         self.do()
#         actor = self.actor and self.actor.get_by_context(ActorContext)
#         assert actor is not None, f"Activity {self.uri} has no actor"
#         assert actor.reference.is_local, f"Activity {self.uri} is not from a local actor"
#         for inbox in actor.followers_inboxes:
#             Notification.objects.create(
#                 resource=self.reference, sender=actor.reference, target=inbox
#             )
#         # We add the posted activity to the actor outbox if Public
#         # is part of the intended audience
#         # if self.is_intended_audience(Actor.PUBLIC):
#         #    actor.outbox.append(self)
#         activity = Activity.objects.get(reference__uri=activity_uri)
#     except AssertionError as exc:
#         logger.warning(exc)
#     except Activity.DoesNotExist:
#         logger.warning(f"Activity {activity_uri} does not exist")
