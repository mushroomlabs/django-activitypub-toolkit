import logging
from typing import Optional, cast

import rdflib
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from django.db import models
from model_utils.managers import QueryManager
from requests_http_message_signatures import HTTPSignatureHeaderAuth

from ..contexts import SEC_V1_CONTEXT
from ..settings import app_settings
from .base import SignatureAlgorithms, generate_ulid
from .linked_data import AbstractContextModel, Domain, Reference, ReferenceField

logger = logging.getLogger(__name__)

SECv1 = SEC_V1_CONTEXT.namespace


class SecV1Context(AbstractContextModel):
    """
    Security vocabulary v1 context (https://w3id.org/security/v1).
    Stores security-specific fields like owner, publicKeyPem, signature, etc.
    """

    CONTEXT = SEC_V1_CONTEXT
    LINKED_DATA_FIELDS = {
        "owner": SECv1.owner,
        "public_key_pem": SECv1.publicKeyPem,
        "revoked": SECv1.revoked,
        "created": SECv1.created,
        "creator": SECv1.creator,
        "signature_value": SECv1.signatureValue,
        "signature_algorithm": SECv1.signatureAlgorithm,
    }

    owner = ReferenceField()
    public_key_pem = models.TextField(null=True, blank=True)
    private_key_pem = models.TextField(null=True, blank=True)
    revoked = models.DateTimeField(null=True, blank=True)
    signature_value = models.TextField(null=True, blank=True)
    signature_algorithm = models.TextField(
        null=True, blank=True, choices=SignatureAlgorithms.choices
    )
    creator = ReferenceField()
    created = models.DateTimeField(null=True, blank=True)

    objects = models.Manager()
    valid = QueryManager(revoked__isnull=True)
    invalid = QueryManager(revoked__isnull=False)

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
            key=self.private_key_pem.encode("utf-8"),
            key_id=self.key_id,
        )

    def verify_signature(self, signature: bytes, cleartext: str):
        try:
            assert not self.revoked, "Key is revoked"
            self.rsa_public_key.verify(
                signature, cleartext.encode("utf8"), padding.PKCS1v15(), hashes.SHA256()
            )
            return True
        except (AssertionError, InvalidSignature):
            return False

    def __str__(self):
        return self.reference.uri

    @classmethod
    def generate_reference(cls, domain: Domain):
        ulid = str(generate_ulid())
        if app_settings.Instance.keypair_view_name:
            uri = domain.reverse_view(app_settings.Instance.keypair_view_name, pk=ulid)
        else:
            uri = f"{domain.url}/keys/{ulid}"

        return Reference.make(uri)

    @classmethod
    def generate_keypair(cls, owner_reference: Reference, force=False):
        if owner_reference.is_remote:
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

        key_reference = cls.generate_reference(owner_reference.domain)

        keypair = cls.make(
            reference=key_reference,
            private_key_pem=private_pem,
            public_key_pem=public_pem,
            signature_algorithm=SignatureAlgorithms.RS256,
        )
        keypair.owner.add(owner_reference)
        return keypair

    @classmethod
    def should_handle_reference(cls, g: rdflib.Graph, reference=Reference):
        owner = reference.get_value(g, SECv1.owner)
        return owner is not None


__all__ = ("SecV1Context",)
