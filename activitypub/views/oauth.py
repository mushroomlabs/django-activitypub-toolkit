import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic.edit import FormView
from oauth2_provider.oauth2_validators import OAuth2Validator
from oauth2_provider.views.base import AuthorizationView as BaseAuthorizationView
from oauth_dcr.views import DynamicClientRegistrationView

from activitypub.forms import CreateIdentityForm
from activitypub.models import (
    ActorContext,
    Identity,
    OAuthAccessToken,
    OAuthClientApplication,
    OAuthRefreshToken,
    Reference,
)
from activitypub.settings import app_settings

logger = logging.getLogger(__name__)


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

    def save_bearer_token(self, token, request, *args, **kwargs):
        """
        Persist identity selection across OAuth flows.

        Without this, token refresh would lose the user's identity selection,
        forcing re-selection on every refresh. RefreshToken preserves identity
        across multiple access token generations.
        """
        super().save_bearer_token(token, request, *args, **kwargs)

        selected_identity_id = request.session.get("selected_identity_id")

        if not selected_identity_id:
            logger.error("Token issuance without identity", extra={"user_id": request.user.id})
            raise PermissionDenied("Identity required for request authorization")

        try:
            identity = request.user.identities.select_related("actor").get(id=selected_identity_id)
            try:
                refresh_token = OAuthRefreshToken.objects.get(
                    token=token["refresh_token"], user=request.user
                )
                refresh_token.identity = identity
                refresh_token.save(update_fields=["identity"])
                logger.info(
                    "Linked identity to OAuth Refresh Token",
                    extra={
                        "user_id": request.user.id,
                        "identity_id": selected_identity_id,
                        "token_id": refresh_token.id,
                    },
                )
            except (KeyError, OAuthRefreshToken.DoesNotExist):
                pass

            try:
                access_token = OAuthAccessToken.objects.get(
                    token=token["access_token"], user=request.user
                )
                access_token.identity = identity
                access_token.save(update_fields=["identity"])
                logger.info(
                    "Linked identity to OAuth Access Token",
                    extra={
                        "user_id": request.user.id,
                        "identity_id": selected_identity_id,
                        "token_id": access_token.id,
                    },
                )
            except (KeyError, OAuthAccessToken.DoesNotExist):
                pass

            del request.session["selected_identity_id"]

        except Identity.DoesNotExist:
            logger.error(
                "Invalid identity for token issuance",
                extra={"user_id": request.user.id, "identity_id": selected_identity_id},
            )
            raise PermissionDenied(
                f"Invalid identity {selected_identity_id} for user {request.user.id}"
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

        if hasattr(request, "access_token") and request.access_token:
            refresh_token = getattr(request.access_token, "source_refresh_token", None)
            if refresh_token:
                identity = getattr(refresh_token, "identity", None)
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
        raise PermissionDenied("Request does not have an associated identity.")


class ActivityPubDynamicClientRegistrationView(DynamicClientRegistrationView):
    """
    OAuth 2.0 Dynamic Client Registration with configurable access control.

    Supports three modes via FEDERATION['OAUTH_DYNAMIC_CLIENT_REGISTRATION']:
    - 'disabled': DCR endpoint returns 403 Forbidden
    - 'authentication_required': Only authenticated users can register
    - 'open': Anyone can register (RFC 7591 open mode, default)
    """

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
            user_id=user,
            client_type=metadata["client_type"],
            authorization_grant_type=metadata["authorization_grant_type"],
            redirect_uris=metadata.get("redirect_uris", ""),
            # RFC 7591 metadata fields
            client_uri=metadata.get("client_uri"),
            logo_uri=metadata.get("logo_uri"),
            policy_uri=metadata.get("policy_uri"),
            tos_uri=metadata.get("tos_uri"),
            software_id=metadata.get("software_id"),
            software_version=metadata.get("software_version"),
        )


class IdentitySelectionAuthorizationView(BaseAuthorizationView):
    template_name = "activitypub/oauth/authorize_identity.html"

    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().get(request, *args, **kwargs)

        identities = request.user.identities.select_related("actor").all()

        if not identities.exists():
            return render(
                request,
                "activitypub/oauth/no_identities.html",
                {
                    "client_id": request.GET.get("client_id"),
                    "redirect_uri": request.GET.get("redirect_uri"),
                },
            )

        if "identity_id" not in request.GET:
            context_data = {
                "identities": identities,
                "client_id": request.GET.get("client_id"),
                "scope": request.GET.get("scope"),
                "state": request.GET.get("state"),
                "redirect_uri": request.GET.get("redirect_uri"),
                "response_type": request.GET.get("response_type"),
                "code_challenge": request.GET.get("code_challenge"),
                "code_challenge_method": request.GET.get("code_challenge_method"),
            }
            return render(request, self.template_name, context_data)

        identity_id = request.GET.get("identity_id")
        try:
            identity = identities.get(id=identity_id)
        except ObjectDoesNotExist:
            raise PermissionDenied("Selected identity does not belong to the current user")

        request.session["selected_identity_id"] = identity.id

        return super().get(request, *args, **kwargs)


@method_decorator(login_required, name="dispatch")
class IdentityManagementView(View):
    template_name = "activitypub/oauth/identity_management.html"

    def get(self, request):
        identities = request.user.identities.select_related("actor__reference__domain").all()
        form = CreateIdentityForm(user=request.user)
        context_data = {"identities": identities, "form": form}
        return render(request, self.template_name, context_data)


class CreateIdentityView(LoginRequiredMixin, FormView):
    form_class = CreateIdentityForm
    template_name = "activitypub/oauth/identity_management.html"
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
