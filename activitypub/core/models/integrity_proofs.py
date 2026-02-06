import base64
import logging
import uuid

from django.db import models

from .linked_data import NotificationIntegrityProof, NotificationProofVerification
from .sec import Reference, SecV1Context

logger = logging.getLogger(__name__)


class HttpMessageSignature(models.Model):
    class SignatureAlgorithms(models.TextChoices):
        RSA_SHA56 = "rsa-sha256"
        HIDDEN = "hs2019"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    algorithm = models.CharField(max_length=20, choices=SignatureAlgorithms.choices)
    signature = models.BinaryField()
    message = models.TextField()
    key_id = models.ForeignKey(
        Reference, related_name="http_message_signatures", on_delete=models.CASCADE
    )

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
            key = Reference.make(bits["keyid"])
            return cls.objects.create(
                algorithm=algorithm,
                signature=base64.b64decode(bits["signature"]),
                key_id=key,
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


class KeySignatureBasedProofMixin:
    @property
    def key_id(self) -> Reference | None:
        refs = Reference.objects.filter(
            activitypub__secv1context_context__owner=self.notification.sender
        )

        return refs.exclude(revoked=True).first()

    def passes_verification(self, signing_key: Reference) -> bool:
        return False

    def verify(self, fetch_missing_keys=False):
        if self.key_id is None:
            return

        if not self.key_id.is_resolved and fetch_missing_keys:
            self.notification.sender.resolve(force=True)
            self.key_id.resolve()

        signing_key = self.key_id.get_by_context(SecV1Context)
        if signing_key is not None and not signing_key.revoked:
            if self.passes_verification(signing_key):
                return NotificationProofVerification.objects.create(
                    notification=self.notification, proof=self
                )


class HttpSignatureProof(NotificationIntegrityProof, KeySignatureBasedProofMixin):
    http_message_signature = models.ForeignKey(
        HttpMessageSignature, related_name="proofs", on_delete=models.CASCADE
    )

    @property
    def key_id(self) -> Reference | None:
        return self.http_message_signature.key_id

    def passes_verification(self, signing_key):
        return signing_key.verify_signature(
            signature=self.http_message_signature.signature,
            cleartext=self.http_message_signature.message,
        )


class DocumentSignatureProof(NotificationIntegrityProof, KeySignatureBasedProofMixin):
    @classmethod
    def passes_verification(cls, notification, signing_key):
        signature = notification.b64_signature
        cleartext = signature and notification.document_signature
        if cleartext is None:
            return False
        return signing_key.verify_signature(signature=signature, cleartext=cleartext)


__all__ = (
    "HttpMessageSignature",
    "HttpSignatureProof",
    "DocumentSignatureProof",
)
