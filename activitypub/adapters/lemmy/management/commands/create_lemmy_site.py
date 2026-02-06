import logging

from django.core.management.base import BaseCommand

from activitypub.adapters.lemmy.models import LocalSite

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sets up an AP Domain that can work as a Lemmy instance"

    def add_arguments(self, parser):
        parser.add_argument("-u", "--url", help="instance url")

    def handle(self, *args, **options):
        LocalSite.setup(options["url"])
