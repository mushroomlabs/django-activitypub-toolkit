from django.db import models
from oauth2_provider.models import (
    AbstractAccessToken,
    AbstractApplication,
    AbstractGrant,
    AbstractIDToken,
    AbstractRefreshToken,
)

from .accounts import Identity


class OAuthClientApplication(AbstractApplication):
    client_uri = models.URLField(null=True, blank=True)
    logo_uri = models.URLField(null=True, blank=True)
    policy_uri = models.URLField(null=True, blank=True)
    tos_uri = models.URLField(null=True, blank=True)
    software_id = models.CharField(max_length=255, null=True, blank=True)
    software_version = models.CharField(max_length=100, null=True, blank=True)
    metadata_uri = models.URLField(null=True, blank=True)

    class Meta:
        verbose_name = "OAuth Client Application"
        verbose_name_plural = "OAuth Client Applications"


class OAuthAccessToken(AbstractAccessToken):
    identity = models.ForeignKey(
        Identity, related_name="oauth_access_tokens", on_delete=models.CASCADE
    )

    def __str__(self):
        return f"Token for {self.identity.actor.subject_name}"

    class Meta:
        verbose_name = "OAuth Access Token"
        verbose_name_plural = "OAuth Access Tokens"


class OAuthRefreshToken(AbstractRefreshToken):
    identity = models.ForeignKey(
        Identity, related_name="oauth_refresh_tokens", on_delete=models.CASCADE
    )

    class Meta:
        verbose_name = "OAuth Refresh Token"
        verbose_name_plural = "OAuth Refresh Tokens"


class OAuthAuthorizationCode(AbstractGrant):
    identity = models.ForeignKey(
        Identity, related_name="oauth_authorization_codes", on_delete=models.CASCADE
    )

    class Meta:
        verbose_name = "OAuth Authorization Code"
        verbose_name_plural = "OAuth Authorization Codes"


class OidcIdentityToken(AbstractIDToken):
    identity = models.ForeignKey(Identity, related_name="oidc_id_tokens", on_delete=models.CASCADE)

    def __str__(self):
        return f"Token for {self.identity.actor.subject_name}"

    class Meta:
        verbose_name = "OIDC ID Token"
        verbose_name_plural = "OIDC ID Tokens"


__all__ = (
    "OAuthAccessToken",
    "OAuthAuthorizationCode",
    "OAuthClientApplication",
    "OAuthRefreshToken",
    "OidcIdentityToken",
)
