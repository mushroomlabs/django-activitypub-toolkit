import base64
import logging
import random
import uuid
from urllib.parse import urlparse

import mmh3
import rdflib
from cryptography.hazmat.primitives import hashes
from django.core.exceptions import FieldDoesNotExist
from django.db import models, transaction
from django.db.models import BooleanField, Case, Exists, OuterRef, Q, Value, When
from django.urls import reverse
from model_utils.choices import Choices
from model_utils.fields import MonitorField
from model_utils.managers import InheritanceManager, QueryManager
from model_utils.models import StatusModel, TimeStampedModel
from pyld import jsonld

from ..exceptions import DocumentResolutionError, InvalidDomainError, ReferenceRedirect
from ..settings import app_settings
from ..signals import document_loaded, reference_loaded
from .fields import ReferenceField

logger = logging.getLogger(__name__)


class NotificationManager(models.Manager):
    def get_queryset(self) -> models.QuerySet:
        qs = super().get_queryset()
        verified_sqs = NotificationProofVerification.objects.filter(notification=OuterRef("pk"))
        dropped_sqs = NotificationProcessResult.objects.filter(
            notification=OuterRef("pk"),
            result__in=[
                NotificationProcessResult.Types.DROPPED,
            ],
        )
        processed_sqs = NotificationProcessResult.objects.filter(
            notification=OuterRef("pk"),
            result__in=[
                NotificationProcessResult.Types.OK,
            ],
        )
        return qs.annotate(
            verified=Exists(verified_sqs),
            processed=Exists(processed_sqs),
            dropped=Exists(dropped_sqs),
        )


class ReferenceManager(models.Manager):
    def get_queryset(self):
        qs = super().get_queryset()

        has_fragment = (Q(uri__startswith="http://") | Q(uri__startswith="https://")) & Q(
            uri__contains="#"
        )
        return qs.annotate(
            dereferenceable=Case(
                # Local or skolemized references are not dereferenceable
                When(
                    Q(domain__local=True) | Q(uri__startswith=self.model.SKOLEM_BASE_URI),
                    then=Value(False),
                ),
                # HTTP(S) URIs with fragments are not dereferenceable
                When(has_fragment, then=Value(False)),
                # Document marked as non-resolvable makes reference non-dereferenceable
                When(Q(document__resolvable=False), then=Value(False)),
                default=Value(True),
                output_field=BooleanField(),
            )
        )


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
        default_http = self.port == 80 and self.scheme == self.SchemeTypes.HTTP
        default_https = self.port == 443 and self.scheme == self.SchemeTypes.HTTPS

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

        if parsed.scheme not in Domain.SchemeTypes:
            raise InvalidDomainError(f"{parsed.scheme} is not a supported scheme")

        match (parsed.scheme, parsed.port):
            case ("http", None):
                port = 80
            case ("https", None):
                port = 443
            case _:
                port = parsed.port

        domain, _ = cls.objects.get_or_create(
            scheme=parsed.scheme, name=parsed.hostname, port=port, defaults=kw
        )
        return domain

    def __str__(self):
        return self.url

    class Meta:
        unique_together = ("scheme", "name", "port")


