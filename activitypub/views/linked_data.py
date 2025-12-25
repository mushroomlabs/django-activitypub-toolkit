import logging
from urllib.parse import urlparse

from django.conf import settings
from django.shortcuts import get_object_or_404
from pyld import jsonld
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Reference
from ..parsers import ActivityStreamsJsonParser, JsonLdParser
from ..renderers import ActivityJsonRenderer, BrowsableLinkedDataRenderer, JsonLdRenderer
from ..serializers import LinkedDataSerializer

logger = logging.getLogger(__name__)


class LinkedDataModelView(APIView):
    renderer_classes = (ActivityJsonRenderer, JsonLdRenderer)
    parser_classes = (ActivityStreamsJsonParser, JsonLdParser)
    serializer_class = LinkedDataSerializer

    def get_renderers(self):
        if settings.DEBUG:
            self.renderer_classes = (BrowsableLinkedDataRenderer,) + self.renderer_classes
        return super().get_renderers()

    def get_object(self):
        parsed_uri = urlparse(self.request.build_absolute_uri())
        uri = parsed_uri._replace(query=None, fragment=None).geturl()
        return get_object_or_404(Reference, uri=uri, domain__local=True)

    def get_serializer(self, *args, **kw):
        reference = self.get_object()
        serializer_class = self.get_serializer_class()

        # FIXME: add authentication mechanism to have actor attribute on request

        viewer = None
        return serializer_class(
            instance=reference, context={"viewer": viewer, "view": self, "request": self.request}
        )

    def get_serializer_class(self) -> type[LinkedDataSerializer] | None:
        return LinkedDataSerializer

    def get(self, *args, **kw):
        """
        Render the linked data resource as compacted JSON-LD.

        Serializes to expanded JSON-LD, then compacts using @context.
        """
        reference = self.get_object()
        serializer = self.get_serializer()

        # Serialize to expanded JSON-LD (main subject, not embedded)
        expanded_document = serializer.data

        # Get compact context and compact the document
        context = serializer.get_compact_context(reference)
        compacted_document = jsonld.compact(expanded_document, context)

        return Response(compacted_document)
