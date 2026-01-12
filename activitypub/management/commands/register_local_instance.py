import logging

from django.core.management.base import BaseCommand

from activitypub.models import Domain

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Register an instance as local domain"

    def add_arguments(self, parser):
        parser.add_argument("-u", "--url", help="instance url")

    def handle(self, *args, **options):
        Domain.make(options["url"], local=True)
