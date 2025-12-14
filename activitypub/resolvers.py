import requests

from activitypub.exceptions import DocumentResolutionError
from activitypub.models import ActivityPubServer, Domain, SecV1Context
from activitypub.settings import app_settings


def is_context_or_namespace_url(uri):
    context_urls = {c.url for c in app_settings.PRESET_CONTEXTS}
    known_namespaces = {
        str(c.namespace) for c in app_settings.PRESET_CONTEXTS if c.namespace is not None
    }
    return uri in context_urls or any([uri.startswith(nm) for nm in known_namespaces])


class BaseDocumentResolver:
    def can_resolve(self, uri):
        return NotImplementedError

    def resolve(self, uri):
        raise NotImplementedError


class ContextUriResolver(BaseDocumentResolver):
    def can_resolve(self, uri):
        return is_context_or_namespace_url(uri)

    def resolve(self, uri):
        return None


class HttpDocumentResolver(BaseDocumentResolver):
    def can_resolve(self, uri):
        if is_context_or_namespace_url(uri):
            return False

        return uri.startswith("http://") or uri.startswith("https://")

    def resolve(self, uri):
        try:
            domain = Domain.get_default()
            server, _ = ActivityPubServer.objects.get_or_create(domain=domain)

            signing_key = (
                server.actor and SecV1Context.valid.filter(owner=server.actor.reference).first()
            )
            auth = signing_key and signing_key.signed_request_auth
            response = requests.get(
                uri,
                headers={"Accept": "application/activity+json,application/ld+json"},
                auth=auth,
            )
            response.raise_for_status()
            return response.json()
        except requests.HTTPError:
            raise DocumentResolutionError
