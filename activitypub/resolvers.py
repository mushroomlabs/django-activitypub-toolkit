import requests

from activitypub.exceptions import DocumentResolutionError
from activitypub.models import ActivityPubServer, Domain
from activitypub.schemas import AS2


class BaseDocumentResolver:
    def can_resolve(self, uri):
        return NotImplementedError

    def resolve(self, uri):
        raise NotImplementedError


class ConstantDocumentResolver(BaseDocumentResolver):
    KNOWN_URIS = {
        str(AS2.Public),
        str(AS2["Public/Inbox"]),
    }

    def can_resolve(self, uri):
        return uri in self.KNOWN_URIS

    def resolve(self, uri):
        return None


class HttpDocumentResolver(BaseDocumentResolver):
    def can_resolve(self, uri):
        return uri.startswith("http://") or uri.startswith("https://")

    def resolve(self, uri):
        try:
            domain = Domain.get_default()
            server, _ = ActivityPubServer.objects.get_or_create(domain=domain)
            signing_key = server and server.actor and server.actor.main_cryptographic_keypair
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
