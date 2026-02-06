import datetime

import jwt
from activitypub.core.models import Domain, Identity
from django.conf import settings
from django.db import models
from model_utils.models import TimeStampedModel


class RegistrationApplication(TimeStampedModel):
    username = models.CharField(max_length=50)
    email_address = models.EmailField(null=True, blank=True)
    domain = models.ForeignKey(Domain, null=True, blank=True, on_delete=models.SET_NULL)
    answer = models.TextField()
    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="+",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    deny_reason = models.TextField(blank=True, null=True)


class LoginToken(TimeStampedModel):
    """
    Tracks active login sessions by storing JWT tokens.

    Matches Lemmy's login_token schema.
    """

    token = models.TextField(unique=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lemmy_login_tokens"
    )
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)

    @classmethod
    def make(cls, identity: Identity, **extra):
        ttl = settings.LEMMY_TOKEN_LIFETIME
        now = datetime.datetime.utcnow()

        payload = {
            "user_id": identity.user.id,
            "identity": identity.actor.subject_name,
            "iat": now,
            "exp": now + datetime.timedelta(seconds=ttl),
        }
        signing_key = settings.LEMMY_TOKEN_SIGNING_KEY
        token = jwt.encode(payload, signing_key, algorithm="HS256")
        return cls.objects.create(token=token, user=identity.user, **extra)

    def __str__(self):
        return f"LoginToken for {self.user.username} at {self.created}"


__all__ = ("RegistrationApplication", "LoginToken")
