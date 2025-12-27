import logging

from django.core.management.base import BaseCommand

from activitypub.models import Reference

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Manually resolve references"

    def add_arguments(self, parser):
        parser.add_argument("uris", type=str, nargs="*", help="Reference URIs")

    def handle(self, *args, **options):
        uris = options["uris"]

        for uri in uris:
            logger.info(f"Resolving: {uri}")
            reference = Reference.make(uri)
            reference.resolve()
