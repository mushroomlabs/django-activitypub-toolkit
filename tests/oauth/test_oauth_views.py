from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.utils import timezone

from activitypub.core.factories import DomainFactory, IdentityFactory, UserFactory
from activitypub.extras.oauth.models import (
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthClientApplication,
    OAuthRefreshToken,
)
from activitypub.extras.oauth.views import ActivityPubIdentityOAuth2Validator
from tests.core.base import BaseTestCase


User = get_user_model()


class OAuthIdentityLinkingTestCase(BaseTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.validator = ActivityPubIdentityOAuth2Validator()
        self.user = UserFactory()
        self.domain = DomainFactory(local=True, scheme="http", name="testserver")
        self.identity = IdentityFactory(user=self.user, actor__reference__domain=self.domain)
        self.application = OAuthClientApplication.objects.create(
            name="Test App",
            client_type=OAuthClientApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthClientApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://localhost:8000/callback",
        )

    def test_create_authorization_code_with_identity(self):
        """Authorization code should be created with identity from request"""
        request = Mock()
        request.user = self.user
        request.client = self.application
        request.identity = self.identity
        request.redirect_uri = "http://localhost:8000/callback"
        request.scopes = ["read", "write"]
        request.code_challenge = "test-challenge"
        request.code_challenge_method = "S256"
        request.nonce = "test-nonce"
        request.claims = {}

        code_dict = {"code": "test-auth-code-123"}
        expires = timezone.now() + timedelta(minutes=10)

        auth_code = self.validator._create_authorization_code(request, code_dict, expires)

        self.assertEqual(auth_code.code, "test-auth-code-123")
        self.assertEqual(auth_code.identity, self.identity)
        self.assertEqual(auth_code.user, self.user)
        self.assertEqual(auth_code.application, self.application)

    def test_create_authorization_code_raises_error_without_identity(self):
        """Should raise PermissionDenied when request has no identity"""
        request = Mock(
            spec=[
                "user",
                "client",
                "redirect_uri",
                "scopes",
                "code_challenge",
                "code_challenge_method",
                "nonce",
                "claims",
            ]
        )
        request.user = self.user
        request.client = self.application
        request.redirect_uri = "http://localhost:8000/callback"
        request.scopes = ["read", "write"]
        request.code_challenge = ""
        request.code_challenge_method = ""
        request.nonce = ""
        request.claims = {}

        code_dict = {"code": "test-auth-code-456"}

        with self.assertRaises(PermissionDenied):
            self.validator._create_authorization_code(request, code_dict)

    def test_create_access_token_from_authorization_code(self):
        """Access token should inherit identity from authorization code"""
        # Create authorization code with identity
        OAuthAuthorizationCode.objects.create(
            application=self.application,
            user=self.user,
            code="test-auth-code",
            expires=timezone.now() + timedelta(minutes=10),
            redirect_uri="http://localhost:8000/callback",
            scope="read write",
            identity=self.identity,
        )

        request = Mock()
        request.user = self.user
        request.client = self.application
        request.code = "test-auth-code"

        token_dict = {
            "access_token": "test-access-token-123",
            "scope": "read write",
        }
        expires = timezone.now() + timedelta(hours=1)

        access_token = self.validator._create_access_token(
            expires, request, token_dict, source_refresh_token=None
        )

        self.assertEqual(access_token.token, "test-access-token-123")
        self.assertEqual(access_token.identity, self.identity)
        self.assertEqual(access_token.user, self.user)

    def test_create_access_token_from_refresh_token(self):
        """Access token should inherit identity from refresh token on refresh"""
        # Create refresh token with identity
        refresh_token = OAuthRefreshToken.objects.create(
            user=self.user,
            application=self.application,
            token="test-refresh-token",
            identity=self.identity,
        )

        request = Mock()
        request.user = self.user
        request.client = self.application

        token_dict = {
            "access_token": "refreshed-access-token-456",
            "scope": "read write",
        }
        expires = timezone.now() + timedelta(hours=1)

        access_token = self.validator._create_access_token(
            expires, request, token_dict, source_refresh_token=refresh_token
        )

        self.assertEqual(access_token.token, "refreshed-access-token-456")
        self.assertEqual(access_token.identity, self.identity)
        self.assertEqual(access_token.source_refresh_token, refresh_token)

    def test_create_refresh_token_initial_grant(self):
        """Initial refresh token should get identity from authorization code"""
        # Create authorization code with identity
        OAuthAuthorizationCode.objects.create(
            application=self.application,
            user=self.user,
            code="test-auth-code",
            expires=timezone.now() + timedelta(minutes=10),
            redirect_uri="http://localhost:8000/callback",
            scope="read write",
            identity=self.identity,
        )

        # Create access token
        access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.application,
            token="test-access-token",
            expires=timezone.now() + timedelta(hours=1),
            identity=self.identity,
        )

        request = Mock()
        request.user = self.user
        request.client = self.application
        request.code = "test-auth-code"

        refresh_token = self.validator._create_refresh_token(
            request, "test-refresh-token-789", access_token, previous_refresh_token=None
        )

        self.assertEqual(refresh_token.token, "test-refresh-token-789")
        self.assertEqual(refresh_token.identity, self.identity)
        self.assertIsNotNone(refresh_token.token_family)

    def test_create_refresh_token_preserves_identity(self):
        """Refresh token rotation should preserve identity and token_family"""
        # Create initial refresh token with identity and token_family
        import uuid

        token_family = uuid.uuid4()
        previous_refresh_token = OAuthRefreshToken.objects.create(
            user=self.user,
            application=self.application,
            token="old-refresh-token",
            identity=self.identity,
            token_family=token_family,
        )

        # Create new access token
        new_access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.application,
            token="new-access-token",
            expires=timezone.now() + timedelta(hours=1),
            identity=self.identity,
            source_refresh_token=previous_refresh_token,
        )

        request = Mock()
        request.user = self.user
        request.client = self.application

        new_refresh_token = self.validator._create_refresh_token(
            request,
            "new-refresh-token-999",
            new_access_token,
            previous_refresh_token=previous_refresh_token,
        )

        self.assertEqual(new_refresh_token.token, "new-refresh-token-999")
        self.assertEqual(new_refresh_token.identity, self.identity)
        self.assertEqual(new_refresh_token.token_family, token_family)

    def test_get_identity_from_access_token(self):
        """Should retrieve identity directly from AccessToken"""
        request = Mock()
        access_token = Mock()
        access_token.identity = self.identity
        request.access_token = access_token

        result = self.validator._get_identity_for_request(request)

        self.assertEqual(result, self.identity)

    def test_get_identity_from_id_token(self):
        """Should retrieve identity from IDToken for OIDC flows"""
        request = Mock()
        # No access_token
        request.access_token = None

        # Has ID token with identity
        id_token = Mock()
        id_token.identity = self.identity
        request.id_token = id_token

        result = self.validator._get_identity_for_request(request)

        self.assertEqual(result, self.identity)

    def test_no_identity(self):
        """no identity if not associated with the tokens"""
        request = Mock()
        request.user = self.user
        request.access_token = None
        request.id_token = None

        self.assertIsNone(self.validator._get_identity_for_request(request))

    def test_get_identity_priority_access_token_over_id_token(self):
        """AccessToken.identity should take priority over IDToken.identity"""
        identity_from_access_token = self.identity
        identity_from_id_token = IdentityFactory(
            user=self.user, actor__reference__domain__local=True, is_primary=False
        )

        request = Mock()

        # Set up access token with identity
        access_token = Mock()
        access_token.identity = identity_from_access_token
        access_token.source_refresh_token = None
        request.access_token = access_token

        # Set up ID token with different identity
        id_token = Mock()
        id_token.identity = identity_from_id_token
        request.id_token = id_token

        result = self.validator._get_identity_for_request(request)

        # Should use access_token identity, not id_token
        self.assertEqual(result, identity_from_access_token)
        self.assertNotEqual(result, identity_from_id_token)

    def test_identity_persists_across_token_refresh(self):
        """
        Identity should persist when tokens are refreshed.
        Access tokens created via refresh flow have identity directly set.
        """
        # Create initial refresh token with identity
        refresh_token = OAuthRefreshToken.objects.create(
            user=self.user,
            application=self.application,
            token="original-refresh-token",
            identity=self.identity,
        )

        # Simulate token refresh: new access token created with identity directly set
        new_access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.application,
            token="refreshed-access-token",
            expires=timezone.now() + timedelta(hours=1),
            identity=self.identity,
            source_refresh_token=refresh_token,
        )

        # Create request with refreshed access token
        request = Mock()
        request.access_token = new_access_token

        # Should retrieve identity directly from access token
        result = self.validator._get_identity_for_request(request)

        self.assertEqual(result, self.identity)
        # Verify identity is directly set on access token, not via fallback
        self.assertEqual(new_access_token.identity, self.identity)


