import logging
from urllib.parse import urlparse

import rdflib
from django.conf import settings
from django.http import Http404
from django.utils.decorators import method_decorator
from rest_framework import status
from rest_framework.renderers import BrowsableAPIRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from ..decorators import calculate_digest, collect_signature
from ..models import (
    Actor,
    BaseActivityStreamsObject,
    HttpSignatureProof,
    LinkedDataModel,
    Message,
    Reference,
)
from ..parsers import ActivityStreamsJsonParser, JsonLdParser
from ..renderers import ActivityJsonRenderer, JsonLdRenderer
from ..schemas import AS2
from ..settings import app_settings

logger = logging.getLogger(__name__)


@method_decorator(calculate_digest(), name="dispatch")
@method_decorator(collect_signature(), name="dispatch")
class ActivityPubObjectDetailView(APIView):
    renderer_classes = (ActivityJsonRenderer, JsonLdRenderer)
    parser_classes = (ActivityStreamsJsonParser, JsonLdParser)
    object_type = BaseActivityStreamsObject

    def get_renderers(self):
        if settings.DEBUG:
            self.renderer_classes = (BrowsableAPIRenderer,) + self.renderer_classes
        return super().get_renderers()

    def get_object(self, *args, **kw):
        parsed_uri = urlparse(self.request.build_absolute_uri())
        uri = parsed_uri._replace(query=None, fragment=None).geturl()
        try:
            return self.object_type.objects.get_subclass(
                reference__uri=uri, reference__domain__local=True
            )
        except self.object_type.DoesNotExist:
            raise Http404

    def get(self, *args, **kw):
        as_object = self.get_object(*args, **kw)
        return Response(as_object.to_jsonld())

    def post(self, *args, **kwargs):
        try:
            inbox = self.get_object()
            assert inbox.reference.is_an_inbox, "Not an inbox"
            document = self.request.data

            doc_id = document["id"]
            g = LinkedDataModel.get_graph(document)

            actor_uri = g.value(subject=rdflib.URIRef(doc_id), predicate=AS2.actor)
            assert actor_uri is not None, "Can not determine actor in activity"

            activity_reference = Reference.make(doc_id)
            actor_reference = Reference.make(actor_uri)
            if actor_reference.domain and actor_reference.domain.blocked:
                return Response(
                    f"Domain from {actor_reference} is blocked", status=status.HTTP_403_FORBIDDEN
                )

            message = Message.objects.create(
                sender=actor_reference,
                recipient=inbox.reference,
                activity=activity_reference,
                document=document,
            )
            if self.request.signature:
                HttpSignatureProof.objects.create(
                    message=message, http_message_signature=self.request.signature
                )
            return Response(status=status.HTTP_202_ACCEPTED)
        except (KeyError, AssertionError) as exc:
            return Response(str(exc), status=status.HTTP_400_BAD_REQUEST)


class ActorDetailView(ActivityPubObjectDetailView):
    def _get_actor(self):
        try:
            if "subject_name" in self.kwargs:
                return self._get_by_subject_name()
            return self._get_by_username()
        except Actor.DoesNotExist:
            raise Http404

    def _get_by_subject_name(self):
        username, domain = self.kwargs["subject_name"].split("@")
        return Actor.objects.get(account__username=username, account__domain__name=domain)

    def _get_by_username(self):
        domain = self.request.META.get("HTTP_HOST", app_settings.Instance.default_domain)
        return Actor.objects.get(
            account__username=self.kwargs["username"],
            account__domain__name=domain,
            account__domain__local=True,
        )

    def get_object(self, *args, **kw):
        return self._get_actor()


__all__ = ("ActivityPubObjectDetailView", "ActorDetailView")
