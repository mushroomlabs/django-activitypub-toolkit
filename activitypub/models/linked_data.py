import base64
import logging
import uuid
from urllib.parse import urlparse

import rdflib
from cryptography.hazmat.primitives import hashes
from django.core.exceptions import FieldDoesNotExist
from django.db import models, transaction
from django.db.models import Exists, OuterRef
from django.urls import reverse
from model_utils.choices import Choices
from model_utils.fields import MonitorField
from model_utils.managers import InheritanceManager
from model_utils.models import StatusModel, TimeStampedModel
from pyld import jsonld

from ..exceptions import DocumentResolutionError, InvalidDomainError
from ..settings import app_settings
from .base import generate_ulid

logger = logging.getLogger(__name__)


class NotificationManager(models.Manager):
    def get_queryset(self) -> models.QuerySet:
        qs = super().get_queryset()
        verified_sqs = NotificationProofVerification.objects.filter(notification=OuterRef("pk"))
        processed_sqs = NotificationProcessResult.objects.filter(
            notification=OuterRef("pk"),
            result__in=[
                NotificationProcessResult.Types.OK,
                NotificationProcessResult.Types.DROPPED,
            ],
        )
        return qs.annotate(verified=Exists(verified_sqs), processed=Exists(processed_sqs))


class ReferenceField(models.ManyToManyField):
    """
    Custom field for referencing Reference instances. Given
    that linked data *can* provide multiple values for the same
    attribute, we will simplify the model by always using many-to-many
    relationships.

    Potential improvements:

     - materialize whole document
     - indicate required contexts
     - validate data
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("related_name", "+")
        kwargs.setdefault("to", Reference)
        super().__init__(**kwargs)


class Domain(TimeStampedModel):
    class SchemeTypes(models.TextChoices):
        HTTP = "http"
        HTTPS = "https"

    scheme = models.CharField(
        max_length=10, choices=SchemeTypes.choices, default=SchemeTypes.HTTPS
    )
    name = models.CharField(max_length=250, db_index=True)
    port = models.PositiveIntegerField(null=True)
    is_active = models.BooleanField(default=True)
    local = models.BooleanField(default=False)
    blocked = models.BooleanField(default=False)

    @property
    def url(self):
        return f"{self.scheme}://{self.netloc}"

    @property
    def netloc(self):
        default_http = self.port == 80 and self.scheme.self.SchemeTypes.HTTP
        default_https = self.port == 443 and self.scheme.self.SchemeTypes.HTTPS

        if self.port is None or default_http or default_https:
            return self.name
        return f"{self.name}:{self.port}"

    def reverse_view(self, view_name, *args, **kwargs):
        path = reverse(view_name, args=args, kwargs=kwargs)
        return f"{self.url}{path}"

    @classmethod
    def get_default(cls):
        return cls.make(app_settings.Instance.default_url, local=True)

    @classmethod
    def make(cls, uri, **kw):
        parsed = urlparse(uri)

        if not parsed.hostname:
            raise InvalidDomainError(f"{uri} does not have a FQDN")

        domain, _ = cls.objects.get_or_create(
            scheme=parsed.scheme, name=parsed.hostname, port=parsed.port, defaults=kw
        )
        return domain

    def __str__(self):
        return self.url

    class Meta:
        unique_together = ("scheme", "name", "port")


class Reference(StatusModel):
    """
    The Reference is the base class for any JSON-LD context.
    """

    SKOLEM_BASE_URI = "urn:ulid:"

    STATUS = Choices("unknown", "resolved", "failed")

    uri = models.CharField(max_length=2083, unique=True)
    domain = models.ForeignKey(
        Domain, related_name="references", null=True, blank=True, on_delete=models.SET_NULL
    )
    resolved_at = MonitorField(monitor="status", when=["resolved"])
    failed_at = MonitorField(monitor="status", when=["failed"])

    @property
    def is_local(self):
        return self.domain and self.domain.local

    @property
    def is_remote(self):
        return not self.is_local

    @property
    def is_resolved(self):
        return self.status == self.STATUS.resolved

    @property
    def is_named_node(self):
        return not self.uri.startswith(self.SKOLEM_BASE_URI)

    def get_by_context(self, context_model: type["AbstractContextModel"]):
        return context_model.objects.filter(reference=self).first()

    def get_value(self, g: rdflib, predicate):
        return g.value(rdflib.URIRef(self.uri), predicate)

    @transaction.atomic()
    def resolve(self, force=False):
        if self.is_local:
            self.status = self.STATUS.resolved
            self.save()
            return

        if self.status in (self.STATUS.resolved, self.STATUS.failed) and not force:
            return

        has_resolved = LinkedDataDocument.objects.filter(reference=self).exists()

        if has_resolved and not force:
            self.status = self.STATUS.resolved
            self.save()
            return

        resolvers = [resolver_class() for resolver_class in app_settings.DOCUMENT_RESOLVERS]
        candidates = [r for r in resolvers if r.can_resolve(self.uri)]

        for resolver in candidates:
            try:
                document_data = resolver.resolve(self.uri)
                self.status = self.STATUS.resolved
                if document_data is not None:
                    self.document, _ = LinkedDataDocument.objects.update_or_create(
                        reference=self, defaults={"data": document_data}
                    )
                    self.document.load()
            except DocumentResolutionError:
                logger.exception(f"failed to resolve {self.uri}")
                self.status = self.STATUS.failed
            else:
                return
            finally:
                self.save()

    def __str__(self):
        return self.uri

    @staticmethod
    def generate_skolem():
        return rdflib.URIRef(f"{Reference.SKOLEM_BASE_URI}{generate_ulid()}")

    @classmethod
    def make(cls, uri: str):
        ref = cls.objects.filter(uri=uri).first()
        if not ref:
            domain = Domain.make(uri)
            ref = cls.objects.create(uri=uri, domain=domain)
        return ref


class LinkedDataDocument(models.Model):
    """
    A linked data document contains *only* the source JSON-LD documents
    """

    reference = models.OneToOneField(Reference, related_name="document", on_delete=models.CASCADE)
    data = models.JSONField()

    def load(self):
        # Generates a RDF graph out of the JSON-LD document,
        # skolemizes it (generates stable names for unnamed nodes),
        # creates Reference entries for every subject in the graph and
        # then calls ContextModelClass.process(self.reference, graph)
        # for every subclass of AbstractContextModel that passes the
        # `can_process(self.reference, graph)` check.

        try:
            assert self.data is not None
            g = LinkedDataDocument.get_graph(self.data)
            blank_node_map = {}
            new_triples = []

            for s, p, o in list(g):
                if isinstance(s, rdflib.BNode):
                    if s not in blank_node_map:
                        blank_node_map[s] = Reference.generate_skolem()
                    s = blank_node_map[s]
                if isinstance(o, rdflib.BNode):
                    if o not in blank_node_map:
                        blank_node_map[o] = Reference.generate_skolem()

                    o = blank_node_map[o]
                new_triples.append((s, p, o))

            g.remove((None, None, None))
            for triple in new_triples:
                g.add(triple)

            references = [
                r
                for r, _ in (
                    Reference.objects.get_or_create(uri=str(uri)) for uri in set(g.subjects())
                )
            ]

            for reference in references:
                for context_model in app_settings.AUTOLOADED_CONTEXT_MODELS:
                    context_model.load_from_graph(g=g, reference=reference)

        except (KeyError, AssertionError):
            raise ValueError("Failed to load document")

    @staticmethod
    def get_graph(data):
        try:
            doc_id = data["id"]
            parsed_data = rdflib.parser.PythonInputSource(data, doc_id)
            return rdflib.Graph().parse(parsed_data, format="json-ld")
        except KeyError:
            raise ValueError("Failed to get graph identifier")

    @staticmethod
    def get_normalized_hash(data):
        norm_form = jsonld.normalize(
            data,
            {"algorithm": "URDNA2015", "format": "application/n-quads"},
        )
        digest = hashes.Hash(hashes.SHA256())
        digest.update(norm_form.encode("utf8"))
        return digest.finalize().hex().encode("ascii")

    @classmethod
    def make(cls, document):
        try:
            document_id = document["id"]
            reference = Reference.make(document_id)
            doc, _ = cls.objects.update_or_create(reference=reference, defaults={"data": document})
            return doc
        except KeyError:
            raise ValueError("Document has no id")


class AbstractContextModel(models.Model):
    """

    Abstract base class for vocabulary-specific context models.
    Each subclass represents a specific RDF namespace (AS2, SECv1,
    etc.) and links to a Reference instance via OneToOneField.
    """

    NAMESPACE = None
    CONTEXT = None
    CONTEXT_URL = None
    LINKED_DATA_FIELDS = {}

    reference = models.OneToOneField(
        Reference, on_delete=models.CASCADE, related_name="%(app_label)s_%(class)s_context"
    )

    @property
    def uri(self) -> str:
        return self.reference.uri

    @classmethod
    def generate_reference(cls, domain):
        raise NotImplementedError("Subclasses need to implement this method")

    @classmethod
    def should_handle_reference(cls, g: rdflib.Graph, reference: Reference):
        return True

    @classmethod
    def load_from_graph(cls, g: rdflib.Graph, reference: Reference):
        """
        Given a parsed RDF graph and a Reference (subject),
        extract all matching triples and populate this context model.
        """
        if not cls.should_handle_reference(g=g, reference=reference):
            return

        subject_uri = rdflib.URIRef(reference.uri)
        attrs = {}
        pointers = {}

        for field_name, predicate in cls.LINKED_DATA_FIELDS.items():
            try:
                field = cls._meta.get_field(field_name)
            except FieldDoesNotExist:
                field = None

            if field is None:
                continue

            # Handle scalar types
            if isinstance(field, (models.CharField, models.TextField, models.DateTimeField)):
                value = g.value(subject_uri, predicate)
                if value is not None:
                    attrs[field_name] = value.toPython()

            # Handle relations (URIs → Reference)
            elif isinstance(field, models.ForeignKey):
                value = g.value(subject_uri, predicate)
                if value is None or isinstance(value, rdflib.Literal):
                    continue
                target_ref, _ = Reference.objects.get_or_create(uri=str(value))
                attrs[field_name] = target_ref

            # Handle reference fields
            elif isinstance(field, ReferenceField):
                refs = []
                values = list(g.objects(subject_uri, predicate))
                for v in values:
                    if not isinstance(v, rdflib.Literal):
                        ref, _ = Reference.objects.get_or_create(uri=str(v))
                        refs.append(ref)
                pointers[field_name] = refs

        if not attrs and not pointers:
            return None

        obj, _ = cls.objects.update_or_create(reference=reference, defaults=attrs)

        # Handle reference fields after save
        for field_name, refs in pointers.items():
            field = cls._meta.get_field(field_name)
            getattr(obj, field_name).set(refs)

        return obj

    @classmethod
    def get_context(cls):
        if cls.CONTEXT_URL is not None:
            return cls.CONTEXT_URL
        if cls.NAMESPACE is not None:
            return str(cls.NAMESPACE).removesuffix("#")
        if cls.CONTEXT is not None:
            return cls.CONTEXT
        return None

    @classmethod
    def make(cls, reference: Reference, **defaults):
        obj, _ = cls.objects.get_or_create(reference=reference, defaults=defaults)
        return obj

    class Meta:
        abstract = True


class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    sender = models.ForeignKey(
        Reference, related_name="notifications_sent", on_delete=models.CASCADE
    )
    target = models.ForeignKey(
        Reference, related_name="notifications_targeted", on_delete=models.CASCADE
    )
    resource = models.ForeignKey(Reference, related_name="notifications", on_delete=models.CASCADE)
    objects = NotificationManager()

    @property
    def is_outgoing(self):
        return self.sender.is_local and not self.recipient.is_local

    @property
    def is_incoming(self):
        return self.recipient.is_local and not self.sender.is_local

    @property
    def is_verified(self):
        return self.verifications.exists()

    @property
    def is_processed(self):
        return self.results.filter(
            result__in=[
                NotificationProcessResult.Types.OK,
                NotificationProcessResult.Types.DROPPED,
            ]
        ).exists()

    @property
    def is_authorized(self):
        # This function should be the place for all the authorization
        # logic. Eventually we can have more sophisticated mechamisms
        # to authorize/reject a message, but at the moment let's keep
        # it simple.

        return self.is_verified or self.sender.is_local

    @property
    def document(self):
        return LinkedDataDocument.objects.filter(reference=self.reference).first()

    @property
    def data(self):
        return self.document and self.document.data

    @property
    def base64_signature(self):
        try:
            return base64.b64decode(self.data["signature"]["signatureValue"])
        except (AttributeError, KeyError):
            return None

    @property
    def document_signature(self):
        try:
            document = self.data.copy()
            signature = document.pop("signature")
            options = {
                "@context": "https://w3id.org/identity/v1",
                "creator": signature["creator"],
                "created": signature["created"],
            }

            get_hash = LinkedDataDocument.get_normalized_hash
            return get_hash(options) + get_hash(document)

        except KeyError as exc:
            logger.info(f"Document has no valid signature: {exc}")
            return None

    def authenticate(self, fetch_missing_keys=False):
        is_remote = not self.sender.is_local
        if is_remote:
            self.sender.resolve(force=fetch_missing_keys)
        for proof in self.proofs.select_subclasses():
            proof.verify(fetch_missing_keys=fetch_missing_keys and is_remote)


class NotificationProcessResult(models.Model):
    class Types(models.IntegerChoices):
        UNAUTHENTICATED = (0, "Unauthenticated")
        OK = (1, "Ok")
        UNAUTHORIZED = (2, "Unauthorized")
        BAD_TARGET = (3, "Target is not a valid box")
        BAD_REQUEST = (4, "Error when posting message to inbox")
        DROPPED = (5, "Message dropped")

    notification = models.ForeignKey(
        Notification, related_name="results", on_delete=models.CASCADE
    )
    result = models.PositiveSmallIntegerField(db_index=True, choices=Types.choices)
    created = models.DateTimeField(auto_now_add=True)


class NotificationIntegrityProof(models.Model):
    notification = models.ForeignKey(Notification, related_name="proofs", on_delete=models.CASCADE)
    objects = InheritanceManager()


class NotificationProofVerification(TimeStampedModel):
    notification = models.ForeignKey(
        Notification, related_name="verifications", on_delete=models.CASCADE
    )
    proof = models.OneToOneField(
        NotificationIntegrityProof, related_name="verification", on_delete=models.CASCADE
    )


__all__ = (
    "AbstractContextModel",
    "Domain",
    "LinkedDataDocument",
    "Notification",
    "NotificationProcessResult",
    "NotificationIntegrityProof",
    "NotificationProofVerification",
    "Reference",
    "ReferenceField",
)
