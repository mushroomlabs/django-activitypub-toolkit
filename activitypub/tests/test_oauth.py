from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.utils import timezone

from activitypub.factories import DomainFactory, IdentityFactory, UserFactory
from activitypub.models import OAuthAccessToken, OAuthClientApplication, OAuthRefreshToken
from activitypub.tests.base import BaseTestCase
from activitypub.views.oauth import ActivityPubIdentityOAuth2Validator

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

    def test_save_bearer_token_links_identity_to_access_token(self):
        """AccessToken should be linked to the selected identity"""
        request = self.factory.post("/oauth/token/")
        request.user = self.user
        request.session = {"selected_identity_id": self.identity.id}

        # Create token objects first
        access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.application,
            token="test-access-token",
            expires=timezone.now() + timedelta(hours=1),
            identity=self.identity,  # Required field
        )

        token_dict = {
            "access_token": "test-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        # Mock the parent save_bearer_token to do nothing
        with patch.object(ActivityPubIdentityOAuth2Validator.__bases__[0], "save_bearer_token"):
            self.validator.save_bearer_token(token_dict, request)

        # Verify identity was linked
        access_token.refresh_from_db()
        self.assertEqual(access_token.identity, self.identity)
        self.assertNotIn("selected_identity_id", request.session)

    def test_save_bearer_token_links_identity_to_refresh_token(self):
        """RefreshToken should be linked to the selected identity"""
        request = self.factory.post("/oauth/token/")
        request.user = self.user
        request.session = {"selected_identity_id": self.identity.id}

        # Create token objects first
        access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.application,
            token="test-access-token",
            expires=timezone.now() + timedelta(hours=1),
            identity=self.identity,  # Required field
        )
        refresh_token = OAuthRefreshToken.objects.create(
            user=self.user,
            application=self.application,
            token="test-refresh-token",
            identity=self.identity,  # Required field
        )

        token_dict = {
            "access_token": "test-access-token",
            "refresh_token": "test-refresh-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        # Mock the parent save_bearer_token to do nothing
        with patch.object(ActivityPubIdentityOAuth2Validator.__bases__[0], "save_bearer_token"):
            self.validator.save_bearer_token(token_dict, request)

        # Verify identity was linked to both tokens
        access_token.refresh_from_db()
        refresh_token.refresh_from_db()
        self.assertEqual(access_token.identity, self.identity)
        self.assertEqual(refresh_token.identity, self.identity)
        self.assertNotIn("selected_identity_id", request.session)

    def test_save_bearer_token_raises_error_when_no_identity_selected(self):
        """Should raise PermissionDenied when no identity is selected in session"""
        request = self.factory.post("/oauth/token/")
        request.user = self.user
        request.session = {}  # No identity selected

        token_dict = {
            "access_token": "test-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        # Mock the parent save_bearer_token to do nothing
        with patch.object(ActivityPubIdentityOAuth2Validator.__bases__[0], "save_bearer_token"):
            with self.assertRaises(PermissionDenied):
                self.validator.save_bearer_token(token_dict, request)

    def test_save_bearer_token_raises_error_for_invalid_identity(self):
        """Should raise PermissionDenied when identity does not belong to user"""
        other_user = UserFactory()
        other_identity = IdentityFactory(user=other_user, actor__reference__domain=self.domain)

        request = self.factory.post("/oauth/token/")
        request.user = self.user
        request.session = {"selected_identity_id": other_identity.id}  # Wrong user's identity

        token_dict = {
            "access_token": "test-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        # Mock the parent save_bearer_token to do nothing
        with patch.object(ActivityPubIdentityOAuth2Validator.__bases__[0], "save_bearer_token"):
            with self.assertRaises(PermissionDenied):
                self.validator.save_bearer_token(token_dict, request)

    def test_get_identity_from_access_token(self):
        """Should retrieve identity directly from AccessToken"""
        request = Mock()
        access_token = Mock()
        access_token.identity = self.identity
        request.access_token = access_token

        result = self.validator._get_identity_for_request(request)

        self.assertEqual(result, self.identity)

    def test_get_identity_from_refresh_token_via_source(self):
        """Should retrieve identity from RefreshToken via source_refresh_token"""
        request = Mock()
        refresh_token = Mock()
        refresh_token.identity = self.identity

        access_token = Mock()
        access_token.identity = None
        access_token.source_refresh_token = refresh_token
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

    def test_get_identity_raises_error_when_no_identity_found(self):
        """Should raise PermissionDenied when no identity can be found on request"""
        request = Mock()
        request.user = self.user
        request.access_token = None
        request.id_token = None

        with self.assertRaises(PermissionDenied):
            self.validator._get_identity_for_request(request)

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
        RefreshToken maintains identity link across multiple access token refreshes.
        """
        # Create initial tokens with identity
        refresh_token = OAuthRefreshToken.objects.create(
            user=self.user,
            application=self.application,
            token="original-refresh-token",
            identity=self.identity,
        )

        # Simulate token refresh: new access token created with source_refresh_token
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

        # Should be able to retrieve identity via source_refresh_token
        result = self.validator._get_identity_for_request(request)

        self.assertEqual(result, self.identity)


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
