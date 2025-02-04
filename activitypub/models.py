import base64
import copy
import datetime
import json
import logging
import os
import re
import ssl
import sys
from functools import cached_property
from typing import Optional, cast
from urllib.parse import urlparse

import rdflib
import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from django.contrib.postgres.fields import ArrayField
from django.db import models, transaction
from django.db.models import Case, Exists, F, Max, OuterRef, Q, Value, When
from django.db.models.functions import Concat
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import classproperty
from django_ulid.models import ULIDField
from django_ulid.models import default as new_ulid
from model_utils.choices import Choices
from model_utils.fields import MonitorField
from model_utils.managers import InheritanceManager, QueryManager
from model_utils.models import StatusModel
from pyld import jsonld
from requests_http_message_signatures import HTTPSignatureHeaderAuth

from . import signals
from .exceptions import DropMessage, UnprocessableJsonLd
from .schemas import AS2, LDP, PURL_RELATIONSHIP, RDF, SEC, SEC_V1
from .serializers import NodeInfoSerializer
from .settings import app_settings

logger = logging.getLogger(__name__)

DOMAIN_REGEX = r"^(?:[a-z0-9](?:[a-z0-9-_]{0,61}[a-z0-9])?\.)+[a-z0-9][a-z0-9-_]{0,61}[a-z]$"
BASE_OBJECT_OR_LINK = Q(app_label="activitypub") & (
    Q(model="object") | Q(model="link") | Q(model="activity") | Q(model="actor")
)
PUBLIC_ACTOR = None


def _domain_validator(name: str):
    return any(
        [name == app_settings.Instance.default_domain, re.match(DOMAIN_REGEX, name) is not None]
    )


def _is_pointer_field(model_field):
    return isinstance(
        model_field,
        (models.ForeignKey, models.OneToOneField, models.ManyToManyField),
    )


def generate_ulid():
    # If we use new_ulid directly, django will generate the migration
    # indefinitely. See https://code.djangoproject.com/ticket/32689
    return new_ulid()


def _file_location(instance, filename):
    _, ext = os.path.splitext(filename)

    new_filename = generate_ulid()
    now = new_filename.timestamp().datetime
    subfolder = str(new_filename.randomness())[:2]
    return f"{now.year}/{now.month:02d}/{now.day:02d}/{subfolder}/{new_filename}{ext}"


def _get_public_actor():
    global PUBLIC_ACTOR
    if PUBLIC_ACTOR is None:
        reference, _ = Reference.objects.get_or_create(uri=str(AS2.Public))
        PUBLIC_ACTOR, _ = Actor.objects.get_or_create(reference=reference)
    return PUBLIC_ACTOR


def _reset_public_actor():
    global PUBLIC_ACTOR
    reference, _ = Reference.objects.get_or_create(uri=str(AS2.Public))
    PUBLIC_ACTOR, _ = Actor.objects.get_or_create(reference=reference)
    return PUBLIC_ACTOR


def _get_public_actor_id():
    # FIXME: ULIDfields may not be a good idea after all. Foreign Keys
    # can not take the ULID object to build a reference, it needs to
    # be in string format. So we need to have a function that just
    # converts the value to string before being usable a default
    # callable to determine the public actor id.
    return str(_get_public_actor().id)


def _get_normalized_hash(data):
    norm_form = jsonld.normalize(
        data,
        {"algorithm": "URDNA2015", "format": "application/n-quads"},
    )
    digest = hashes.Hash(hashes.SHA256())
    digest.update(norm_form.encode("utf8"))
    return digest.finalize().hex().encode("ascii")


class AccountManager(models.Manager):
    def get_queryset(self) -> models.QuerySet:
        qs = super().get_queryset()
        return qs.annotate(
            _subject_name=Concat(Value("@"), "username", Value("@"), "domain__name"),
            local=F("domain__local"),
        )

    def get_by_subject_name(self, subject_name):
        username, domain = subject_name.split("@", 1)
        if not _domain_validator(domain):
            raise ValueError("malformed domain name")
        qs = super().get_queryset()
        return qs.filter(username=username, domain_id=domain).get()


class MessageManager(models.Manager):
    def get_queryset(self) -> models.QuerySet:
        qs = super().get_queryset()
        verified_sqs = MessageIntegrityVerification.objects.filter(proof__message=OuterRef("pk"))
        processed_sqs = MessageProcessResult.objects.filter(
            message=OuterRef("pk"),
            result__in=[MessageProcessResult.Types.OK, MessageProcessResult.Types.DROPPED],
        )
        return qs.annotate(verified=Exists(verified_sqs), processed=Exists(processed_sqs))


class LinkedDataModel(models.Model):
    NAMESPACES = set([LDP])
    LINKED_DATA_FIELDS = {}
    EXTRA_LINKED_DATA_FIELDS = {}

    @cached_property
    def linked_data_attributes(self):
        return [*self.EXTRA_LINKED_DATA_FIELDS.keys(), *self.LINKED_DATA_FIELDS.keys()]

    @cached_property
    def linked_data_map(self):
        return {**self.LINKED_DATA_FIELDS, **self.EXTRA_LINKED_DATA_FIELDS}

    @cached_property
    def linked_data_fields(self):
        all_fields = (*self._meta.fields, *self._meta.many_to_many, *self._meta.private_fields)
        return [f for f in all_fields if f.name in self.linked_data_attributes]

    @cached_property
    def property_attributes(self):
        all_field_names = [
            f.name
            for f in (*self._meta.fields, *self._meta.many_to_many, *self._meta.private_fields)
        ]

        return [f for f in self.linked_data_attributes if f not in all_field_names]

    @cached_property
    def native_fields(self):
        return [f for f in self.linked_data_fields if not _is_pointer_field(f)]

    @cached_property
    def native_attributes(self):
        return [f.name for f in self.native_fields] + self.property_attributes

    @cached_property
    def related_fields(self):
        return [f for f in self.linked_data_fields if _is_pointer_field(f)]

    @cached_property
    def link_fields(self):
        return [f for f in self.related_fields if f.related_model is Link and not f.many_to_many]

    @cached_property
    def reference_fields(self):
        return [
            f for f in self.related_fields if f.related_model is CoreType and not f.many_to_many
        ]

    @cached_property
    def reference_list_fields(self):
        return [f for f in self.related_fields if f.related_model is CoreType and f.many_to_many]

    @cached_property
    def collection_fields(self):
        return [f for f in self.related_fields if f.related_model is Collection]

    @cached_property
    def namespaces(self):
        current = copy.deepcopy(self.NAMESPACES)
        for field in self.related_fields:
            for nm in getattr(field.related_model, "NAMESPACES", []):
                current.add(nm)
        return [n.removesuffix("#") for n in current]

    def _should_be_inlined(self, reference_field, value=None) -> bool:
        if reference_field.name in [
            "in_reply_to",
            "attributed_to",
            "to",
            "cc",
            "bto",
            "bcc",
            "replies",
        ]:
            return False

        if type(value) is str and value.startswith(str(AS2.Public)):
            return False

        return True

    def _should_paginate_collection(self, collection_field, value=None, page_number=1) -> bool:
        return False

    def _serialize_native_attributes(self, *args, **kw):
        data = {}

        for native_attribute in self.native_attributes:
            attr_name = self.linked_data_map[native_attribute]
            attr_value = getattr(self, native_attribute, None)

            match type(attr_value):
                case datetime.datetime | datetime.date:
                    value = attr_value.isoformat()
                case _:
                    value = attr_value

            data[attr_name] = value

        return data

    def _serialize_reference_fields(self, *args, **kw):
        data = {}

        for field in self.reference_fields:
            attr_name = self.linked_data_map[field.name]
            core_item = getattr(self, field.name, None)
            as_item = core_item and core_item.as2_item
            if self._should_be_inlined(reference_field=field, value=as_item):
                attr_value = as_item and as_item.serialize()
            else:
                attr_value = as_item and as_item.uri

            data[attr_name] = attr_value
        return data

    def _serialize_reference_list_fields(self, *args, **kw):
        data = {}
        for field in self.reference_list_fields:
            attr_name = self.linked_data_map[field.name]
            qs = getattr(self, field.name, None)
            items = [] if qs is None else qs.select_subclasses()

            attr_value = []
            should_inline = self._should_be_inlined(reference_field=field, value=None)
            for as_item in items:
                if as_item is not None:
                    if should_inline:
                        attr_value.append(as_item.serialize())
                    else:
                        attr_value.append(as_item.uri)

            if attr_value:
                data[attr_name] = attr_value

        return data

    def _serialize_link_fields(self, *args, **kw):
        data = {}

        for field in self.link_fields:
            attr_name = self.linked_data_map[field.name]
            attr_value = getattr(self, field.name, None)
            # TODO: Add logic to inline Link relationships.
            data[attr_name] = attr_value and attr_value.href

        return data

    def _serialize_collection_fields(self, *args, **kw):
        data = {}

        for field in self.collection_fields:
            attr_name = self.linked_data_map[field.name]
            collection = getattr(self, field.name, None)

            if collection is None:
                continue
            should_inline = self._should_be_inlined(reference_field=field, value=collection)
            if should_inline:
                attr_value = collection.serialize(
                    paginate=self._should_paginate_collection(
                        collection_field=field, value=collection
                    )
                )
            else:
                attr_value = collection.uri
            data[attr_name] = attr_value

        return data

    def serialize(self, *args, **kw):
        data = {}

        doc_id = getattr(self, "reference_id", None)
        if doc_id is not None:
            data["id"] = doc_id

        data.update(**self._serialize_native_attributes(*args, **kw))
        data.update(**self._serialize_reference_fields(*args, **kw))
        data.update(**self._serialize_reference_list_fields(*args, **kw))
        data.update(**self._serialize_link_fields(*args, **kw))
        data.update(**self._serialize_collection_fields(*args, **kw))

        return data

    def to_jsonld(self, include_context=True):
        data = self.serialize()

        if include_context:
            context = self.namespaces
            data["@context"] = [str(nm) for nm in context]
            return jsonld.compact(data, context)

        return data

    @classmethod
    def load(cls, document):
        g = cls.get_graph(document)
        subject_uri = rdflib.URIRef(document["id"])
        return LinkedDataModel.deserialize(subject_uri=subject_uri, g=g, default_model=cls)

    @staticmethod
    def get_graph(document, identifier=None):
        doc_id = document.get("id")
        if identifier is not None and doc_id is not None:
            assert str(doc_id) == str(identifier), "graph id mismatch"

        document_identifier = identifier or doc_id
        parsed_data = rdflib.parser.PythonInputSource(document, document_identifier)
        return rdflib.Graph().parse(parsed_data, format="json-ld")

    @staticmethod
    def deserialize(
        subject_uri: Optional[rdflib.URIRef | rdflib.BNode], g: rdflib.Graph, default_model=None
    ):
        if subject_uri is None:
            return None

        if type(subject_uri) is rdflib.URIRef:
            reference = Reference.make(str(subject_uri))
        else:
            reference = None

        has_predicates = len([*g.predicates(subject=subject_uri)]) > 0

        if not has_predicates and default_model is None:
            # This means that the graph only contains the uri as the
            # attribute. If we already resolved this reference, we can
            # return the referenced item.
            return reference and reference.referenced_item

        if not has_predicates and default_model is not None:
            obj, _ = default_model.objects.get_or_create(reference=reference)
            return obj

        as2_type = g.value(subject=subject_uri, predicate=RDF.type)

        if str(as2_type) in Actor.Types:
            klass = Actor
        elif str(as2_type) in (AS2.Collection, AS2.OrderedCollection):
            klass = Collection
        elif str(as2_type) in Object.Types:
            klass = Object
        elif str(as2_type) in Activity.Types:
            klass = Activity
        elif as2_type == AS2.Link:
            klass = Link
        else:
            logger.warning(f"Failed to determine type for {subject_uri}")
            return None

        item = reference and reference.referenced_item or klass(reference=reference)

        item.load_from_graph(subject_uri=subject_uri, g=g)
        return item

    class Meta:
        abstract = True


