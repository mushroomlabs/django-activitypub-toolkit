import copy
import logging

import requests

from .exceptions import DocumentPublishingError, UnauthenticatedPublisher
from .models import Reference, SecV1Context
from .settings import app_settings

logger = logging.getLogger(__name__)


class DocumentPublisher:
    @classmethod
    def can_publish_to(cls, target: Reference, sender: Reference | None = None):
        return False


class HttpDocumentPublisher(DocumentPublisher):
    @classmethod
    def can_publish_to(cls, target: Reference, sender: Reference | None = None):
        return target.uri.startswith("http://") or target.uri.startswith("https://")

    @classmethod
    def publish(cls, data, target: Reference, sender: Reference):
        signing_key = SecV1Context.valid.filter(owner=sender).first()

        if signing_key is None:
            logger.warning(
                f"No valid signing key provided. Publishing to {target} without signature"
            )

        logger.info(f"Sending message to {target.uri}")
        headers = {"Content-Type": "application/ld+json"}
        try:
            response = requests.post(
                target.uri,
                json=data,
                headers=headers,
                auth=signing_key and signing_key.signed_request_auth,
            )

            if response.status_code == 401:
                raise UnauthenticatedPublisher("Authentication Required")
            response.raise_for_status()
        except (requests.HTTPError, requests.ConnectTimeout) as exc:
            raise DocumentPublishingError from exc


def publish(data, target: Reference, sender: Reference):
    for klass in DocumentPublisher.__subclasses__():
        if klass.can_publish_to(target=target, sender=sender):
            # Apply document processors
            document = copy.deepcopy(data)
            for adapter in app_settings.DOCUMENT_PROCESSORS:
                adapter.process_outgoing(document)

            return klass.publish(data=document, target=target, sender=sender)
        raise DocumentPublishingError("No document publisher class found")
