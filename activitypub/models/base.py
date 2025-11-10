import os

from django.db import models
from ulid import ULID


def _is_pointer_field(model_field):
    return isinstance(
        model_field,
        (models.ForeignKey, models.OneToOneField, models.ManyToManyField),
    )


def generate_ulid():
    # If we use the callable directly, django will generate the migration
    # indefinitely. See https://code.djangoproject.com/ticket/32689
    return str(ULID())


def _file_location(_, filename):
    _, ext = os.path.splitext(filename)

    ulid = ULID()
    now = ulid.datetime
    subfolder = str(ulid.hex)[-2:]
    return f"{now.year}/{now.month:02d}/{now.day:02d}/{subfolder}/{ulid}{ext}"


class SignatureAlgorithms(models.TextChoices):
    # RSA PKCS#1 v1.5
    RS256 = ("rsa-v1_5-sha256", "RSASSA-PKCS1-v1_5 using SHA-256")
    RS384 = ("rsa-v1_5-sha384", "RSASSA-PKCS1-v1_5 using SHA-384")
    RS512 = ("rsa-v1_5-sha512", "RSASSA-PKCS1-v1_5 using SHA-512")

    # RSA-PSS
    PS256 = ("rsa-pss-sha256", "RSASSA-PSS using SHA-256")
    PS384 = ("rsa-pss-sha384", "RSASSA-PSS using SHA-384")
    PS512 = ("rsa-pss-sha512", "RSASSA-PSS using SHA-512")

    # ECDSA
    ES256 = ("ecdsa-p256-sha256", "ECDSA using P-256 and SHA-256")
    ES384 = ("ecdsa-p384-sha384", "ECDSA using P-384 and SHA-384")
    ES512 = ("ecdsa-p521-sha512", "ECDSA using P-521 and SHA-512")

    # EdDSA
    EDDSA = ("ed25519", "EdDSA using Ed25519")

    # HMAC
    HS256 = ("hmac-sha256", "HMAC using SHA-256")
