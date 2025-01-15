import json
import logging
import ssl

import requests
from celery import shared_task
from django.db import transaction

from .models import Activity, Domain, Message, Reference
from .serializers import NodeInfoSerializer

logger = logging.getLogger(__name__)


@shared_task
def clear_processed_messages():
    Message.objects.filter(processed=True).delete()


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
def process_message(message_id):
    try:
        message = Message.objects.get(id=message_id)
        if not message.is_verified:
            message.authenticate(fetch_missing_keys=True)
        message.process()
    except Message.DoesNotExist:
        logger.warning(f"Message {message_id} does not exist")


@shared_task
def fetch_nodeinfo(domain_name):
    try:
        NODEINFO_URLS = [
            "http://nodeinfo.diaspora.software/ns/schema/2.0",
            "http://nodeinfo.diaspora.software/ns/schema/2.1",
        ]
        domain = Domain.objects.get(name=domain_name)
        metadata_response = requests.get(f"https://{domain_name}/.well-known/nodeinfo")
        metadata_response.raise_for_status()
        metadata = metadata_response.json()

        for link in metadata.get("links", []):
            if link.get("rel") in NODEINFO_URLS:
                nodeinfo20_url = link.get("href")
                node_response = requests.get(nodeinfo20_url)
                node_response.raise_for_status()
                node_data = node_response.json()
                serializer = NodeInfoSerializer(data=node_data)
                assert serializer.is_valid(), "Could not parse node info data"
                software = serializer.data["software"]
                domain.nodeinfo = node_data
                domain.software_family = Domain.Software.get_family(software["name"])
                domain.software = software["name"]
                domain.version = software["version"]
                domain.save()
                break

    except (requests.HTTPError, ssl.SSLCertVerificationError, ssl.SSLError, json.JSONDecodeError):
        pass
    except Domain.DoesNotExist:
        logger.warning(f"Domain {domain_name} does not exist")


@shared_task
def process_standard_activity_flows(activity_uri):
    try:
        activity = Activity.objects.get(reference_id=activity_uri)
        actor = activity.actor and activity.actor.as2_item
        object = activity.object and activity.object.as2_item
        actor_uri = actor and actor.uri
        object_uri = object and object.uri
        match (actor_uri, activity.type, object_uri):
            case (_, Activity.Types.UNDO, _):
                activity.undo()
            case _:
                logger.info(f"No standard flow to execute for {activity_uri}")
    except Activity.DoesNotExist:
        logger.warning(f"Activity {activity_uri} does not exist")


@shared_task
def post_activity(activity_uri):
    try:
        activity = Activity.objects.get(reference_id=activity_uri)
        activity.post()
    except Activity.DoesNotExist:
        logger.warning(f"Activity {activity_uri} does not exist")
