import requests
from urllib.parse import urlparse, urljoin

from activitypub.exceptions import DocumentResolutionError, ReferenceRedirect
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
        domain = Domain.get_default()
        server, _ = ActivityPubServer.objects.get_or_create(domain=domain)

        signing_key = (
            server.actor and SecV1Context.valid.filter(owner=server.actor.reference).first()
        )
        auth = signing_key and signing_key.signed_request_auth

        original_domain = urlparse(uri).netloc
        uri_to_fetch = uri
        final_uri = uri

        while uri_to_fetch is not None:
            response = requests.get(
                uri_to_fetch,
                headers={"Accept": "application/activity+json,application/ld+json"},
                auth=auth,
                allow_redirects=False,
            )

            if response.is_redirect:
                location = response.headers.get("Location")
                redirect_uri = urljoin(uri_to_fetch, location)
                redirect_domain = urlparse(redirect_uri).netloc

                if redirect_domain != original_domain:
                    raise ReferenceRedirect(
                        f"Cross-domain redirect to {redirect_uri}", redirect_uri=redirect_uri
                    )

                uri_to_fetch = redirect_uri
                final_uri = redirect_uri
            else:
                uri_to_fetch = None

        try:
            response.raise_for_status()
            document = response.json()
            document_id = document.get("id")

            parsed_final_uri = urlparse(final_uri)
            parsed_document_id = urlparse(document_id)

            # Document id must match final location
            same_uri = all(
                [
                    parsed_final_uri.netloc == parsed_document_id.netloc,
                    (parsed_final_uri.path or "/") == (parsed_document_id.path or "/"),
                ]
            )

            if not same_uri:
                raise DocumentResolutionError(
                    f"Document id {document_id} doesn't match final URI {final_uri}"
                )

            # If we followed redirects, signal the redirect
            if final_uri != uri:
                raise ReferenceRedirect(
                    f"Redirected from {uri} to {final_uri}", redirect_uri=final_uri
                )

            return document
        except (requests.JSONDecodeError, requests.HTTPError, requests.ConnectionError) as exc:
            raise DocumentResolutionError from exc
