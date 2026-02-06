import json
import logging
import uuid
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic.edit import FormView
from oauth2_provider.oauth2_backends import OAuthLibCore
from oauth2_provider.oauth2_validators import OAuth2Validator
from oauth2_provider.settings import oauth2_settings
from oauth2_provider.views.base import AuthorizationView
from oauth_dcr.views import DynamicClientRegistrationView

from activitypub.core.models import ActorContext, Identity, Reference
from activitypub.core.settings import app_settings

from .forms import CreateIdentityForm, IdentityAuthorizationForm
from .models import (
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthClientApplication,
    OAuthRefreshToken,
)

logger = logging.getLogger(__name__)


class ActivityPubOAuthServer(OAuthLibCore):
    def create_authorization_response(self, request, scopes, credentials, allow):
        selected_identity = getattr(request, "selected_identity", None)
        if selected_identity:
            credentials["identity"] = selected_identity

        return super().create_authorization_response(request, scopes, credentials, allow)

    def create_token_response(self, request):
        uri, headers, body, status = super().create_token_response(request)

        # Parse the token response body
        token_data = json.loads(body)

        # Get the access token and find its identity
        access_token = (
            OAuthAccessToken.objects.filter(token=token_data.get("access_token"))
            .select_related("identity__actor__reference")
            .first()
        )

        if access_token and access_token.identity:
            token_data["actor"] = access_token.identity.actor.reference.uri

        return uri, headers, json.dumps(token_data), status


class ActivityPubIdentityOAuth2Validator(OAuth2Validator):
    oidc_claim_scope = OAuth2Validator.oidc_claim_scope.copy()
    oidc_claim_scope.update(
        {
            "activitypub": [
                "sub",
                "preferred_username",
                "subject_username",
                "display_name",
                "profile",
                "identity_id",
            ]
        }
    )

    def _create_authorization_code(self, request, code, expires=None):
        if not expires:
            expires = timezone.now() + timedelta(
                seconds=oauth2_settings.AUTHORIZATION_CODE_EXPIRE_SECONDS
            )

        identity = getattr(request, "identity", None)
        if not identity:
            logger.error(
                "Authorization code creation without identity", extra={"user_id": request.user.id}
            )
            raise PermissionDenied("Identity required for authorization code creation")

        return OAuthAuthorizationCode.objects.create(
            application=request.client,
            user=request.user,
            code=code["code"],
            expires=expires,
            redirect_uri=request.redirect_uri,
            scope=" ".join(request.scopes),
            code_challenge=request.code_challenge or "",
            code_challenge_method=request.code_challenge_method or "",
            nonce=request.nonce or "",
            claims=json.dumps(request.claims or {}),
            identity=identity,
        )

    def _create_access_token(self, expires, request, token, source_refresh_token=None):
        if source_refresh_token:
            # Refresh flow - copy from existing token
            identity = source_refresh_token.identity
        else:
            # Initial authorization code exchange
            grant = OAuthAuthorizationCode.objects.get(code=request.code)
            identity = grant.identity

        id_token = token.get("id_token", None)
        if id_token:
            id_token = self._load_id_token(id_token)

        return OAuthAccessToken.objects.create(
            user=request.user,
            scope=token["scope"],
            expires=expires,
            token=token["access_token"],
            id_token=id_token,
            application=request.client,
            source_refresh_token=source_refresh_token,
            identity=identity,
        )

    def _create_refresh_token(
        self, request, refresh_token_code, access_token, previous_refresh_token
    ):
        if previous_refresh_token:
            identity = previous_refresh_token.identity
            token_family = previous_refresh_token.token_family
        else:
            grant = OAuthAuthorizationCode.objects.get(code=request.code)
            identity = grant.identity
            token_family = uuid.uuid4()

        return OAuthRefreshToken.objects.create(
            user=request.user,
            token=refresh_token_code,
            application=request.client,
            access_token=access_token,
            token_family=token_family,
            identity=identity,
        )

    def get_userinfo_claims(self, request):
        claims = super().get_userinfo_claims(request)

        identity = self._get_identity_for_request(request)
        claims["user_id"] = request.user.id

        if identity is not None:
            claims["sub"] = identity.actor.reference.uri
            claims["preferred_username"] = identity.actor.preferred_username
            claims["subject_username"] = identity.actor.subject_name
            claims["display_name"] = identity.actor.name
            claims["profile"] = identity.actor.reference.uri
            claims["identity_id"] = identity.id

        return claims

    def get_additional_claims(self, request):
        claims = super().get_additional_claims(request)

        identity = self._get_identity_for_request(request)

        if identity is not None:
            claims["sub"] = identity.actor.reference.uri
            claims["preferred_username"] = identity.actor.preferred_username
            claims["subject_username"] = identity.actor.subject_name
            claims["display_name"] = identity.actor.name
            claims["profile"] = identity.actor.reference.uri
            claims["identity_id"] = identity.id

        return claims

    def _get_identity_for_request(self, request):
        """
        request from authenticated users must have an identity, so we raise
        PermissionDenied if we can not find an identity on any of the tokens.
        """
        if hasattr(request, "access_token") and request.access_token:
            identity = getattr(request.access_token, "identity", None)
            if identity:
                return identity

        if hasattr(request, "id_token") and request.id_token:
            identity = getattr(request.id_token, "identity", None)
            if identity:
                return identity

        logger.warning(
            "Request without associated identity",
            extra={"user_id": getattr(request.user, "id", None)},
        )
        return None


