import logging

from django.http import Http404
from django.utils.decorators import method_decorator
from rest_framework import status
from rest_framework.response import Response

from ..contexts import AS2
from ..decorators import calculate_digest, collect_signature
from ..models import (
    ActivityContext,
    Actor,
    ActorContext,
    CollectionContext,
    CollectionPageContext,
    Domain,
    HttpSignatureProof,
    LinkedDataDocument,
    Notification,
    QuestionContext,
    Reference,
)
from ..projections import (
    ActorProjection,
    CollectionPageProjection,
    CollectionProjection,
    CollectionWithFirstPageProjection,
    QuestionProjection,
    ReferenceProjection,
)
from ..tasks import process_incoming_notification
from .linked_data import LinkedDataModelView

logger = logging.getLogger(__name__)


def is_an_inbox(uri):
    return any(
        [
            Domain.objects.filter(local=True, instance__actor__inbox__uri=uri).exists(),
            Actor.objects.filter(reference__domain__local=True, inbox__uri=uri).exists(),
        ]
    )


def is_an_outbox(uri):
    return Actor.objects.filter(reference__domain__local=True, outbox__uri=uri).exists()


def is_outbox_owner(actor_reference: Reference, uri):
    return Actor.objects.filter(reference=actor_reference, outbox__uri=uri).exists()


@method_decorator(calculate_digest(), name="dispatch")
@method_decorator(collect_signature(), name="dispatch")
class ActivityPubObjectDetailView(LinkedDataModelView):
    def get_projection_class(self, reference):
        if is_an_outbox(reference.uri):
            return CollectionWithFirstPageProjection

        # Check for ActorContext
        if reference.get_by_context(ActorContext):
            return ActorProjection

        # Check for QuestionContext
        if reference.get_by_context(QuestionContext):
            return QuestionProjection

        # Check for CollectionPageContext
        if reference.get_by_context(CollectionPageContext):
            return CollectionPageProjection

        # Check for CollectionContext
        if reference.get_by_context(CollectionContext):
            collection = reference.get_by_context(CollectionContext)
            # Use CollectionWithFirstPageProjection if collection has pages
            if collection.pages.exists():
                return CollectionWithFirstPageProjection
            else:
                return CollectionProjection

        # Default
        return ReferenceProjection

    def get(self, *args, **kw):
        reference = self.get_object()
        if is_an_inbox(reference.uri):
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        return super().get(*args, **kw)

    def _post_inbox(self, reference: Reference):
        try:
            document = self.request.data
            doc_id = document["id"]
            activity_reference = Reference.make(doc_id)
            g = LinkedDataDocument.get_graph(document)

            actor_uri = activity_reference.get_value(g=g, predicate=AS2.actor)

            assert actor_uri is not None, "Can not determine actor in activity"
            actor_reference = Reference.make(actor_uri)
            if actor_reference.domain and actor_reference.domain.blocked:
                return Response(
                    f"Domain from {actor_reference} is blocked", status=status.HTTP_403_FORBIDDEN
                )

            notification = Notification.objects.create(
                sender=actor_reference, target=reference, resource=activity_reference
            )
            if self.request.signature:
                HttpSignatureProof.objects.create(
                    notification=notification, http_message_signature=self.request.signature
                )

            LinkedDataDocument.objects.create(reference=activity_reference, data=document)
            process_incoming_notification.delay_on_commit(notification_id=str(notification.id))

            return Response(status=status.HTTP_202_ACCEPTED)
        except (KeyError, AssertionError) as exc:
            return Response(str(exc), status=status.HTTP_400_BAD_REQUEST)

    def _post_outbox(self, reference: Reference):
        try:
            assert reference.is_local, "Outbox is not managed by this server"
            document = self.request.data.copy()
            doc_id = document.pop("id", None)

            activity_reference = None

            if doc_id is not None:
                assert not Reference.objects.filter(uri=str(doc_id)).exists(), (
                    f"Document {doc_id} already exists"
                )
                activity_reference = Reference.make(doc_id)

            if activity_reference is None:
                activity_reference = ActivityContext.generate_reference(reference.domain)

            msg = f"Different origin domains for {reference.uri} outbox and {doc_id}"
            assert activity_reference.domain == reference.domain, msg

            document["id"] = activity_reference.uri
            g = LinkedDataDocument.get_graph(document)

            actor_uri = activity_reference.get_value(g=g, predicate=AS2.actor)

            assert actor_uri is not None, "Can not determine actor in activity"
            actor_reference = Reference.make(actor_uri)

            if not is_outbox_owner(actor_reference, reference.uri):
                return Response(
                    f"{reference.uri} is not owned by {actor_reference}",
                    status=status.HTTP_403_FORBIDDEN,
                )

            notification = Notification.objects.create(
                sender=actor_reference, target=reference, resource=activity_reference
            )

            if self.request.signature:
                HttpSignatureProof.objects.create(
                    notification=notification, http_message_signature=self.request.signature
                )

            LinkedDataDocument.objects.create(reference=activity_reference, data=document)
            process_incoming_notification(notification_id=str(notification.id))

            return Response(
                status=status.HTTP_201_CREATED, headers={"Location": activity_reference.uri}
            )
        except (KeyError, AssertionError) as exc:
            return Response(str(exc), status=status.HTTP_400_BAD_REQUEST)

    def post(self, *args, **kw):
        reference = self.get_object()

        if is_an_inbox(reference.uri):
            return self._post_inbox(reference)

        if is_an_outbox(reference.uri):
            return self._post_outbox(reference)

        return Response("Not a valid inbox or outbox", status=status.HTTP_400_BAD_REQUEST)


class ActorDetailView(LinkedDataModelView):
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
        domain = self.request.META.get("HTTP_HOST", Domain.get_default())
        return Actor.objects.get(
            account__username=self.kwargs["username"],
            account__domain__name=domain,
            account__domain__local=True,
        )

    def get_object(self, *args, **kw):
        return self._get_actor()


__all__ = ("ActivityPubObjectDetailView", "ActorDetailView")
