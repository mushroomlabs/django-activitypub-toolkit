import logging

from celery import shared_task
from django.db import transaction

from .models import Activity, Domain, Message, Reference

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
        domain = Domain.objects.get(name=domain_name)
        domain.get_nodeinfo()
    except Domain.DoesNotExist:
        logger.warning(f"Domain {domain_name} does not exist")


@shared_task
def process_standard_activity_flows(activity_uri):
    try:
        activity = Activity.objects.get(reference_id=activity_uri)
        activity.do()
    except Activity.DoesNotExist:
        logger.warning(f"Activity {activity_uri} does not exist")


@shared_task
def post_activity(activity_uri):
    try:
        activity = Activity.objects.get(reference_id=activity_uri)
        activity.post()
    except Activity.DoesNotExist:
        logger.warning(f"Activity {activity_uri} does not exist")