class Reference(StatusModel):
    STATUS = Choices("unknown", "resolved", "failed")
    uri = models.CharField(max_length=500, primary_key=True)
    domain = models.ForeignKey(
        "Domain", related_name="references", null=True, blank=True, on_delete=models.SET_NULL
    )
    resolved_at = MonitorField(monitor="status", when=["resolved"])
    failed_at = MonitorField(monitor="status", when=["failed"])

    @property
    def referenced_item(self):
        logger.debug(f"Getting item referenced by {self.uri}")
        try:
            return BaseActivityStreamsObject.objects.get_subclass(reference_id=self.uri)
        except BaseActivityStreamsObject.DoesNotExist:
            return None

    @property
    def is_resolved(self):
        try:
            return self.item is not None
        except Reference.item.RelatedObjectDoesNotExist:
            return False

    @property
    def is_local(self):
        return self.domain and self.domain.local

    @property
    def is_a_box(self):
        return Collection.objects.filter(
            Q(shared_inbox_actors__shared_inbox__reference=self)
            | Q(inbox_owner_actor__inbox__reference=self)
            | Q(outbox_owner_actor__inbox__reference=self)
        ).exists()

    @property
    def is_an_inbox(self):
        return Collection.objects.filter(
            Q(shared_inbox_actors__shared_inbox__reference=self)
            | Q(inbox_owner_actor__inbox__reference=self)
        ).exists()

    @property
    def is_an_outbox(self):
        return Collection.objects.filter(outbox_owner_actor__inbox__reference=self).exists()

    @transaction.atomic()
    def load(self, document):
        g = LinkedDataModel.get_graph(document, identifier=self.uri)
        return LinkedDataModel.deserialize(subject_uri=rdflib.URIRef(self.uri), g=g)

    def resolve(self, force=False):
        if self.is_resolved and not force:
            if self.status != self.STATUS.resolved:
                self.status = self.STATUS.resolved
                self.save()
            return

        # References to known, unresolvable items
        if any([self.uri.startswith(Actor.PUBLIC.uri), self.is_local]):
            self.status = self.STATUS.resolved
            self.save()
            return

        try:
            domain = Domain.get_default()
            signing_key = domain and domain.actor and domain.actor.main_cryptographic_keypair
            auth = signing_key and signing_key.signed_request_auth
            response = requests.get(
                self.uri,
                headers={"Accept": "application/activity+json,application/ld+json"},
                auth=auth,
            )
            response.raise_for_status()
            data = response.json()
            self.load(data)
            self.status = self.STATUS.resolved
        except (TypeError, AssertionError, requests.HTTPError):
            logger.exception(f"failed to resolve {self.uri}")
            self.status = self.STATUS.failed
            self.save()

    def __str__(self):
        return self.uri

    def generate_keypair(self, alias=None, force=False):
        if not self.is_local:
            raise ValueError("Can only generate keypairs for local resources")

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")
        public_pem = (
            private_key.public_key()
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode("ascii")
        )

        key_id = f"{self.uri}#{alias or str(generate_ulid())}"
        key_reference = Reference.make(key_id)
        if not force:
            return self.keypairs.create(
                reference=key_reference, private_pem=private_pem, public_pem=public_pem
            )
        else:
            key, _ = self.keypairs.update_or_create(
                reference=key_reference,
                defaults={"public_pem": public_pem, "private_pem": private_pem},
            )
            return key

    @classmethod
    def make(cls, uri: str):
        ref = cls.objects.filter(uri=uri).first()
        if not ref:
            domain = Domain.make(uri)
            ref = cls.objects.create(uri=uri, domain=domain)
        return ref


class CoreType(LinkedDataModel):
    NAMESPACES = set([AS2])

    id = ULIDField(default=generate_ulid, primary_key=True)
    objects = InheritanceManager()

    @property
    def as2_item(self):
        return CoreType.objects.get_subclass(id=self.id)


class Link(CoreType):
    class Types(models.TextChoices):
        LINK = str(AS2.Link)
        MENTION = str(AS2.Mention)

    class RelationTypes(models.TextChoices):
        ALTERNATE = ("alternate", "Designates a substitute for the link's context")
        APPENDIX = ("appendix", "Refers to an appendix.")
        BOOKMARK = ("bookmark", "Refers to a bookmark or entry point.")
        CHAPTER = ("chapter", "Refers to a chapter in a collection of resources.")
        CONTENTS = ("contents", "Refers to a table of contents.")
        COPYRIGHT = ("copyright", "Copyright statement that applies to the link")
        CURRENT = ("current", "the most recent item(s) in a collection of resources")
        DESCRIBED_BY = ("describedby", "information about the link's context.")
        EDIT = ("edit", "used to edit the link's context")
        EDIT_MEDIA = ("edit-media", "can be used to edit media associated with the link")
        ENCLOSURE = ("enclosure", "Identifies a related resource that is potentially large")
        FIRST = ("first", "furthest preceding resource in a series of resources")
        GLOSSARY = ("glossary", "Refers to a glossary of terms.")
        HELP = ("help", "Refers to a resource offering help")
        HUB = ("hub", "Refers to a hub that enables registration for notification of updates")
        INDEX = ("index", "Refers to an index")
        LAST = ("last", "furthest following resource in a series")
        LATEST = ("latest-version", "latest version of the context")
        LICENSE = ("license", "Refers to a license associated with the link's context.")
        NEXT = ("next", "Refers to the next resource in a ordered series of resources.")
        NEXT_ARCHIVE = ("next-archive", "Refers to the immediately following archive resource.")
        PAYMENT = ("payment", "indicates a resource where payment is accepted.")
        PREV = ("prev", "Synonym for 'previous'")
        PREDECESSOR_VERSION = ("predecessor-version", "predecessor version in the version history")
        PREVIOUS = ("previous", "Previous resource in an ordered series of resources")
        PREV_ARCHIVE = ("prev-archive", "Refers to the immediately preceding archive resource")
        RELATED = ("related", "Identifies a related resource")
        REPLIES = ("replies", "Identifies a resource that is a reply to the context of the link")
        SECTION = ("section", "Refers to a section in a collection of resources")
        SELF = ("self", "Conveys an identifier for the link's context")
        SERVICE = ("service", "Indicates a URI that can be used to retrieve a service document")
        START = ("start", "Refers to the first resource in a collection of resources")
        STYLESHEET = ("stylesheet", "Refers to an external style sheet")
        SUBSECTION = ("subsection", "subsection in a collection of resources")
        SUCCESSOR_VERSION = ("successor-version", "successor version in the version history")
        UP = ("up", "Refers to a parent document in a hierarchy of documents")
        VERSION_HISTORY = ("version-history", "version history for the context")
        VIA = ("via", "source of the information in the link's context")
        WORKING_COPY = ("working-copy", "Points to a working copy for this resource")
        WORKING_COPY_OF = ("working-copy-of", "versioned resource originating this working copy")

    core_type = models.OneToOneField(CoreType, parent_link=True, on_delete=models.CASCADE)

    type = models.CharField(max_length=48, choices=Types.choices, default=Types.LINK)
    reference = models.ForeignKey(
        Reference, null=True, blank=True, related_name="links", on_delete=models.SET_NULL
    )
    href = models.URLField()
    relations = ArrayField(
        models.CharField(max_length=50, choices=RelationTypes.choices), null=True, blank=True
    )
    media_type = models.CharField(max_length=48, null=True, blank=True)
    name = models.TextField(null=True, blank=True)
    language = models.CharField(max_length=5, null=True, blank=True)
    height = models.PositiveIntegerField(null=True)
    width = models.PositiveIntegerField(null=True)
    preview = models.ForeignKey(
        Reference,
        related_name="link_previews",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )

    def load_from_graph(self, g: rdflib.Graph, subject_uri: rdflib.URIRef | rdflib.BNode):
        to_native = lambda x: x and x.toPython()

        self.type = g.value(subject=subject_uri, predicate=RDF.type)
        self.href = to_native(g.value(subject=subject_uri, predicate=AS2.href))
        self.media_type = to_native(g.value(subject=subject_uri, predicate=AS2.mediaType))
        self.name = to_native(g.value(subject=subject_uri, predicate=AS2.name))
        self.height = to_native(g.value(subject=subject_uri, predicate=AS2.height))
        self.width = to_native(g.value(subject=subject_uri, predicate=AS2.width))
        self.save()


