from activitypub.models import Identity, Domain


class ActorUsernameAuthenticationBackend:
    def authenticate(self, username=None, password=None, domain=None):
        try:
            if domain is None:
                raise AssertionError
            identity = Identity.objects.get(
                actor__preferred_username=username, actor__reference__domain=domain
            )
            if not identity.user.check_password(password):
                raise AssertionError
            return identity.user
        except (Domain.DoesNotExist, Identity.DoesNotExist, AssertionError):
            return None

    def get_user(self, user_id):
        try:
            identity = Identity.objects.get(user_id=user_id)
            return identity.user
        except Identity.DoesNotExist:
            return None