class Reference(TimeStampedModel, StatusModel):
    """
    The Reference is the base class for any JSON-LD context.
    """

    SKOLEM_BASE_URI = "urn:uuid:"

    STATUS = Choices("unknown", "resolved", "redirected", "failed")

    uri = models.CharField(max_length=2083, unique=True)
    domain = models.ForeignKey(
        Domain, related_name="references", null=True, blank=True, on_delete=models.SET_NULL
    )
    redirects_to = models.ForeignKey(
        "Reference",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="redirects_from",
    )

    redirected_at = MonitorField(monitor="status", null=True, when=["redirected"])
    resolved_at = MonitorField(monitor="status", null=True, when=["resolved"])
    failed_at = MonitorField(monitor="status", null=True, when=["failed"])
    objects = ReferenceManager()
    remote = QueryManager(domain__local=False)
    local = QueryManager(domain__local=True)

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
    def is_dereferenceable(self):
        # check if model is coming from queryset and has annotated 'dereferenceable' field
        if not hasattr(self, "dereferenceable"):
            parsed = urlparse(self.uri)
            has_fragment = parsed.scheme in ("http", "https") and parsed.fragment

            resolvable_document = True
            if hasattr(self, "document"):
                resolvable_document = self.document.resolvable
            self.dereferenceable = not any(
                [self.is_local, self.is_blank_node, has_fragment, not resolvable_document]
            )
        return self.dereferenceable

    @property
    def is_named_node(self):
        return not self.uri.startswith(self.SKOLEM_BASE_URI)

    @property
    def is_blank_node(self):
        return self.uri.startswith(self.SKOLEM_BASE_URI)

    @property
    def as_rdf(self):
        return rdflib.URIRef(self.uri)

    def get_by_context(self, context_model: type["AbstractContextModel"]):
        return context_model.objects.filter(reference=self).first()

    def get_value(self, g: rdflib.Graph, predicate):
        return g.value(self.as_rdf, predicate)

    def load_context_models(self, g: rdflib.Graph, source: "Reference"):
        for context_model in app_settings.CONTEXT_MODELS:
            if context_model.should_handle_reference(g=g, reference=self, source=source):
                context_model.clean_graph(g=g, reference=self, source=source)
                context_model.load_from_graph(g=g, reference=self)

        reference_loaded.send_robust(reference=self, graph=g, sender=self.__class__)

    def has_authority_over(self, object: "Reference") -> bool:
        """
        Check if this reference can be trusted as authoritative over `object`
        """

        # Blank nodes do not have an owner, so anyone can control them.
        if object.is_blank_node:
            return True

        # references are authoritative over themselves
        if self == object:
            return True

        # They must have a domain, otherwise we can not establish authority
        if self.domain is None:
            return False

        # Local references are controlled by the server, so they have
        # no authority over anything (except themselves)
        if self.domain.local:
            return False

        # If the references come from the same domain, we accept that
        # any data update as authoritative
        return self.domain == object.domain

    @transaction.atomic()
    def resolve(self, force=False):
        if self.is_blank_node or self.is_local:
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
                    self.document.load(sender=self)
            except DocumentResolutionError:
                logger.exception(f"failed to resolve {self.uri}")
                self.status = self.STATUS.failed
            except ReferenceRedirect as exc:
                self.status = self.STATUS.redirected
                if exc.redirect_uri:
                    self.redirects_to = Reference.make(exc.redirect_uri)
                    self.redirects_to.resolve()
            else:
                return
            finally:
                self.save()

    def __str__(self):
        return self.uri

    @classmethod
    def make(cls, uri: str):
        ref = cls.objects.filter(uri=uri).first()
        if not ref:
            try:
                domain = Domain.make(uri)
            except InvalidDomainError:
                domain = None
            ref = cls.objects.create(uri=uri, domain=domain)
        return ref

    @classmethod
    def generate_skolem(cls, identifier=None):
        if identifier is None:
            identifier = random.getrandbits(128)

        as_bytes = identifier.to_bytes(16, byteorder="big")
        encoded = base64.b32encode(as_bytes).decode("ascii").rstrip("=").lower()

        return rdflib.URIRef(f"{Reference.SKOLEM_BASE_URI}{encoded}")


