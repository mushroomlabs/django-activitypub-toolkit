import logging

import requests
from celery import shared_task
from django.db import transaction

from .contexts import AS2
from .exceptions import (
    DocumentPublishingError,
    DropMessage,
    UnauthenticatedPublisher,
    UnprocessableJsonLd,
)
from .models import (
    Activity,
    CollectionContext,
    LinkedDataDocument,
    Notification,
    NotificationProcessResult,
    Reference,
)
from .models.ap import ActivityPubServer, Actor
from .publishers import publish
from .settings import app_settings
from .signals import notification_accepted

logger = logging.getLogger(__name__)


@shared_task
def clear_processed_messages():
    Notification.objects.filter(processed=True).delete()


@shared_task
def webfinger_lookup(subject_name: str):
    try:
        username, domain = subject_name.split("@", 1)
        webfinger_url = f"https://{domain}/.well-known/webfinger?resource=acct:{subject_name}"

        response = requests.get(
            webfinger_url, headers={"Accept": "application/jrd+json"}, timeout=10
        )
        response.raise_for_status()
        data = response.json()

        # Find the self link with application/activity+json type
        for link in data.get("links", []):
            if link.get("rel") == "self" and "activity+json" in link.get("type", ""):
                uri = link.get("href")
                with transaction.atomic():
                    reference = Reference.make(uri)
                    reference.resolve(force=True)

    except (requests.RequestException, ValueError, KeyError) as e:
        logger.warning(f"Webfinger lookup failed for {subject_name}: {e}")


@shared_task
def resolve_reference(uri, force=True):
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
        notification.authenticate(fetch_missing_keys=True)
        document = LinkedDataDocument.objects.get(reference=notification.resource)

        for processor in app_settings.DOCUMENT_PROCESSORS:
            processor.process_incoming(document.data)

        # Load context models from the document
        document.load()
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
    try:
        notification = Notification.objects.select_related("sender__domain", "target__domain").get(
            id=notification_id
        )

        if notification.target.is_local:
            logger.info(f"{notification.target.uri} is a local target. Skipping request")
            return

        inbox_owner = Actor.objects.filter(inbox=notification.target).first()

        viewer = inbox_owner and inbox_owner.reference or Reference(uri=str(AS2.Public))

        # Select projection class
        projection_class = app_settings.PROJECTION_SELECTOR(reference=notification.resource)
        # Serialize to JSON-LD using projection
        projection = projection_class(reference=notification.resource, scope={"viewer": viewer})
        projection.build()
        compacted_document = projection.get_compacted()

        publish(data=compacted_document, target=notification.target, sender=notification.sender)
        return notification.results.create(result=NotificationProcessResult.Types.OK)
    except UnauthenticatedPublisher:
        return notification.results.create(result=NotificationProcessResult.Types.UNAUTHENTICATED)
    except DocumentPublishingError:
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


@shared_task
def post_activity(activity_uri):
    try:
        activity = Activity.objects.get(reference__uri=activity_uri)
        actor = activity.actor and activity.actor.get_by_context(Actor)
        assert actor is not None, f"Activity {activity.uri} has no actor"
        assert actor.reference.is_local, f"Activity {activity.uri} is not from a local actor"
        for inbox in actor.followers_inboxes:
            Notification.objects.create(
                resource=activity.reference, sender=actor.reference, target=inbox
            )

        outbox_collection = actor.outbox.get_by_context(CollectionContext)
        assert outbox_collection is not None, "Actor has no outbox"
        outbox_collection.append(activity.reference)
    except AssertionError as exc:
        logger.warning(exc)
    except Activity.DoesNotExist:
        logger.warning(f"Activity {activity_uri} does not exist")
