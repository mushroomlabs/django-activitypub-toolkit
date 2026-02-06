from activitypub.core.models import Identity


class ActorMiddleware:
    """
    Attaches an actor to request.actor. Mostly a convenience method
    to avoid having to check for identities on every request.

    Preconditions:

     - user is authenticated
     - user has exactly one identity
     - no actor is already present

    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            if getattr(request, "actor", None) is not None:
                raise AssertionError

            user = request.user
            if not user or not user.is_authenticated:
                raise AssertionError

            identity = Identity.objects.select_related("actor").get(user=request.user)
            request.actor = identity.actor
        except (
            AttributeError,
            AssertionError,
            Identity.DoesNotExist,
            Identity.MultipleObjectsReturned,
        ):
            pass
        finally:
            return self.get_response(request)
