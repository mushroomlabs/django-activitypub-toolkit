from activitypub.models import ActorAccount, Domain


class ActorAccountAuthenticationBackend:
    def authenticate(self, username=None, password=None, domain=None):
        try:
            user_domain = domain or Domain.get_default()
            account = ActorAccount.objects.get(
                actor__preferred_username=username, actor__reference__domain=user_domain
            )
            if account.check_password(password):
                return account
        except (Domain.DoesNotExist, ActorAccount.DoesNotExist):
            return None

    def get_user(self, user_id):
        try:
            return ActorAccount.objects.get(pk=user_id)
        except ActorAccount.DoesNotExist:
            return None
