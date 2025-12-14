import http.client
import json
import logging
from io import BytesIO
from pathlib import Path
from urllib.request import HTTPHandler, HTTPSHandler, OpenerDirector, Request, install_opener

from django.apps import AppConfig
from pyld import jsonld
from urllib3.response import HTTPResponse

from .settings import app_settings

logger = logging.getLogger(__name__)


def builtin_document_loader(url: str, options={}):
    try:
        context_map = {c.url: c for c in app_settings.PRESET_CONTEXTS}

        context = context_map[url]
        return context.as_pyld
    except KeyError:
        logger.info(f"Fetching remote context: {url!r}")
        return jsonld.requests_document_loader(url, options)


class LocalDocumentHandler(HTTPHandler, HTTPSHandler):
    """
    A HTTP handler that to get context documents directly, instead
    of loading from the web every time.
    """

    def _response_from_local_document(self, req, document) -> HTTPResponse:
        # See https://github.com/getsentry/responses/blob/master/responses/__init__.py
        # https://github.com/getsentry/responses/issues/691

        data = BytesIO()
        data.close()
        headers = {"Content-Type": "application/ld+json"}

        orig_response = HTTPResponse(
            body=data,
            msg=headers,
            preload_content=False,
        )
        status = 200

        body = BytesIO()
        body.write(json.dumps(document).encode("utf-8"))
        body.seek(0)

        return HTTPResponse(
            status=status,
            reason=http.client.responses.get(status, None),
            body=body,
            headers=headers,
            original_response=orig_response,
            preload_content=False,
            request_method=req.get_method(),
        )

    def _fetch_local(self, req):
        context_map = {c.url: c for c in app_settings.PRESET_CONTEXTS}
        url = req.get_full_url()
        context = context_map.get(url)

        if context is None:
            return None

        return self._response_from_local_document(req, context.document)

    def http_open(self, req: Request) -> http.client.HTTPResponse:
        cached = self._fetch_local(req)
        return cached if cached is not None else super().http_open(req)

    def https_open(self, req: Request) -> http.client.HTTPResponse:
        cached = self._fetch_local(req)
        return cached if cached is not None else super().https_open(req)


def secure_rdflib():
    opener = OpenerDirector()
    opener.add_handler(LocalDocumentHandler())
    install_opener(opener)


class ActivityPubConfig(AppConfig):
    name = "activitypub"
    path = str(Path(__file__).parent)

    def ready(self):
        from . import handlers  # noqa
        from . import signals  # noqa

        app_settings.load()

        secure_rdflib()
        jsonld.set_document_loader(builtin_document_loader)
