import json
import os
import re
from functools import wraps
from unittest import SkipTest

import httpretty
from django.test import TestCase, override_settings

from activitypub.core.models import LinkedDataDocument

TEST_DOCUMENTS_FOLDER = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "./fixtures/documents")
)


def with_document_file(path, base_folder=TEST_DOCUMENTS_FOLDER):
    def decorator(function_at_test):
        @wraps(function_at_test)
        def inner(*args, **kw):
            full_path = os.path.join(base_folder, path)
            if not os.path.exists(full_path):
                raise SkipTest("Document {full_path} not found")
            with open(full_path) as f:
                document_data = json.load(f)
                document = LinkedDataDocument.make(document_data)
                document.load()
                new_args = args + (document,)
                return function_at_test(*new_args, **kw)

        return inner

    return decorator


def with_remote_reference(uri, path, base_folder=TEST_DOCUMENTS_FOLDER):
    def decorator(function_at_test):
        @wraps(function_at_test)
        def inner(*args, **kw):
            full_path = os.path.join(TEST_DOCUMENTS_FOLDER, path)
            if not os.path.exists(full_path):
                raise SkipTest("Document {full_path} not found")

            with open(full_path) as doc:
                httpretty.register_uri(httpretty.GET, uri, body=doc.read())
                return function_at_test(*args, **kw)

        return inner

    return decorator


def use_nodeinfo(domain_url, path, base_folder=TEST_DOCUMENTS_FOLDER):
    def decorator(function_at_test):
        @wraps(function_at_test)
        def inner(*args, **kw):
            full_path = os.path.join(base_folder, path)
            if not os.path.exists(full_path):
                raise SkipTest("Document {full_path} not found")

            metadata = {
                "links": [
                    {
                        "rel": "http://nodeinfo.diaspora.software/ns/schema/2.0",
                        "href": f"{domain_url}/nodeinfo/2.0",
                    }
                ]
            }

            with open(full_path) as doc:
                httpretty.register_uri(
                    httpretty.GET,
                    f"{domain_url}/.well-known/nodeinfo",
                    body=json.dumps(metadata),
                )
                httpretty.register_uri(
                    httpretty.GET, f"{domain_url}/nodeinfo/2.0", body=doc.read()
                )

                return function_at_test(*args, **kw)

        return inner

    return decorator


def silence_notifications(domain_url):
    def decorator(function_at_test):
        @wraps(function_at_test)
        def inner(*args, **kw):
            pattern = re.escape(domain_url)
            compiled = re.compile(f"{pattern}/*")
            httpretty.register_uri(httpretty.POST, compiled)
            httpretty.register_uri(httpretty.GET, compiled)

            return function_at_test(*args, **kw)

        return inner

    return decorator


@override_settings(
    FEDERATION={"DEFAULT_URL": "http://testserver", "FORCE_INSECURE_HTTP": True},
    ALLOWED_HOSTS=["testserver"],
)
class BaseTestCase(TestCase):
    pass
