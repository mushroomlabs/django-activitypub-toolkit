import logging
from pathlib import Path

from django.apps import AppConfig
from pyld import jsonld

logger = logging.getLogger(__name__)


class ActivityPubConfig(AppConfig):
    name = "activitypub"
    path = str(Path(__file__).parent)

    def ready(self):
        from . import handlers  # noqa
        from . import signals  # noqa
        from .schemas import builtin_document_loader, secure_rdflib

        secure_rdflib()
        jsonld.set_document_loader(builtin_document_loader)
