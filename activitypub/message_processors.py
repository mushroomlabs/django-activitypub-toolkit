import logging

import rdflib

from .exceptions import DropMessage
from .models import Actor, LinkedDataModel, Message
from .schemas import AS2, RDF

logger = logging.getLogger(__name__)


class MessageProcessor:
    def process_outgoing(self, message: Message):
        pass

    def process_incoming(self, message: Message):
        pass


class ActorDeletionMessageProcessor(MessageProcessor):
    def process_incoming(self, message: Message):
        """
        Mastodon is constantly sending DELETE messages for all
        users who move/delete their accounts to all known network,
        even when we never even seen that actor before.

        To avoid having to process the whole message, we will simply
        drop the message if it's a DELETE for an actor that we have no
        reference in our database.

        If we do have the reference, then we might be interested in
        cleaning up properly.
        """

        try:
            g = LinkedDataModel.get_graph(message.document)
            subject_uri = rdflib.URIRef(message.document["id"])
            activity_type = g.value(subject=subject_uri, predicate=RDF.type)

            actor = g.value(subject=subject_uri, predicate=AS2.actor)
            object = g.value(subject=subject_uri, predicate=AS2.object)

            assert activity_type == AS2.Delete
            assert actor is not None
            assert object is not None
            assert actor == object
            assert not Actor.objects.filter(reference__uri=str(actor)).exists()

            raise DropMessage
        except (KeyError, AssertionError):
            pass
