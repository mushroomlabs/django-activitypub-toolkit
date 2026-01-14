from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from activitypub.models import Reference

from .as2 import ActorContext


class Identity(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="identities", on_delete=models.CASCADE
    )
    actor = models.OneToOneField(ActorContext, related_name="identity", on_delete=models.CASCADE)
    is_primary = models.BooleanField(default=False)

    @property
    def reference(self) -> Reference:
        return self.actor.reference

    def clean(self):
        if not self.actor.reference.domain.local:
            raise ValidationError("Account must be on a local domain")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.actor.subject_name

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user",),
                condition=Q(is_primary=True),
                name="one_primary_identity_per_user",
            )
        ]


__all__ = ("Identity",)