class ActivityPubDynamicClientRegistrationView(DynamicClientRegistrationView):
    """
    OAuth 2.0 Dynamic Client Registration with configurable access control.

    Supports three modes via FEDERATION['OAUTH_DYNAMIC_CLIENT_REGISTRATION']:
    - 'disabled': DCR endpoint returns 403 Forbidden
    - 'authentication_required': Only authenticated users can register
    - 'open': Anyone can register (RFC 7591 open mode, default)
    """

    @csrf_exempt
    def dispatch(self, request, *args, **kwargs):
        """Check registration mode before processing request."""
        mode = app_settings.OAuth.dynamic_client_registration

        dcr_registration_modes = app_settings.OAuth.DynamicClientRegistration

        if mode == dcr_registration_modes.DISABLED:
            return JsonResponse(
                {
                    "error": "unauthorized_client",
                    "error_description": "Dynamic client registration is disabled on this server.",
                },
                status=403,
            )

        if (
            mode == dcr_registration_modes.AUTHENTICATION_REQUIRED
            and not request.user.is_authenticated
        ):
            return JsonResponse(
                {
                    "error": "unauthorized_client",
                    "error_description": "Authentication required for client registration.",
                },
                status=401,
            )

        return super().dispatch(request, *args, **kwargs)

    def _create_application(self, metadata):
        """
        Create application with user association if authenticated.

        User field is populated when:
        - Mode is 'authentication_required' (always authenticated)
        - Mode is 'open' AND user happens to be authenticated

        User field is NULL when:
        - Mode is 'open' AND user is anonymous
        """
        user = self.request.user if self.request.user.is_authenticated else None

        return OAuthClientApplication.objects.create(
            name=metadata.get("name", ""),
            user=user,
            client_type=metadata["client_type"],
            authorization_grant_type=metadata["authorization_grant_type"],
            redirect_uris=metadata.get("redirect_uris", ""),
            algorithm=metadata.get("algorithm", ""),
            # RFC 7591 metadata fields
            client_uri=metadata.get("client_uri"),
            logo_uri=metadata.get("logo_uri"),
            policy_uri=metadata.get("policy_uri"),
            tos_uri=metadata.get("tos_uri"),
            software_id=metadata.get("software_id"),
            software_version=metadata.get("software_version"),
        )


class IdentitySelectionAuthorizationView(AuthorizationView):
    template_name = "activitypub_oauth/authorize_identity.html"
    form_class = IdentityAuthorizationForm

    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().get(request, *args, **kwargs)

        identities = request.user.identities.select_related("actor").all()

        if not identities.exists():
            return render(
                request,
                "activitypub_oauth/no_identities.html",
                {
                    "client_id": request.GET.get("client_id"),
                    "redirect_uri": request.GET.get("redirect_uri"),
                },
            )
        return super().get(request, *args, **kwargs)

    def get_form(self, *args, **kw):
        initial = self.get_initial()
        return self.form_class(self.request.user, self.request.POST or None, initial=initial)

    def form_valid(self, form):
        identity = form.cleaned_data["identity"]
        self.request.selected_identity = identity
        return super().form_valid(form)

    def form_invalid(self, form):
        logger.error(f"Form invalid: {form.errors}")
        logger.error(f"Form data: {form.data}")
        return super().form_invalid(form)


@method_decorator(login_required, name="dispatch")
class IdentityManagementView(View):
    template_name = "activitypub_oauth/identity_management.html"

    def get(self, request):
        identities = request.user.identities.select_related("actor__reference__domain").all()
        form = CreateIdentityForm(user=request.user)
        context_data = {"identities": identities, "form": form}
        return render(request, self.template_name, context_data)


class CreateIdentityView(LoginRequiredMixin, FormView):
    form_class = CreateIdentityForm
    template_name = "activitypub_oauth/identity_management.html"
    success_url = reverse_lazy("identity_management")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        domain = form.cleaned_data["domain"]
        preferred_username = form.cleaned_data["preferred_username"]
        display_name = form.cleaned_data.get("display_name") or preferred_username
        actor_type = form.cleaned_data.get("actor_type") or ActorContext.Types.PERSON
        actor_path = form.cleaned_data["actor_path"]

        # Create Reference for the new actor
        reference = Reference.objects.create(uri=f"{domain.url}/{actor_path}", domain=domain)

        actor = ActorContext.objects.create(
            reference=reference,
            type=actor_type,
            preferred_username=preferred_username,
            name=display_name,
        )

        is_primary = not self.request.user.identities.exists()
        Identity.objects.create(user=self.request.user, actor=actor, is_primary=is_primary)

        messages.success(self.request, f"Identity {actor.subject_name} created!")

        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, "Please correct the errors below.")
        identities = self.request.user.identities.select_related("actor__reference__domain").all()
        context_data = {"identities": identities, "form": form}
        return render(self.request, self.template_name, context_data)


__all__ = (
    "ActivityPubDynamicClientRegistrationView",
    "CreateIdentityView",
    "IdentityManagementView",
    "IdentitySelectionAuthorizationView",
)