class BaseActivityStreamsObject(CoreType):
    LINKED_DATA_FIELDS = {
        "published": "published",
        "updated": "updated",
        "name": "name",
        "content": "content",
        "media_type": "mediaType",
        "summary": "summary",
        "start_time": "startTime",
        "end_time": "endTime",
        "duration": "duration",
        "context": "context",
        "generator": "generator",
        "icon": "icon",
        "image": "image",
        "location": "location",
        "preview": "preview",
        "replies": "replies",
        "url": "url",
        "tags": "tag",
        "in_reply_to": "inReplyTo",
        "attributed_to": "attributedTo",
        "attachments": "attachment",
        "audience": "audience",
        "to": "to",
        "cc": "cc",
        "bto": "bto",
        "bcc": "bcc",
    }

    reference = models.OneToOneField(
        Reference, related_name="item", null=True, blank=True, on_delete=models.SET_NULL
    )
    published = models.DateTimeField(null=True, blank=True)
    updated = models.DateTimeField(null=True, blank=True)
    name = models.TextField(null=True, blank=True)
    source = models.TextField(null=True, blank=True)
    content = models.TextField(null=True, blank=True)
    media_type = models.CharField(max_length=64, null=True, blank=True)
    summary = models.TextField(null=True, blank=True)
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    duration = models.DurationField(null=True, blank=True)

    replies = models.OneToOneField(
        "Collection",
        related_name="replies_of",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    url = models.ForeignKey(
        Link, related_name="links", null=True, blank=True, on_delete=models.SET_NULL
    )

    context = models.ForeignKey(
        CoreType,
        related_name="items_in_context",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    generator = models.ForeignKey(
        CoreType,
        related_name="generators_of",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    icon = models.ForeignKey(
        CoreType,
        related_name="icons_of",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    image = models.ForeignKey(
        CoreType,
        related_name="generic_images_of",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    location = models.ForeignKey(
        CoreType,
        related_name="generic_locations_of",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    preview = models.ForeignKey(
        CoreType,
        related_name="generic_previews_of",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    tags = models.ManyToManyField(CoreType, related_name="tags")
    in_reply_to = models.ManyToManyField(CoreType, related_name="in_reply_to")
    attributed_to = models.ManyToManyField(CoreType, related_name="attributed_to")
    attachments = models.ManyToManyField(CoreType, related_name="attachments")
    audience = models.ManyToManyField(CoreType, related_name="audience")
    to = models.ManyToManyField(CoreType, related_name="to")
    cc = models.ManyToManyField(CoreType, related_name="cc")
    bto = models.ManyToManyField(CoreType, related_name="bto")
    bcc = models.ManyToManyField(CoreType, related_name="bcc")

    objects = InheritanceManager()

    @property
    def uri(self):
        return self.reference_id

    def load_from_graph(self, g: rdflib.Graph, subject_uri: rdflib.URIRef | rdflib.BNode):

        if self.reference and self.reference.domain and self.reference.domain.blocked:
            raise ValueError(f"{self.reference.domain.name} is blocked")

        def to_native(predicate):
            value = g.value(subject=subject_uri, predicate=predicate)
            return value and value.toPython()

        def to_related(predicate):
            value = g.value(subject=subject_uri, predicate=predicate)
            item = value and LinkedDataModel.deserialize(subject_uri=value, g=g)
            return item and item

        def to_list(predicate):
            data = [
                LinkedDataModel.deserialize(subject_uri=o, g=g)
                for _, _, o in g.triples((subject_uri, predicate, None))
            ]
            return [d for d in data if d is not None]

        self.published = to_native(predicate=AS2.published)
        self.updated = to_native(predicate=AS2.updated)
        self.name = to_native(predicate=AS2.name)
        self.content = to_native(predicate=AS2.content)
        self.context = to_related(predicate=AS2.context)
        self.image = to_related(predicate=AS2.image)
        self.preview = to_related(predicate=AS2.preview)
        self.replies = to_related(predicate=AS2.replies)
        self.save()

        for tag in to_list(AS2.tag):
            self.tags.add(tag)

        for attachment in to_list(AS2.attachment):
            self.attachments.add(attachment)

        for in_reply_to in to_list(AS2.inReplyTo):
            self.in_reply_to.add(in_reply_to)

        for attributed_to in to_list(AS2.attributedTo):
            self.attributed_to.add(attributed_to)

        for audience in to_list(AS2.audience):
            self.audience.add(audience)

        for to in to_list(AS2.to):
            self.to.add(to)

        for bto in to_list(AS2.bto):
            self.bto.add(bto)

        for cc in to_list(AS2.cc):
            self.cc.add(cc)

        for bcc in to_list(AS2.bcc):
            self.bcc.add(bcc)

    @classmethod
    def make(cls, uri, **kw):
        reference = Reference.make(uri)
        obj, _ = cls.objects.get_or_create(reference=reference, defaults=kw)
        return obj

    def __str__(self):
        return self.reference_id


class Collection(BaseActivityStreamsObject):
    EXTRA_LINKED_DATA_FIELDS = {
        "type": "type",
        "total_items": "totalItems",
        "current": "current",
        "first": "first",
        "last": "last",
        "items": "items",
    }

    class OrderingMethods(models.TextChoices):
        NONE = "Not Ordered"
        CREATE_TIME = "Creation Time"
        KEY = "Order Key"

    ordering_method = models.CharField(
        max_length=16, choices=OrderingMethods.choices, default=OrderingMethods.NONE
    )
    collection_items = models.ManyToManyField(
        CoreType, through="CollectionItem", related_name="collections"
    )

    base_object = models.OneToOneField(
        BaseActivityStreamsObject,
        related_name="as_collection",
        parent_link=True,
        on_delete=models.CASCADE,
    )

    @property
    def is_ordered(self):
        return self.ordering_method != self.OrderingMethods.NONE

    @property
    def type(self):
        return "OrderedCollection" if self.is_ordered else "Collection"

    @property
    def total_items(self):
        return self.collection_items.count()

    @property
    def order_by_key(self):
        return {
            self.OrderingMethods.KEY: "collections__collection_items__in_collections__order",
            self.OrderingMethods.CREATE_TIME: "collections__collection_items__in_collections__id",
        }.get(self.ordering_method)

    @property
    def items(self) -> models.QuerySet:
        qs = CoreType.objects.filter(collections=self).select_subclasses()
        order_by = self.order_by_key
        if order_by is not None:
            qs = qs.order_by(order_by)

        return qs

    @property
    def ordered_collection_items(self):
        return CollectionItem.objects.filter(collection=self)

    @property
    def highest_order_value(self):
        return self.ordered_collection_items.aggregate(highest=Max("order")).get("highest", 0)

    def _should_be_inlined(self, reference_field, value=None):
        if reference_field.name == "items":
            return False

        return super()._should_be_inlined(reference_field=reference_field, value=value)

    def _serialize_collection_items(self, start, end):
        return [it.uri for it in self.items[start:end]]

    def serialize(self, *args, **kw):
        collection_size = self.total_items
        page_number = int(kw.pop("page_number", 1))

        should_paginate = page_number > 1 or kw.pop(
            "paginate", collection_size > app_settings.Instance.collection_page_size
        )
        logger.debug(f"Will paginate {self.uri}? {should_paginate}")

        data = {
            "id": self.uri,
            "type": self.type,
            "totalItems": self.total_items,
        }

        if not should_paginate:
            attr_name = "orderedItems" if self.is_ordered else "items"
            data.update({attr_name: self._serialize_collection_items(0, collection_size)})
        else:
            data.update({"first": f"{self.uri}?page=1"})

        return data

    def reset_ordering(self):
        for idx, item in enumerate(self.items.all(), start=1):
            item.order = idx
            item.save()

    def append(self, item: CoreType) -> "CollectionItem":
        existing = self.collection_items.filter(id=item.id).first()

        if existing:
            return existing

        if self.ordering_method == self.OrderingMethods.NONE:
            return self.collection_items.add(item)

        if self.ordering_method == self.OrderingMethods.CREATE_TIME:
            return CollectionItem.objects.create(
                collection=self, item=item, order=timezone.now().timestamp()
            )

        if self.total_items == 0:
            return CollectionItem.objects.create(collection=self, item=item, order=1.0)

        new_item_order = max(self.highest_order_value, self.total_items) + 1
        if new_item_order >= CollectionItem.MAX_ORDER_VALUE:
            new_item_order = (CollectionItem.MAX_ORDER_VALUE + new_item_order) / 2.0

        return CollectionItem.objects.create(collection=self, item=item, order=new_item_order)

    def prepend(self, item: CoreType) -> "CollectionItem":
        existing = self.collection_items.filter(item=item).first()

        if existing:
            return existing

        if self.ordering_method == self.OrderingMethods.NONE:
            return self.collection_items.create(item=item)

        if self.ordering_method == self.OrderingMethods.CREATE_TIME:
            return self.collection_items.create(item=item, order=timezone.now().timestamp())

        if self.total_items == 0:
            return self.collection_items.create(item=item, order=1.0)

        first_item = CollectionItem.objects.filter(collection=self).order_by("order").first()
        lowest_order_value = first_item.order

        if lowest_order_value < 0:
            self.reset_ordering()
            lowest_order_value = 1
        new_item_order = lowest_order_value / 2.0

        return self.collection_items.create(item=item, order=new_item_order)


class CollectionItem(models.Model):
    MAX_ORDER_VALUE = sys.float_info.max
    collection = models.ForeignKey(Collection, on_delete=models.CASCADE)
    created = models.DateTimeField(auto_now_add=True)
    item = models.ForeignKey(CoreType, related_name="in_collections", on_delete=models.CASCADE)
    order = models.FloatField(default=0.0)


class Object(BaseActivityStreamsObject):
    EXTRA_LINKED_DATA_FIELDS = {"type": "type"}

    base_object = models.OneToOneField(
        BaseActivityStreamsObject,
        related_name="as_object",
        parent_link=True,
        on_delete=models.CASCADE,
    )

    class Types(models.TextChoices):
        ARTICLE = str(AS2.Article)
        AUDIO = str(AS2.Audio)
        DOCUMENT = str(AS2.Document)
        EVENT = str(AS2.Event)
        IMAGE = str(AS2.Image)
        QUESTION = str(AS2.Question)
        NOTE = str(AS2.Note)
        PAGE = str(AS2.Page)
        PLACE = str(AS2.Place)
        PROFILE = str(AS2.Profile)
        RELATIONSHIP = str(AS2.Relationship)
        TOMBSTONE = str(AS2.Tombstone)
        VIDEO = str(AS2.Video)
        HASHTAG = str(AS2.Hashtag)

    type = models.CharField(max_length=128, choices=Types.choices)

    def _should_be_inlined(self, reference_field, value=None):
        if reference_field.name == "replies":
            return True

        return super()._should_be_inlined(reference_field=reference_field, value=value)

    def serialize(self, *args, **kw):
        data = super().serialize(*args, **kw)

        if self.type == self.Types.QUESTION:
            properties = QuestionExtraData.objects.filter(question=self).first()
            question_data = properties and properties.serialize()
            if question_data:
                data.update(question_data)

        return data

    def load_from_graph(self, subject_uri: rdflib.URIRef | rdflib.BNode, g: rdflib.Graph):
        as2_type = g.value(subject=subject_uri, predicate=RDF.type)

        self.type = as2_type and as2_type.toPython()

        super().load_from_graph(subject_uri=subject_uri, g=g)

    def __str__(self):
        return self.uri or f"Unreferenced object #{self.id} ({self.get_type_display()}"


class Actor(BaseActivityStreamsObject):
    NAMESPACES = set([AS2, SEC_V1])
    EXTRA_LINKED_DATA_FIELDS = {
        "type": "type",
        "inbox": "inbox",
        "outbox": "outbox",
        "following": "following",
        "followers": "followers",
        "liked": "liked",
        "preferred_username": "preferredUsername",
    }

    class Types(models.TextChoices):
        PERSON = str(AS2.Person)
        GROUP = str(AS2.Group)
        SERVICE = str(AS2.Service)
        ORGANIZATION = str(AS2.Organization)
        APPLICATION = str(AS2.Application)

    base_object = models.OneToOneField(
        BaseActivityStreamsObject,
        related_name="as_actor",
        parent_link=True,
        on_delete=models.CASCADE,
    )
    type = models.CharField(max_length=64, choices=Types.choices)
    preferred_username = models.CharField(max_length=100, null=True, blank=True)

    shared_inbox = models.ForeignKey(
        Collection,
        related_name="shared_inbox_actors",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    inbox = models.OneToOneField(
        Collection,
        related_name="inbox_owner_actor",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    outbox = models.OneToOneField(
        Collection,
        related_name="outbox_owner_actor",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    following = models.OneToOneField(
        Collection, related_name="actor_follows", null=True, blank=True, on_delete=models.SET_NULL
    )
    followers = models.OneToOneField(
        Collection,
        related_name="actor_followers",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    liked = models.OneToOneField(
        Collection, related_name="actor_liked", null=True, blank=True, on_delete=models.SET_NULL
    )

    @property
    def main_cryptographic_keypair(self):
        return self.reference.keypairs.exclude(revoked=True).order_by("created").first()

    @property
    def followed_by(self):
        return (
            self.followers and self.followers.items.select_subclasses() or CoreType.objects.none()
        )

    @property
    def follows(self):
        return (
            self.following and self.following.items.select_subclasses() or CoreType.objects.none()
        )

    @property
    def alternative_identities(self):
        return [self.account.subject_name] if self.account else []

    @property
    def inbox_url(self):
        return self.inbox and self.inbox.uri

    @property
    def outbox_url(self):
        return self.outbox and self.outbox.uri

    @property
    def followers_url(self):
        return self.followers and self.followers.uri

    @property
    def following_url(self):
        return self.following and self.following.uri

    @property
    def followers_inboxes(self):
        actors = Actor.objects.filter(id__in=self.followers.items.values_list("id", flat=True))
        return Collection.objects.filter(
            id__in=actors.annotate(
                target_inbox=Case(
                    When(shared_inbox__isnull=False, then=F("shared_inbox")),
                    When(shared_inbox__isnull=True, then=F("inbox")),
                    default=Value(None),
                )
            )
            .exclude(target_inbox=None)
            .distinct("target_inbox")
            .values_list("target_inbox", flat=True)
        )

    @property
    def username(self):
        try:
            return self.account.username
        except AttributeError:
            return None

    @property
    def is_local(self):
        try:
            return self.account.domain.local
        except AttributeError:
            return False

    def _should_be_inlined(self, reference_field, value=None):
        if isinstance(value, Collection):
            return False
        return super()._should_be_inlined(reference_field=reference_field, value=value)

    def serialize(self, *args, **kw):
        data = super().serialize(*args, **kw)
        data.update({"preferredUsername": self.preferred_username})
        if self.main_cryptographic_keypair:
            data["publicKey"] = self.main_cryptographic_keypair.serialize()

        return data

    def make_box(self, uri, name) -> Collection:
        return Collection.make(uri=uri, name=name, ordering_method=Collection.OrderingMethods.KEY)

    def load_from_graph(self, subject_uri: rdflib.URIRef | rdflib.BNode, g: rdflib.Graph):

        to_native = lambda x: x and x.toPython()

        self.type = to_native(g.value(subject=subject_uri, predicate=RDF.type))

        super().load_from_graph(subject_uri=subject_uri, g=g)

        # Seems like AS2.inbox also exists as an alias for LDP.inbox, so we check both
        self.inbox = LinkedDataModel.deserialize(
            g.value(subject=subject_uri, predicate=LDP.inbox | AS2.inbox),
            g=g,
            default_model=Collection,
        )
        self.outbox = LinkedDataModel.deserialize(
            g.value(subject=subject_uri, predicate=LDP.outbox | AS2.outbox),
            g=g,
            default_model=Collection,
        )

        self.following = LinkedDataModel.deserialize(
            g.value(subject=subject_uri, predicate=AS2.following), g=g, default_model=Collection
        )
        self.followers = LinkedDataModel.deserialize(
            g.value(subject=subject_uri, predicate=AS2.followers), g=g, default_model=Collection
        )
        self.preferred_username = to_native(
            g.value(subject=subject_uri, predicate=AS2.preferredUsername)
        )
        self.save()

        self.reference.domain.accounts.get_or_create(actor=self, username=self.preferred_username)

        try:
            key_id = g.value(subject=subject_uri, predicate=SEC.publicKey)
            assert key_id is not None, "No public key provided"
            owner = g.value(subject=key_id, predicate=SEC.owner)
            assert subject_uri == owner, f"Actor {subject_uri} is not key owner"
            private_pem = to_native(g.value(subject=key_id, predicate=SEC.privateKeyPem))
            public_pem = to_native(g.value(subject=key_id, predicate=SEC.publicKeyPem))

            self.reference.keypairs.update_or_create(
                reference=Reference.make(str(key_id)),
                defaults={"public_pem": public_pem, "private_pem": private_pem},
            )
        except AssertionError as exc:
            logger.warning(f"Failed to get keypair from {subject_uri}: {exc}")

    def __str__(self):
        return self.uri

    @classproperty
    def PUBLIC(cls):
        return _get_public_actor()

    @classproperty
    def PUBLIC_INBOX(cls):
        actor = cls.PUBLIC
        if actor.inbox is None:
            actor.inbox = actor.make_box(str(AS2["Public/Inbox"], name="Public Inbox"))
            actor.save()
        return actor.inbox


class Activity(BaseActivityStreamsObject):
    EXTRA_LINKED_DATA_FIELDS = {
        "type": "type",
        "actor": "actor",
        "object": "object",
        "target": "target",
        "result": "result",
        "instrument": "instrument",
    }

    class Types(models.TextChoices):
        ACCEPT = str(AS2.Accept)
        ADD = str(AS2.Add)
        ANNOUNCE = str(AS2.Announce)
        ARRIVE = str(AS2.Arrive)
        BLOCK = str(AS2.Block)
        CREATE = str(AS2.Create)
        DELETE = str(AS2.Delete)
        DISLIKE = str(AS2.Dislike)
        FLAG = str(AS2.Flag)
        FOLLOW = str(AS2.Follow)
        IGNORE = str(AS2.Ignore)
        INVITE = str(AS2.Invite)
        JOIN = str(AS2.Join)
        LEAVE = str(AS2.Leave)
        LIKE = str(AS2.Like)
        LISTEN = str(AS2.Listen)
        MOVE = str(AS2.Move)
        OFFER = str(AS2.Offer)
        QUESTION = str(AS2.Question)
        REJECT = str(AS2.Reject)
        READ = str(AS2.Read)
        REMOVE = str(AS2.Remove)
        TENTATIVE_REJECT = str(AS2.TentativeReject)
        TENTATIVE_ACCEPT = str(AS2.TentativeAccept)
        TRAVEL = str(AS2.Travel)
        UNDO = str(AS2.Undo)
        UPDATE = str(AS2.Update)
        VIEW = str(AS2.View)

    base_object = models.OneToOneField(
        BaseActivityStreamsObject,
        related_name="as_activity",
        parent_link=True,
        on_delete=models.CASCADE,
    )

    type = models.CharField(max_length=128, choices=Types.choices, db_index=True)

    actor = models.ForeignKey(
        CoreType,
        related_name="activities_as_actor",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    object = models.ForeignKey(
        CoreType,
        related_name="activities_as_object",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    target = models.ForeignKey(
        CoreType,
        related_name="activities_as_target",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    result = models.ForeignKey(
        CoreType,
        related_name="activities_as_result",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    instrument = models.ForeignKey(
        CoreType,
        related_name="activities_as_instrument",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    def _should_be_inlined(self, reference_field, value=None):
        if reference_field.name == "actor":
            return False

        if reference_field.name == "object" and type(value) is Activity:
            return False

        if self.type == self.Types.CREATE and reference_field.name == "object":
            return True

        return super()._should_be_inlined(reference_field=reference_field, value=value)

    def load_from_graph(self, subject_uri: rdflib.URIRef | rdflib.BNode, g: rdflib.Graph):
        def parse(predicate):
            value = g.value(subject=subject_uri, predicate=predicate)
            if value == subject_uri:
                raise UnprocessableJsonLd(
                    f"Circular reference: {subject_uri} is both document id and {predicate}"
                )
            obj = value and LinkedDataModel.deserialize(subject_uri=value, g=g)
            return obj and obj

        as2_type = g.value(subject=subject_uri, predicate=RDF.type)
        self.type = as2_type and as2_type.toPython()

        super().load_from_graph(subject_uri=subject_uri, g=g)

        self.actor = parse(predicate=AS2.actor)
        self.object = parse(predicate=AS2.object)
        self.target = parse(predicate=AS2.target)
        self.result = parse(predicate=AS2.result)
        self.instrument = parse(predicate=AS2.instrument)
        self.save()

    def post(self):
        try:
            document = self.to_jsonld()
            assert self.actor is not None, f"Activity {self.uri} has no actor"
            assert self.actor.is_local, f"Activity {self.uri} is not from a local actor"
            for inbox in self.actor.followers_inboxes:
                Message.objects.create(
                    activity=self.reference,
                    sender=self.actor.reference,
                    recipient=inbox.reference,
                    document=document,
                )
        except AssertionError as exc:
            logger.warning(exc)

    def _do_nothing(self):
        pass

    def _do_follow(self):
        follower = self.actor and self.actor.as2_item
        followed = self.object and self.object.as2_item

        has_accept = Activity.objects.filter(
            actor=self.object, type=Activity.Types.ACCEPT, object=self
        ).exists()

        try:
            approval_required = (
                followed is not None and followed.account.manually_approves_followers
            )
        except Actor.account.RelatedObjectDoesNotExist:
            approval_required = False

        can_accept = has_accept or not approval_required

        if not can_accept:
            return

        if (
            follower
            and follower.following is not None
            and self.object not in follower.following.items
        ):
            follower.following.append(item=self.object)

        if (
            followed
            and followed.followers is not None
            and self.actor not in followed.followers.items
        ):
            followed.followers.append(item=self.actor)

            if followed.is_local:
                logger.info(f"{followed} accepts follow from {follower}")

                accept = followed.account.domain.build_activity(
                    actor=self.object, type=Activity.Types.ACCEPT, object=self
                )
                Message.objects.create(
                    activity=accept.reference,
                    sender=followed.reference,
                    recipient=follower.inbox.reference,
                    document=accept.to_jsonld(),
                )

    def _undo_follow(self):
        follower = self.actor and self.actor.as2_item
        followed = self.object and self.object.as2_item

        if follower and follower.following is not None:
            follower.following.collection_items.remove(self.object)
        if followed and followed.followers is not None:
            followed.followers.collection_items.remove(self.actor)

    def _do_accept(self):
        # Accepted activity is the object of this activity. We just do it.
        if self.object is not None:
            self.object.as2_item.do()

    def _do_create(self):
        if all(
            [
                self.actor is not None,
                self.actor.outbox is not None,
                Actor.PUBLIC in self.to.all() or Actor.PUBLIC in self.cc.all(),
            ]
        ):
            self.actor.outbox.append(self)

    def _do_question(self):
        return self._do_create()

    def _do_undo(self):
        to_undo = self.object and self.object.as2_item
        if not isinstance(to_undo, Activity):
            return

        if to_undo:
            to_undo.undo()

    def _undo_undo(self):
        logger.info("Trying to undo an Undo activity. Should it be possible?")
        return

    def do(self):
        if self.activities_as_object.filter(type=Activity.Types.UNDO).exists():
            logger.warning("Ignoring this task as it will be undone")
            return

        if not self.actor:
            logger.warning("Can not do anything with activity that has no actor")
            return

        action = {
            str(AS2.Accept): self._do_accept,
            str(AS2.Add): self._do_nothing,
            str(AS2.Announce): self._do_nothing,
            str(AS2.Arrive): self._do_nothing,
            str(AS2.Block): self._do_nothing,
            str(AS2.Create): self._do_create,
            str(AS2.Delete): self._do_nothing,
            str(AS2.Dislike): self._do_nothing,
            str(AS2.Flag): self._do_nothing,
            str(AS2.Follow): self._do_follow,
            str(AS2.Ignore): self._do_nothing,
            str(AS2.Invite): self._do_nothing,
            str(AS2.Join): self._do_nothing,
            str(AS2.Leave): self._do_nothing,
            str(AS2.Like): self._do_nothing,
            str(AS2.Listen): self._do_nothing,
            str(AS2.Move): self._do_nothing,
            str(AS2.Offer): self._do_nothing,
            str(AS2.Question): self._do_question,
            str(AS2.Reject): self._do_nothing,
            str(AS2.Read): self._do_nothing,
            str(AS2.Remove): self._do_nothing,
            str(AS2.TentativeReject): self._do_nothing,
            str(AS2.TentativeAccept): self._do_nothing,
            str(AS2.Travel): self._do_nothing,
            str(AS2.Undo): self._do_undo,
            str(AS2.Update): self._do_nothing,
            str(AS2.View): self._do_nothing,
        }.get(self.type, self._do_nothing)

        action()

        signals.activity_done.send_robust(activity=self, sender=self.__class__)

    def undo(self):
        action = {
            str(AS2.Accept): self._do_nothing,
            str(AS2.Add): self._do_nothing,
            str(AS2.Announce): self._do_nothing,
            str(AS2.Arrive): self._do_nothing,
            str(AS2.Block): self._do_nothing,
            str(AS2.Create): self._do_nothing,
            str(AS2.Delete): self._do_nothing,
            str(AS2.Dislike): self._do_nothing,
            str(AS2.Flag): self._do_nothing,
            str(AS2.Follow): self._undo_follow,
            str(AS2.Ignore): self._do_nothing,
            str(AS2.Invite): self._do_nothing,
            str(AS2.Join): self._do_nothing,
            str(AS2.Leave): self._do_nothing,
            str(AS2.Like): self._do_nothing,
            str(AS2.Listen): self._do_nothing,
            str(AS2.Move): self._do_nothing,
            str(AS2.Offer): self._do_nothing,
            str(AS2.Question): self._do_nothing,
            str(AS2.Reject): self._do_nothing,
            str(AS2.Read): self._do_nothing,
            str(AS2.Remove): self._do_nothing,
            str(AS2.TentativeReject): self._do_nothing,
            str(AS2.TentativeAccept): self._do_nothing,
            str(AS2.Travel): self._do_nothing,
            str(AS2.Undo): self._do_nothing,
            str(AS2.Update): self._do_nothing,
            str(AS2.View): self._do_nothing,
        }.get(self.type, self._do_nothing)

        action()

    class Meta:
        verbose_name_plural = "Activities"


class QuestionExtraData(LinkedDataModel):
    NAMESPACES = set([AS2])

    LINKED_DATA_FIELDS = {"closed": "closed", "any_of": "anyOf", "one_of": "oneOf"}
    # Only applicable for Question Activities (or Objects if non-standard)

    question = models.OneToOneField(
        BaseActivityStreamsObject, related_name="question_properties", on_delete=models.CASCADE
    )
    closed = models.DateTimeField(null=True, blank=True)
    any_of = models.ManyToManyField(CoreType, related_name="multiple_choice_alternatives")
    one_of = models.ManyToManyField(CoreType, related_name="alternatives")

    def _should_be_inlined(self, reference_field, value=None):
        return True


class RelationshipProperties(models.Model):
    class Types(models.TextChoices):
        ACQUAINTANCE_OF = (
            PURL_RELATIONSHIP.acquaintanceOf,
            "subject is familiar with object, not friendship",
        )
        AMBIVALENT_OF = (
            PURL_RELATIONSHIP.ambivalentOf,
            "subject has mixed feelings or emotions for object",
        )
        ANCESTOR_OF = (PURL_RELATIONSHIP.ancestorOf, "subject is a descendant of object")
        ANTAGONIST_OF = (PURL_RELATIONSHIP.antagonistOf, "subject opposes or contends object")
        APPRENTICE_TO = (PURL_RELATIONSHIP.apprenticeTo, "object is a counselor for subject")
        CHILD_OF = (
            PURL_RELATIONSHIP.childOf,
            "subject was given birth to or nurtured and raised by object",
        )
        CLOSE_FRIEND_OF = (
            PURL_RELATIONSHIP.closeFriendOf,
            "subject and object share a close mutual friendship",
        )
        COLLABORATES_WITH = (
            PURL_RELATIONSHIP.collaboratesWith,
            "subject and object work towards a common goal",
        )
        COLLEAGUE_OF = (
            PURL_RELATIONSHIP.colleagueOf,
            "subject and object are members of the same profession",
        )
        DESCENDANT_OF = (
            PURL_RELATIONSHIP.descendantOf,
            "A person from whom this person is descended",
        )
        EMPLOYED_BY = (
            PURL_RELATIONSHIP.employedBy,
            "A person for whom this person's services have been engaged",
        )
        EMPLOYER_OF = (
            PURL_RELATIONSHIP.employerOf,
            "A person who engages the services of this person",
        )
        ENEMY_OF = (
            PURL_RELATIONSHIP.enemyOf,
            "A person towards whom this person feels hatred, or opposes the interests of",
        )
        ENGAGED_TO = (PURL_RELATIONSHIP.engagedTo, "A person to whom this person is betrothed")
        FRIEND_OF = (
            PURL_RELATIONSHIP.friendOf,
            "A person who shares mutual friendship with this person",
        )
        GRANDCHILD_OF = (
            PURL_RELATIONSHIP.grandchildOf,
            "A person who is a child of any of this person's children",
        )
        GRANDPARENT_OF = (
            PURL_RELATIONSHIP.grandparentOf,
            "A person who is the parent of any of this person's parents",
        )
        HAS_MET = (
            PURL_RELATIONSHIP.hasMet,
            "A person who has met this person whether in passing or longer",
        )
        INFLUENCED_BY = (PURL_RELATIONSHIP.influencedBy, "a person who has influenced this person")
        KNOWS_BY_REPUTATION = (
            PURL_RELATIONSHIP.knowsByReputation,
            "subject knows object for a particular action, position or field of endeavour",
        )
        KNOWS_IN_PASSING = (
            PURL_RELATIONSHIP.knowsInPassing,
            "A person whom this person has slight or superficial knowledge of",
        )
        KNOWS_OF = (
            PURL_RELATIONSHIP.knowsOf,
            "A person who has come to be known to this person through their actions or position",
        )
        LIFE_PARTNER_OF = (
            PURL_RELATIONSHIP.lifePartnerOf,
            "A person who has made a long-term commitment to this person's",
        )
        LIVES_WITH = (
            PURL_RELATIONSHIP.livesWith,
            "A person who shares a residence with this person",
        )
        LOST_CONTACT_WITH = (
            PURL_RELATIONSHIP.lostContactWith,
            "A person who was once known by this person but has subsequently become uncontactable",
        )
        MENTOR_OF = (
            PURL_RELATIONSHIP.mentorOf,
            "A person who serves as a trusted counselor or teacher to this person",
        )
        NEIGHBOR_OF = (
            PURL_RELATIONSHIP.neighborOf,
            "A person who lives in the same locality as this person",
        )
        PARENT_OF = (
            PURL_RELATIONSHIP.parentOf,
            "A person who has given birth to or nurtured and raised this person",
        )
        PARTICIPANT = (
            PURL_RELATIONSHIP.participant,
            "A person who has participates in the relationship",
        )
        PARTICIPANT_IN = (
            PURL_RELATIONSHIP.participantIn,
            "A person who is a participant in the relationship",
        )
        RELATIONSHIP = (
            PURL_RELATIONSHIP.Relationship,
            "subject has a particular type of connection or dealings with subject",
        )
        SIBLING_OF = (
            PURL_RELATIONSHIP.siblingOf,
            "A person having one or both parents in common with this person",
        )
        SPOUSE_OF = (PURL_RELATIONSHIP.spouseOf, "A person who is married to this person")
        WORKS_WITH = (
            PURL_RELATIONSHIP.worksWith,
            "A person who works for the same employer as this person",
        )
        WOULD_LIKE_TO_KNOW = (
            PURL_RELATIONSHIP.wouldLikeToKnow,
            "A person whom this person would desire to know more closely",
        )

    relationship = models.OneToOneField(
        Object, related_name="relationship_properties", on_delete=models.CASCADE
    )

    relationship_type = models.CharField(max_length=64, db_index=True, choices=Types.choices)
    subject = models.ForeignKey(
        Reference, related_name="subject_of_relationships", on_delete=models.CASCADE
    )
    object = models.ForeignKey(
        Reference, related_name="object_of_relationships", on_delete=models.CASCADE
    )


class CryptographicKeyPair(LinkedDataModel):
    NAMESPACES = set([SEC_V1])

    LINKED_DATA_FIELDS = {"actor": "owner", "public_pem": "publicKeyPem"}

    reference = models.OneToOneField(Reference, on_delete=models.CASCADE)
    actor = models.ForeignKey(Reference, related_name="keypairs", on_delete=models.CASCADE)
    private_pem = models.TextField(null=True, blank=True)
    public_pem = models.TextField()
    revoked = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    objects = models.Manager()
    valid = QueryManager(revoked=False)
    invalid = QueryManager(revoked=True)

    @property
    def key_id(self):
        return self.reference.uri

    @property
    def rsa_public_key(self) -> rsa.RSAPublicKey:
        return cast(
            rsa.RSAPublicKey, serialization.load_pem_public_key(self.public_pem.encode("ascii"))
        )

    @property
    def rsa_private_key(self) -> Optional[rsa.RSAPrivateKey]:
        return self.private_pem and cast(
            rsa.RSAPrivateKey,
            serialization.load_pem_private_key(self.private_pem.encode("ascii"), password=None),
        )

    @property
    def signed_request_auth(self):
        return HTTPSignatureHeaderAuth(
            headers=["(request-target)", "user-agent", "host", "date"],
            algorithm="rsa-sha256",
            key=self.private_pem.encode("utf-8"),
            key_id=self.key_id,
        )

    def _should_be_inlined(self, reference_field, value=None) -> bool:
        return reference_field.name != "actor"

    def serialize(self, *args, **kw):
        data = super().serialize(*args, **kw)
        data["owner"] = self.actor.uri
        return data

    def verify_signature(self, signature: bytes, cleartext: str):
        try:
            assert not self.revoked, "Key is revoked"
            self.rsa_public_key.verify(
                signature, cleartext.encode("utf8"), padding.PKCS1v15(), hashes.SHA256()
            )
            return True
        except (AssertionError, InvalidSignature):
            return False

    def verify_document(self, document):
        """
        Verifies a document
        """
        try:
            assert not self.revoked, "key is revoked"
            # causing side effects to the original document is bad form
            document = document.copy()
            # Strip out the signature from the incoming document
            signature = document.pop("signature")
            assert signature["type"].lower() == "rsasignature2017", "Unknown signature type"
            # Create the options document
            options = {
                "@context": "https://w3id.org/identity/v1",
                "creator": signature["creator"],
                "created": signature["created"],
            }

        except (KeyError, AssertionError) as exc:
            logger.info(f"Document signature was invalid: {exc}")
            return False

        # Get the normalised hash of each document
        options_hash = CryptographicKeyPair.normalized_hash(options)
        document_hash = CryptographicKeyPair.normalized_hash(document)

        decoded_signature = base64.b64decode(signature["signatureValue"])
        cleartext = options_hash + document_hash
        return self.verify_signature(signature=decoded_signature, cleartext=cleartext)


# Non-ActivityPub models

# The models defined below are not specific to ActivityPub, but can
# help us in supporting business logic.


class Domain(models.Model):
    class Software(models.TextChoices):
        MASTODON = "Mastodon"
        FEDIBIRD = "Fedibird"
        HOMETOWN = "Hometown"
        BIRDSITELIVE = "BirdsiteLive"
        TAKAHE = "Takahe"
        PLEROMA = "Pleroma"
        AKKOMA = "Akkoma"
        BONFIRE = "Bonfire"
        MITRA = "Mitra"
        MISSKEY = "Misskey"
        CALCKEY = "CalcKey"
        FIREFISH = "Firefish"
        GOTOSOCIAL = "Gotosocial"
        FUNKWHALE = "Funkwhale"
        PIXELFED = "Pixelfed"
        PEERTUBE = "Peertube"
        LEMMY = "Lemmy"
        KBIN = "Kbin"
        WRITE_FREELY = "Write Freely"
        PLUME = "Plume"
        BOOKWYRM = "Bookwyrm"
        WORDPRESS = "Wordpress"
        MICRODOTBLOG = "Microdotblog"
        MOBILIZON = "Mobilizon"
        GANCIO = "Gancio"
        SOCIALHOME = "Socialhome"
        DIASPORA = "Diaspora"
        HUBZILLA = "Hubzilla"
        FRIENDICA = "Friendica"
        GNU_SOCIAL = "GNU Social"
        FORGEJO = "Forgejo"
        ACTIVITY_RELAY = "Activity Relay"
        OTHER = "Other"

        @classmethod
        def get_family(cls, software_name):
            return {
                "mastodon": cls.MASTODON,
                "hometown": cls.MASTODON,
                "fedibird": cls.MASTODON,
                "birdsitelive": cls.BIRDSITELIVE,
                "pleroma": cls.PLEROMA,
                "akkoma": cls.PLEROMA,
                "bonfire": cls.BONFIRE,
                "takahe": cls.TAKAHE,
                "firefish": cls.FIREFISH,
                "calckey": cls.FIREFISH,
                "misskey": cls.MISSKEY,
                "mitra": cls.MITRA,
                "gotosocial": cls.GOTOSOCIAL,
                "lemmy": cls.LEMMY,
                "kbin": cls.KBIN,
                "writefreely": cls.WRITE_FREELY,
                "plume": cls.PLUME,
                "microdotblog": cls.MICRODOTBLOG,
                "wordpress": cls.WORDPRESS,
                "bookwyrm": cls.BOOKWYRM,
                "funkwhale": cls.FUNKWHALE,
                "peertube": cls.PEERTUBE,
                "pixelfed": cls.PIXELFED,
                "mobilizon": cls.MOBILIZON,
                "gancio": cls.GANCIO,
                "hubzilla": cls.HUBZILLA,
                "socialhome": cls.SOCIALHOME,
                "diaspora": cls.DIASPORA,
                "friendica": cls.FRIENDICA,
                "gnu social": cls.GNU_SOCIAL,
                "forgejo": cls.FORGEJO,
                "activity-relay": cls.ACTIVITY_RELAY,
            }.get(software_name.lower(), cls.OTHER)

    name = models.CharField(max_length=250, primary_key=True, validators=[_domain_validator])
    nodeinfo = models.JSONField(null=True, blank=True)
    software_family = models.CharField(
        max_length=50, choices=Software.choices, default=Software.OTHER
    )
    software = models.CharField(max_length=60, null=True, db_index=True)
    version = models.CharField(max_length=60, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    local = models.BooleanField()
    blocked = models.BooleanField(default=False)
    actor = models.OneToOneField(Actor, null=True, blank=True, on_delete=models.SET_NULL)

    @property
    def is_mastodon_compatible(self):
        return self.software_family in [
            self.Software.MASTODON,
            self.Software.HOMETOWN,
            self.Software.PLEROMA,
            self.Software.AKKOMA,
            self.Software.TAKAHE,
            self.Software.MITRA,
            self.Software.GOTOSOCIAL,
            self.Software.PIXELFED,
        ]

    @property
    def scheme(self):
        return "http://" if app_settings.Instance.force_http else "https://"

    @property
    def fqdn(self):
        return f"{self.scheme}{self.name}"

    def get_nodeinfo(self):
        try:
            NODEINFO_URLS = [
                "http://nodeinfo.diaspora.software/ns/schema/2.0",
                "http://nodeinfo.diaspora.software/ns/schema/2.1",
            ]

            metadata_response = requests.get(f"https://{self.name}/.well-known/nodeinfo")
            metadata_response.raise_for_status()
            metadata = metadata_response.json()

            for link in metadata.get("links", []):
                if link.get("rel") in NODEINFO_URLS:
                    nodeinfo20_url = link.get("href")
                    node_response = requests.get(nodeinfo20_url)
                    node_response.raise_for_status()
                    node_data = node_response.json()
                    serializer = NodeInfoSerializer(data=node_data)
                    assert serializer.is_valid(), "Could not parse node info data"
                    software = serializer.data["software"]
                    self.nodeinfo = node_data
                    self.software_family = self.Software.get_family(software["name"])
                    self.software = software["name"]
                    self.version = software["version"]
                    self.save()
                    break
        except (
            requests.HTTPError,
            ssl.SSLCertVerificationError,
            ssl.SSLError,
            json.JSONDecodeError,
        ):
            logger.warning(f"Failed to get nodeinfo from {self.name}")

    def reverse_view(self, view_name, *args, **kwargs):
        url = reverse(view_name, args=args, kwargs=kwargs)
        return f"{self.scheme}{self.name}{url}"

    def build_collection(self, **kw):
        ulid = str(generate_ulid())
        if app_settings.Instance.collection_view_name:
            uri = self.reverse_view(app_settings.Instance.collection_view_name, pk=ulid)
        else:
            uri = f"{self.scheme}{self.name}/collections/{ulid}"
        reference = Reference.make(uri)
        return Collection.objects.create(reference=reference, id=ulid, **kw)

    def build_activity(self, **kw):
        ulid = str(generate_ulid())
        if app_settings.Instance.activity_view_name:
            uri = self.reverse_view(app_settings.Instance.activity_view_name, pk=ulid)
        else:
            uri = f"{self.scheme}{self.name}/activities/{ulid}"
        reference = Reference.make(uri)
        return Activity.objects.create(reference=reference, id=ulid, **kw)

    def build_object(self, **kw):
        ulid = str(generate_ulid())
        if app_settings.Instance.object_view_name:
            uri = self.reverse_view(app_settings.Instance.object_view_name, pk=ulid)
        else:
            uri = f"{self.scheme}{self.name}/objects/{ulid}"
        reference = Reference.make(uri)
        return Object.objects.create(reference=reference, id=ulid, **kw)

    def __str__(self):
        return self.name

    @classmethod
    def get_requested_domain(cls, request):
        host = request.META.get("HOST", "").strip()

        if bool(host):
            is_local = host == app_settings.Instance.default_domain
            domain, _ = cls.objects.get_or_create(name=host, defaults={"local": is_local})
            return domain

        return cls.get_default()

    @classmethod
    def get_default(cls):
        domain, _ = cls.objects.get_or_create(
            name=app_settings.Instance.default_domain, defaults={"local": True}
        )
        return domain

    @classmethod
    def make(cls, uri):
        parsed = urlparse(uri)

        if not parsed.hostname:
            raise ValueError(f"{uri} does not have a FQDN")

        is_local = parsed.hostname == app_settings.Instance.default_domain

        domain, _ = cls.objects.get_or_create(name=parsed.hostname, defaults={"local": is_local})
        return domain


class LinkedFile(models.Model):
    link = models.OneToOneField(Link, on_delete=models.CASCADE)
    file = models.FileField(upload_to=_file_location)


class Account(models.Model):
    actor = models.OneToOneField(Actor, related_name="account", on_delete=models.CASCADE)
    domain = models.ForeignKey(Domain, related_name="accounts", on_delete=models.CASCADE)
    username = models.CharField(max_length=200, db_index=True)

    objects = AccountManager()
    local = QueryManager(domain__local=True)

    @property
    def subject_name(self):
        return getattr(self, "_subject_name", f"@{self.username}@{self.domain_id}")

    @property
    def manually_approves_followers(self):
        return True

    def __str__(self):
        return self.subject_name

    class Meta:
        unique_together = ("domain", "username")


class HttpMessageSignature(models.Model):
    class SignatureAlgorithms(models.TextChoices):
        RSA_SHA56 = "rsa-sha256"
        HIDDEN = "hs2019"

    id = ULIDField(default=generate_ulid, primary_key=True)
    algorithm = models.CharField(max_length=20, choices=SignatureAlgorithms.choices)
    signature = models.BinaryField()
    message = models.TextField()
    key_id = models.CharField(max_length=500)

    @classmethod
    def build_message(cls, request, signed_headers):
        message_parts = {}
        for header_name in signed_headers:
            if header_name == "(request-target)":
                value = f"{request.method.lower()} {request.path}"
            elif header_name == "content-type":
                value = request.headers["content-type"]
            elif header_name == "content-length":
                value = request.headers["content-length"]
            else:
                value = request.META["HTTP_%s" % header_name.upper().replace("-", "_")]
            message_parts[header_name] = value
        return "\n".join(f"{name.lower()}: {value}" for name, value in message_parts.items())

    @classmethod
    def extract(cls, request):
        try:
            header_data = request.headers["signature"]
            bits = {}
            for item in header_data.split(","):
                name, value = item.split("=", 1)
                value = value.strip('"')
                bits[name.lower()] = value

            algorithm = cls.SignatureAlgorithms(bits["algorithm"])
            return cls.objects.create(
                algorithm=algorithm,
                signature=base64.b64decode(bits["signature"]),
                key_id=bits["keyid"],
                message=cls.build_message(request, bits["headers"].split()),
            )

        except ValueError:
            logger.warning(f"algorithm provided is not supported: {algorithm}")
            return None
        except KeyError as exc:
            logger.warning(f"Missing information to build http request: {exc}")
            return None

    def __str__(self):
        return f"{self.algorithm} message {self.key_id}"


class Message(models.Model):
    id = ULIDField(default=generate_ulid, primary_key=True)
    sender = models.ForeignKey(Reference, related_name="messages_sent", on_delete=models.CASCADE)
    recipient = models.ForeignKey(
        Reference, related_name="messages_targeted", on_delete=models.CASCADE
    )
    document = models.JSONField()
    activity = models.ForeignKey(Reference, related_name="messages", on_delete=models.CASCADE)
    objects = MessageManager()

    @property
    def is_outgoing(self):
        return self.sender.is_local and not self.recipient.is_local

    @property
    def is_incoming(self):
        return self.recipient.is_local and not self.sender.is_local

    @property
    def is_verified(self):
        return MessageIntegrityVerification.objects.filter(proof__message=self).exists()

    @property
    def is_processed(self):
        return self.results.filter(
            result__in=[MessageProcessResult.Types.OK, MessageProcessResult.Types.DROPPED]
        ).exists()

    @property
    def is_authorized(self):
        # This function should be the place for all the authorization
        # logic. Eventually we can have more sophisticated mechamisms
        # to authorize/reject a message, but at the moment let's keep
        # it simple.

        return self.is_verified or self.sender.is_local

    @property
    def document_signature(self):
        try:
            document = self.document.copy()
            signature = document.pop("signature")
            options = {
                "@context": "https://w3id.org/identity/v1",
                "creator": signature["creator"],
                "created": signature["created"],
            }
            return _get_normalized_hash(options) + _get_normalized_hash(document)
        except KeyError as exc:
            logger.info(f"Document has no valid signature: {exc}")
            return None

    def authenticate(self, fetch_missing_keys=False):
        self.sender.resolve(force=fetch_missing_keys)
        for proof in self.proofs.select_subclasses():
            proof.verify(fetch_missing_keys=fetch_missing_keys)

    @transaction.atomic()
    def _process_receive(self):
        try:
            activity = self.activity.load(self.document)
            signals.activity_received.send_robust(activity=activity, sender=Activity)
            box = self.recipient.referenced_item
            box.append(activity)
            return self.results.create(result=MessageProcessResult.Types.OK)
        except UnprocessableJsonLd:
            return self.results.create(result=MessageProcessResult.Types.BAD_REQUEST)

    @transaction.atomic()
    def _process_send(self):
        logger.info(f"Sending message to {self.recipient.uri}")
        try:
            signing_key = self.sender.keypairs.exclude(revoked=True, private_pem=None).first()
            headers = {"Content-Type": "application/activity+json"}
            response = requests.post(
                self.recipient.uri,
                json=self.document,
                headers=headers,
                auth=signing_key.signed_request_auth,
            )
            response.raise_for_status()
            return self.results.create(result=MessageProcessResult.Types.OK)
        except requests.HTTPError:
            return self.results.create(result=MessageProcessResult.Types.BAD_REQUEST)

    def process(self, force=False):
        try:
            if self.is_incoming:
                for adapter in app_settings.MESSAGE_ADAPTERS:
                    adapter.process_incoming(self)
            if self.is_outgoing:
                for adapter in app_settings.MESSAGE_ADAPTERS:
                    adapter.process_outgoing(self)
        except DropMessage:
            return self.results.create(result=MessageProcessResult.Types.DROPPED)

        if not (self.is_authorized or force):
            return self.results.create(result=MessageProcessResult.Types.UNAUTHORIZED)

        if not self.recipient.is_a_box:
            return self.results.create(result=MessageProcessResult.Types.BAD_TARGET)

        if self.is_incoming:
            return self._process_receive()

        if self.is_outgoing:
            return self._process_send()


class MessageProcessResult(models.Model):
    class Types(models.IntegerChoices):
        OK = (1, "Ok")
        UNAUTHORIZED = (2, "Unauthorized")
        BAD_TARGET = (3, "Target is not a valid box")
        BAD_REQUEST = (4, "Error when posting message to inbox")
        DROPPED = (5, "Message dropped")

    message = models.ForeignKey(Message, related_name="results", on_delete=models.CASCADE)
    result = models.PositiveSmallIntegerField(db_index=True, choices=Types.choices)
    created = models.DateTimeField(auto_now_add=True)


class MessageIntegrityProof(models.Model):
    message = models.ForeignKey(Message, related_name="proofs", on_delete=models.CASCADE)
    objects = InheritanceManager()

    @property
    def valid_signing_keys(self):
        return CryptographicKeyPair.objects.exclude(revoked=True).filter(
            actor__messages_sent__proofs=self
        )

    def passes_verification(self, signing_key):
        raise NotImplementedError("This needs to be implemented by the subclass")

    def _get_signing_keys(self, fetch_if_missing=False):
        if not self.valid_signing_keys.exists() and fetch_if_missing:
            self.message.sender.resolve(force=True)
        return self.valid_signing_keys

    def verify(self, fetch_missing_keys=False):
        for signing_key in self._get_signing_keys(fetch_if_missing=fetch_missing_keys):
            if self.passes_verification(signing_key):
                return self.verifications.create(signing_key=signing_key)


class HttpSignatureProof(MessageIntegrityProof):
    http_message_signature = models.ForeignKey(
        HttpMessageSignature, related_name="proofs", on_delete=models.CASCADE
    )

    def _get_signing_keys(self, fetch_if_missing=False):
        keys = super()._get_signing_keys(fetch_if_missing=fetch_if_missing)
        return keys.filter(reference__uri=self.http_message_signature.key_id)

    def passes_verification(self, signing_key):
        return signing_key.verify_signature(
            signature=self.http_message_signature.signature,
            cleartext=self.http_message_signature.message,
        )


class DocumentSignatureProof(MessageIntegrityProof):
    def passes_verification(self, signing_key):
        try:
            signature = base64.b64decode(self.message.document["signature"]["signatureValue"])
            cleartext = signature and self.message.document_signature
            if cleartext is None:
                return False
            return signing_key.verify_signature(signature=signature, cleartext=cleartext)
        except KeyError:
            return False


class MessageIntegrityVerification(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    proof = models.ForeignKey(
        MessageIntegrityProof, related_name="verifications", on_delete=models.CASCADE
    )
    signing_key = models.ForeignKey(
        CryptographicKeyPair, related_name="signed_integrity_proofs", on_delete=models.CASCADE
    )
