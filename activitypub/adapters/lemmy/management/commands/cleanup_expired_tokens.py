from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from activitypub.adapters.lemmy.models import LoginToken


class Command(BaseCommand):
    help = "Delete expired JWT tokens from LoginToken table"

    def handle(self, *args, **options):
        cutoff_time = timezone.now() - timedelta(seconds=settings.LEMMY_TOKEN_LIFETIME)

        LoginToken.objects.filter(created__lte=cutoff_time).delete()

        self.stdout.write(self.style.SUCCESS(f"Deleted all tokens created before {cutoff_time}"))