class LinkedDataDocument(models.Model):
    """
    A linked data document contains *only* the source JSON-LD documents
    """

    reference = models.OneToOneField(Reference, related_name="document", on_delete=models.CASCADE)
    resolvable = models.BooleanField(default=True)
    data = models.JSONField()

    def load(self, sender: Reference):
        # Generates a RDF graph out of the JSON-LD document,
        # creates Reference entries for every subject in the graph and
        # then calls reference.load_context_models(graph)
        # for every reference that is has a trusted domain (in relation to the document)

        try:
            assert self.data is not None
            g = LinkedDataDocument.get_graph(self.data)

            references = [Reference.make(uri=str(uri)) for uri in set(g.subjects())]

            for ref in references:
                ref.load_context_models(g=g, source=sender)

            document_loaded.send_robust(document=self, sender=self.__class__)

        except (KeyError, AssertionError):
            raise ValueError("Failed to load document")

    @staticmethod
    def get_graph(data):
        def skolemize(blank_node, identifier):
            # We would like to have a deterministic identifier for blank nodes,
            # this function calculates murmurhash3(node_id + document uri), then passes that for
            # Reference.generate_skolem

            node_uid = f"{blank_node}:{identifier}"
            hashed = mmh3.hash128(node_uid.encode())

            return Reference.generate_skolem(hashed)

        def should_skolemize(value):
            if isinstance(value, rdflib.BNode):
                return True
            if isinstance(value, rdflib.URIRef):
                uri = str(value)
                try:
                    domain = Domain.make(uri)
                    if domain.local:
                        # Local domain URI - skolemize if it doesn't exist
                        return not Reference.objects.filter(uri=uri).exists()
                except InvalidDomainError:
                    pass
            return False

        try:
            doc_id = data["id"]
            parsed_data = rdflib.parser.PythonInputSource(data, doc_id)
            g = rdflib.Graph(identifier=doc_id)
            g.parse(parsed_data, format="json-ld")
            blank_node_map = {}
            new_triples = []

            for s, p, o in list(g):
                if should_skolemize(s):
                    if s not in blank_node_map:
                        blank_node_map[s] = skolemize(s, doc_id)
                    s = blank_node_map[s]

                if should_skolemize(o):
                    if o not in blank_node_map:
                        blank_node_map[o] = skolemize(o, doc_id)
                    o = blank_node_map[o]

                new_triples.append((s, p, o))

            g.remove((None, None, None))
            for triple in new_triples:
                g.add(triple)

            return g

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

    CONTEXT = None
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
    def should_handle_reference(cls, g: rdflib.Graph, reference: Reference, source: Reference):
        return source.has_authority_over(reference)

    @classmethod
    def clean_graph(cls, g: rdflib.Graph, reference: Reference, source: Reference):
        """
        Sanitize the graph before loading - generate named references for blank nodes,
        remove or modify data that the source shouldn't control.

        Subclasses should override this to add context-specific cleaning rules.
        """
        pass

    @classmethod
    def load_from_graph(cls, g: rdflib.Graph, reference: Reference):
        """
        Given a parsed RDF graph and a Reference (subject),
        extract all matching triples and populate this context model.
        """
        subject_uri = rdflib.URIRef(reference.uri)
        attrs = {}
        reference_fields = {}

        scalar_types = (
            models.BooleanField,
            models.CharField,
            models.TextField,
            models.IntegerField,
            models.DateTimeField,
        )

        for field_name, predicate in cls.LINKED_DATA_FIELDS.items():
            try:
                field = cls._meta.get_field(field_name)
            except FieldDoesNotExist:
                field = None

            if field is None:
                continue

            # Handle reference fields
            if isinstance(field, ReferenceField):
                refs = [
                    Reference.make(uri=str(v))
                    for v in g.objects(subject_uri, predicate)
                    if not isinstance(v, rdflib.Literal)
                ]
                if refs:
                    reference_fields[field_name] = refs

            # Handle direct attributes scalar types
            elif isinstance(field, scalar_types):
                value = g.value(subject_uri, predicate)
                if value is not None:
                    attrs[field_name] = value.toPython()

            # Handle relations (URIs → Reference)
            elif isinstance(field, models.ForeignKey):
                value = g.value(subject_uri, predicate)
                if value is None or isinstance(value, rdflib.Literal):
                    continue
                attrs[field_name] = Reference.make(uri=str(value))

        if not attrs and not reference_fields:
            return None

        # FIXME: Using "update_or_create" with the attrs is
        # occasionally returning `django.db.utils.NotSupportedError`
        # "FOR UPDATE cannot be applied to the nullable side of an
        # outer join". So let's first create the object, then update the values.

        obj = cls.make(reference=reference)
        cls.objects.filter(reference=reference).update(**attrs)
        obj.refresh_from_db()

        # Handle reference FKs after save

        for field_name, refs in reference_fields.items():
            existing = getattr(obj, field_name).all()
            to_add = set(refs).difference(set(existing))
            to_remove = set(existing).difference(set(refs))

            for ref in to_remove:
                getattr(obj, field_name).remove(ref)

            for ref in to_add:
                getattr(obj, field_name).add(ref)

        return obj

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
        return self.sender.is_local and not self.target.is_local

    @property
    def is_incoming(self):
        return self.target.is_local and not self.sender.is_local

    @property
    def is_verified(self):
        return self.verifications.exists()

    @property
    def is_processed(self):
        return self.results.filter(result=NotificationProcessResult.Types.OK).exists()

    @property
    def is_dropped(self):
        return self.results.filter(result=NotificationProcessResult.Types.DROPPED).exists()

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

    def __str__(self):
        return f"Notification {self.notification_id}: {self.get_result_display()}"


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
