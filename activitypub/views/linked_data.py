import logging
from urllib.parse import urlparse

from django.conf import settings
from django.shortcuts import get_object_or_404
from pyld import jsonld
from rest_framework.renderers import BrowsableAPIRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from ..frames import FrameRegistry, LinkedDataFrame
from ..models import Reference
from ..parsers import ActivityStreamsJsonParser, JsonLdParser
from ..renderers import ActivityJsonRenderer, JsonLdRenderer
from ..serializers import LinkedDataSerializer

logger = logging.getLogger(__name__)


class LinkedDataModelView(APIView):
    renderer_classes = (ActivityJsonRenderer, JsonLdRenderer)
    parser_classes = (ActivityStreamsJsonParser, JsonLdParser)
    serializer_class = LinkedDataSerializer

    def get_renderers(self):
        if settings.DEBUG:
            self.renderer_classes = (BrowsableAPIRenderer,) + self.renderer_classes
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

    def get_frame_class(self) -> type[LinkedDataFrame] | None:
        """
        Override this method if you need custom frame selection logic.
        By default, uses automatic selection via FrameRegistry (returns None).
        """
        return None

    def get_framed_document(self, serializer):
        """Get framed document with automatic or custom frame selection"""
        frame_class = self.get_frame_class()

        if frame_class is None:
            # Automatic selection via registry
            frame = FrameRegistry.auto_frame(serializer)
        else:
            # Manual override (for custom views)
            frame = frame_class(serializer=serializer)

        return frame.to_framed_document()

    def get(self, *args, **kw):
        serializer = self.get_serializer()
        document = self.get_framed_document(serializer)

        if not document:
            document = serializer.data

        # Get context array from serializer and compact the document
        instance = self.get_object()
        context = serializer.get_compact_context(instance)
        return Response(jsonld.compact(document, context))
