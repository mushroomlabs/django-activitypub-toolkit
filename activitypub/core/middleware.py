import logging

from urllib.parse import urlunparse

from django.http import HttpResponse, JsonResponse

from activitypub.core.exceptions import DocumentResolutionError
from activitypub.core.models import Domain, Identity, Reference, SecV1Context
from activitypub.core.resolvers import SignedHttpRequestResolver
from activitypub.core.settings import app_settings

logger = logging.getLogger(__name__)

SIGNED_RESOLVER = None


def get_resolver():
    global SIGNED_RESOLVER

    if SIGNED_RESOLVER is None:
        SIGNED_RESOLVER = SignedHttpRequestResolver()
    return SIGNED_RESOLVER


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


class LinkedDataProxyMiddleware:
    """
    A middleware to allow the Django application to serve requests
    for linked data objects that are *not* local.

    Useful for cases where we want to allow clients to fetch resources
    from servers that implement authorized fetch, or for servers that
    do not serve the data related to transient activities, etc.

    Preconditions:

     - user is authenticated

    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(":")[0]

        # Build the remote URI from the request
        uri = urlunparse(
            ("https", host, request.path, "", request.META.get("QUERY_STRING", ""), "")
        )

        # Not a proxy request - pass through to normal Django handling
        if Domain.objects.filter(name=host, local=True).exists():
            return self.get_response(request)

        logger.info(f"Making proxy request to {uri}")

        # if not request.user.is_authenticated:
        #    return HttpResponse(status=401)

        if request.method != "GET":
            return HttpResponse(status=405)

        accept = request.headers.get("Accept", "")
        if not self._wants_jsonld(accept):
            return HttpResponse(status=406)

        reference = Reference.make(uri=uri)

        if not reference.is_resolved:
            logger.info(f"{uri} is not resolved. Attempt to resolve it first")
            if request.user.is_authenticated:
                identity = (
                    Identity.objects.select_related("actor").filter(user=request.user).first()
                )
                signing_key = (
                    identity
                    and SecV1Context.valid.filter(
                        owner__in=identity.actors.values("reference")
                    ).first()
                )
            else:
                signing_key = None
            resolver = get_resolver()
            try:
                resolver.resolve(uri, signing_key=signing_key)
            except DocumentResolutionError:
                return HttpResponse(status=502)

        reference.refresh_from_db()
        projection_class = app_settings.PROJECTION_SELECTOR(reference=reference)
        projection = projection_class(reference=reference, scope={"request": request})
        projection.build()
        document = projection.get_compacted()
        return JsonResponse(document, content_type="application/activity+json")

    def _wants_jsonld(self, accept):
        return any(mime in accept for mime in ("application/activity+json", "application/ld+json"))
