import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import LoginToken

User = get_user_model()


class LemmyJWTAuthentication(BaseAuthentication):
    """
    JWT authentication requiring token to exist in LoginToken table.

    Stateful authentication:
    - Valid JWT + present in LoginToken = authenticated
    - Valid JWT + NOT in LoginToken = rejected (logged out)
    - Invalid JWT = rejected (tampered/expired)
    """

    def authenticate(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            return None

        token = auth_header.removeprefix("Bearer ")

        try:
            signing_key = settings.LEMMY_TOKEN_SIGNING_KEY
            jwt.decode(token, signing_key, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed("Token has expired")
        except jwt.InvalidTokenError:
            raise AuthenticationFailed("Invalid token")

        try:
            login_token = LoginToken.objects.select_related("user").get(token=token)
        except LoginToken.DoesNotExist:
            raise AuthenticationFailed("Token not found or has been logged out")

        user = login_token.user
        if not user.is_active:
            raise AuthenticationFailed("User account is disabled")

        return (user, token)

    def authenticate_header(self, request):
        """
        Return WWW-Authenticate header for 401 responses.
        """
        return 'Bearer realm="api"'
