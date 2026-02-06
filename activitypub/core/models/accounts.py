from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from activitypub.core.models import Domain, Reference

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
        verbose_name_plural = "Identities"
        constraints = [
            models.UniqueConstraint(
                fields=("user",),
                condition=Q(is_primary=True),
                name="one_primary_identity_per_user",
            )
        ]


class UserDomain(models.Model):
    domain = models.OneToOneField(Domain, related_name="user_domain", on_delete=models.CASCADE)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="domains",
        on_delete=models.CASCADE,
        help_text="Domains controlled by the user, hosted at this server",
    )

    def clean(self):
        if not self.domain.local:
            raise ValidationError("Only local domains can be assigned to users")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"domain: {self.domain.url} "


__all__ = ("Identity", "UserDomain")
