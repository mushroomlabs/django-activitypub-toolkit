from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Value
from django.db.models.functions import Concat

from activitypub.models import Reference

from .as2 import ActorContext


class AccountManager(models.Manager):
    def get_queryset(self) -> models.QuerySet:
        qs = super().get_queryset()
        return qs.annotate(
            _subject_name=Concat(
                Value("@"),
                "actor__preferred_username",
                Value("@"),
                "actor__reference__domain__name",
            ),
            local=F("actor__reference__domain__local"),
        )

    def get_by_subject_name(self, subject_name):
        username, domain = subject_name.split("@", 1)
        qs = super().get_queryset()
        return qs.filter(
            actor__preferred_username=username, actor__reference__domain__name=domain
        ).get()


class ActorAccount(AbstractBaseUser):
    actor = models.OneToOneField(
        ActorContext, related_name="user_account", on_delete=models.CASCADE
    )
    objects = AccountManager()

    @property
    def reference(self) -> Reference:
        return self.actor.reference

    @property
    def subject_name(self):
        if hasattr(self, "_subject_name"):
            return self._subject_name
        return f"{self.actor.preferred_username}@{self.reference.domain.name}"

    def get_username(self):
        return self.subject_name

    def clean(self):
        if not self.actor.reference.domain.local:
            raise ValidationError("Account must be on a local domain")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


__all__ = ("ActorAccount",)
