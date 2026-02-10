import logging

import rdflib

from .contexts import AS2, AS2_CONTEXT, RDF, SEC_V1_CONTEXT
from .exceptions import DropMessage
from .models import Actor, LinkedDataDocument

logger = logging.getLogger(__name__)


class DocumentProcessor:
    def process_outgoing(self, document):
        pass

    def process_incoming(self, document):
        pass


class ActorDeletionDocumentProcessor(DocumentProcessor):
    def process_incoming(self, document: dict | None):
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
            assert document is not None
            g = LinkedDataDocument.get_graph(document)
            subject_uri = rdflib.URIRef(document["id"])
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


class ContextCompatibilityDocumentProcessor(DocumentProcessor):
    def process_outgoing(self, document: dict | None):
        if not document:
            return

        if document["@context"] == SEC_V1_CONTEXT.url:
            document["@context"] = [AS2_CONTEXT.url, SEC_V1_CONTEXT.url]


class CompactJsonLdDocumentProcessor(DocumentProcessor):
    def process_outgoing(self, document: dict | None):
        """
        Many Fediverse servers do not properly treat ActivityPub data as JSON-LD
        and expect attribute names without prefixes (e.g., "name" instead of "as:name").

        With this processor we transform the compacted JSON-LD from
        outgoing messages (with prefixes like "as:name") to simple
        attribute names ("name").
        """

        if not document:
            return

        self._strip_prefixes(document)
        self._wrap_list_fields(document)
        self._expand_public(document)

    def _wrap_list_fields(self, data):
        if isinstance(data, dict):
            for key, value in data.items():
                if key in ["to", "cc", "bcc"] and type(value) is str:
                    data[key] = [value]
                self._wrap_list_fields(value)

    def _expand_public(self, data):
        if isinstance(data, dict):
            for key, value in data.items():
                if value == "as:Public":
                    data[key] = "https://www.w3.org/ns/activitystreams#Public"
                else:
                    self._expand_public(value)

        elif isinstance(data, list):
            for i, item in enumerate(data):
                if item == "as:Public":
                    data[i] = "https://www.w3.org/ns/activitystreams#Public"
                else:
                    self._expand_public(item)

    def _strip_prefixes(self, data):
        """
        Recursively strip prefixes from dictionary keys.

        Handles nested dictionaries and lists.
        """
        if isinstance(data, dict):
            # Process dictionary keys
            keys_to_process = list(data.keys())
            for key in keys_to_process:
                value = data[key]

                normalized_key = key.split(":", 1)[1] if ":" in key else None
                if normalized_key is not None:
                    data[normalized_key] = data.pop(key)
                    key = normalized_key

                # Recursively process nested structures
                self._strip_prefixes(value)

        elif isinstance(data, list):
            # Process list items
            for item in data:
                self._strip_prefixes(item)
