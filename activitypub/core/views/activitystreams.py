import logging

import rdflib
from django.shortcuts import get_object_or_404, redirect
from django.utils.decorators import method_decorator
from rest_framework import status
from rest_framework.response import Response

from .. import tasks
from ..settings import app_settings
from ..contexts import AS2
from ..decorators import calculate_digest, collect_signature
from ..models import (
    ActivityContext,
    ActorContext,
    CollectionContext,
    Domain,
    HttpSignatureProof,
    LinkedDataDocument,
    Notification,
    Reference,
)
from .discovery import get_domain
from .linked_data import LinkedDataModelView

logger = logging.getLogger(__name__)


def is_an_inbox(reference):
    return any(
        [
            Domain.objects.filter(local=True, instance__actor__inbox=reference).exists(),
            ActorContext.objects.filter(reference__domain__local=True, inbox=reference).exists(),
        ]
    )


def is_an_outbox(uri):
    return ActorContext.objects.filter(reference__domain__local=True, outbox__uri=uri).exists()


@method_decorator(calculate_digest, name="dispatch")
@method_decorator(collect_signature, name="dispatch")
class ActivityPubObjectDetailView(LinkedDataModelView):
    def get(self, *args, **kw):
        reference = self.get_object()
        if is_an_inbox(reference):
            logger.debug(f"{reference} is marked as an inbox")
            if not self.request.user.is_authenticated:
                return Response(
                    "Authentication required for accessing inboxes",
                    status=status.HTTP_401_UNAUTHORIZED,
                )
            actors = ActorContext.objects.filter(identity__user=self.request.user)
            if not actors.filter(inbox=reference).exists():
                return Response(
                    f"{reference.uri} is not owned by {self.request.user}",
                    status=status.HTTP_403_FORBIDDEN,
                )

        return super().get(*args, **kw)

    def _post_inbox(self, reference: Reference):
        try:
            document = self.request.data
            doc_id = document["id"]
            activity_reference = Reference.make(doc_id)

            if LinkedDataDocument.objects.filter(reference=activity_reference).exists():
                logger.warning(f"{activity_reference} already exists. Will ignore this post")
                return Response(status=status.HTTP_202_ACCEPTED)

            g = LinkedDataDocument.get_graph(document)

            actor_uri = activity_reference.get_value(g=g, predicate=AS2.actor)

            if actor_uri is None:
                raise AssertionError("Can not determine actor in activity")

            actor_reference = Reference.make(actor_uri)
            if actor_reference.domain and actor_reference.domain.blocked:
                return Response(
                    f"Domain from {actor_reference} is blocked", status=status.HTTP_403_FORBIDDEN
                )

            # The activity's domain must match the actor's domain to prevent spoofing
            if activity_reference.domain != actor_reference.domain:
                return Response(
                    f"Activity domain {activity_reference.domain} does not match actor domain {actor_reference.domain}",
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
            tasks.process_incoming_notification.delay_on_commit(
                notification_id=str(notification.id)
            )

            return Response(status=status.HTTP_202_ACCEPTED)
        except rdflib.plugins.shared.jsonld.errors.JSONLDException as exc:
            logger.warning(f"Failed to parse request. data: {self.request.data}")
            return Response(str(exc), status=status.HTTP_400_BAD_REQUEST)
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

            if actor_uri is None:
                raise AssertionError("Can not determine actor in activity")

            actor_ref = Reference.make(actor_uri)

            # remove triples where subjects are not from authoritative domains
            LinkedDataDocument.sanitize_graph(g, reference.domain)

            # Validate C2S business logic
            ActivityContext.validate_graph(g, actor_ref)

            # Load data for all subjects in the sanitized graph
            for subject_uri in set(g.subjects()):
                subject_ref = Reference.make(uri=str(subject_uri))
                subject_ref.load_context_models(g=g)

            activity = activity_reference.get_by_context(ActivityContext)

            if activity is None:
                raise AssertionError("Could not extract process activity")

            outbox = CollectionContext.make(reference, type=CollectionContext.Types.ORDERED)
            outbox.append(item=activity.reference)

            tasks.process_standard_activity_flows.delay(activity_uri=activity.reference.uri)
            tasks.post_activity.delay(activity.reference.uri)

            return Response(
                status=status.HTTP_201_CREATED, headers={"Location": activity_reference.uri}
            )
        except (KeyError, AssertionError) as exc:
            return Response(str(exc), status=status.HTTP_400_BAD_REQUEST)

    def post(self, *args, **kw):
        reference = self.get_object()

        # Posting to inbox (Server-to-Server) does not require authentication
        if is_an_inbox(reference):
            return self._post_inbox(reference)

        # Posting to outbox (C2S) requires an authenticated django user.
        if is_an_outbox(reference):
            if not self.request.user.is_authenticated:
                return Response(
                    "Post to outbox requires authentication", status=status.HTTP_401_UNAUTHORIZED
                )
            actors = ActorContext.objects.filter(identity__user=self.request.user)
            if not actors.filter(outbox=reference).exists():
                return Response(
                    f"{reference.uri} is not owned by {self.request.user}",
                    status=status.HTTP_403_FORBIDDEN,
                )

            return self._post_outbox(reference)

        return Response("Not a valid inbox or outbox", status=status.HTTP_400_BAD_REQUEST)


def redirect_to_actor(request, subject_name: str):
    if "@" in subject_name:
        username, domain = subject_name.split("@")

    else:
        username = subject_name
        domain = get_domain(request)

    actor = get_object_or_404(
        ActorContext,
        preferred_username=username,
        reference__domain__local=True,
        reference__domain=domain,
    )

    return redirect(actor.reference.uri)


__all__ = ("ActivityPubObjectDetailView", "redirect_to_actor")