class OAuthUserinfoClaimsTestCase(BaseTestCase):
    def setUp(self):
        self.validator = ActivityPubIdentityOAuth2Validator()
        self.user = UserFactory()
        self.domain = DomainFactory(local=True, scheme="http", name="testserver")
        self.identity = IdentityFactory(user=self.user, actor__reference__domain=self.domain)

    def test_get_userinfo_claims_includes_activitypub_identity(self):
        """Userinfo claims should include ActivityPub identity information"""
        request = Mock()
        request.user = self.user
        access_token = Mock()
        access_token.identity = self.identity
        request.access_token = access_token

        # Mock parent method
        with patch.object(
            ActivityPubIdentityOAuth2Validator.__bases__[0], "get_userinfo_claims", return_value={}
        ):
            claims = self.validator.get_userinfo_claims(request)

        self.assertEqual(claims["user_id"], self.user.id)
        self.assertEqual(claims["sub"], self.identity.actor.reference.uri)
        self.assertEqual(claims["preferred_username"], self.identity.actor.preferred_username)
        self.assertEqual(claims["subject_username"], self.identity.actor.subject_name)
        self.assertEqual(claims["display_name"], self.identity.actor.name)
        self.assertEqual(claims["profile"], self.identity.actor.reference.uri)
        self.assertEqual(claims["identity_id"], self.identity.id)

    def test_get_additional_claims_includes_activitypub_identity(self):
        """Additional claims (for ID token) should include ActivityPub identity information"""
        request = Mock()
        request.user = self.user
        access_token = Mock()
        access_token.identity = self.identity
        request.access_token = access_token

        # Mock parent method
        with patch.object(
            ActivityPubIdentityOAuth2Validator.__bases__[0],
            "get_additional_claims",
            return_value={},
        ):
            claims = self.validator.get_additional_claims(request)

        self.assertEqual(claims["sub"], self.identity.actor.reference.uri)
        self.assertEqual(claims["preferred_username"], self.identity.actor.preferred_username)
        self.assertEqual(claims["subject_username"], self.identity.actor.subject_name)
        self.assertEqual(claims["display_name"], self.identity.actor.name)
        self.assertEqual(claims["profile"], self.identity.actor.reference.uri)
        self.assertEqual(claims["identity_id"], self.identity.id)
