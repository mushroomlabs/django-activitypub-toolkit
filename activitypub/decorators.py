import base64
import logging
from functools import wraps

from cryptography.hazmat.primitives import hashes
from django.http import HttpResponseBadRequest

from .models import HttpMessageSignature

logger = logging.getLogger(__name__)


def calculate_digest():
    def decorator(function):
        @wraps(function)
        def inner(request, *args, **kw):
            digest = hashes.Hash(hashes.SHA256())
            digest.update(request.body)
            request.digest = "SHA-256=" + base64.b64encode(digest.finalize()).decode("ascii")

            provided_digest = request.headers.get("digest")

            if all(
                [
                    request.method.upper() == "POST",
                    provided_digest is not None,
                    provided_digest != request.digest,
                ]
            ):
                return HttpResponseBadRequest("Provided Digest is invalid")
            return function(request, *args, **kw)

        return inner

    return decorator


def collect_signature():
    def decorator(function):
        @wraps(function)
        def inner(request, *args, **kw):
            request.signature = HttpMessageSignature.extract(request)
            return function(request, *args, **kw)

        return inner

    return decorator


def log_request():
    def decorator(function):
        @wraps(function)
        def inner(request, *args, **kw):
            logger.debug(request.body)
            response = function(request, *args, **kw)
            if response.status_code >= 400:
                logger.warning(response.data)
            return response

        return inner

    return decorator
