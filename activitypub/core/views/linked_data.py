import logging
from urllib.parse import urlparse

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Reference
from ..parsers import ActivityStreamsJsonParser, JsonLdParser
from ..renderers import ActivityJsonRenderer, BrowsableLinkedDataRenderer, JsonLdRenderer
from ..settings import app_settings

logger = logging.getLogger(__name__)


class LinkedDataModelView(APIView):
    renderer_classes = (ActivityJsonRenderer, JsonLdRenderer)
    parser_classes = (ActivityStreamsJsonParser, JsonLdParser)

    def get_renderers(self):
        if settings.DEBUG:
            self.renderer_classes = (BrowsableLinkedDataRenderer,) + self.renderer_classes
        return super().get_renderers()

    def get_object(self):
        parsed_uri = urlparse(self.request.build_absolute_uri())
        uri = parsed_uri._replace(query=None, fragment=None).geturl()

        if self.request.path == "/":
            uri = uri.removesuffix("/")

        return get_object_or_404(Reference, uri=uri, domain__local=True)

    def get_projection_class(self, reference):
        return app_settings.PROJECTION_SELECTOR(reference=reference)

    def get(self, *args, **kw):
        """
        Render the linked data resource as compacted JSON-LD, as defined by the projection class
        """

        reference = self.get_object()
        projection_class = self.get_projection_class(reference=reference)

        viewer = None  # TODO: add authentication based on http signatures

        projection = projection_class(
            reference=reference, scope={"viewer": viewer, "view": self, "request": self.request}
        )

        projection.build()

        document = projection.get_compacted()
        for processor in app_settings.DOCUMENT_PROCESSORS:
            processor.process_outgoing(document)

        return Response(document)
