import logging

from django.core.management.base import BaseCommand

from activitypub.core.models import Reference
from activitypub.core.tasks import run_webfinger_lookup

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Manually resolve a Lemmy actor (person or community) for testing"

    def add_arguments(self, parser):
        parser.add_argument(
            "query",
            type=str,
            help="Query string: @user@domain, !community@domain, or URI",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force re-resolution even if already exists",
        )

    def handle(self, *args, **options):
        query = options["query"]

        logger.info(f"Resolving: {query}")

        # Check if it's a subject_name (@user@domain or !community@domain)
        is_subject_name = query.startswith("@") or query.startswith("!")

        if is_subject_name:
            username, domain = query.split("@", 1)
            username = username[1:]

            run_webfinger_lookup(f"{username}@{domain}")

        else:
            Reference.make(query)
