import json
import os
from functools import wraps
from unittest import SkipTest


import pytest
import httpretty
from django.test import TestCase, override_settings

from activitypub.models import BaseActivityStreamsObject


TEST_DOCUMENTS_FOLDER = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "./fixtures/documents")
)


def with_document_file(path):
    def decorator(function_at_test):
        @wraps(function_at_test)
        def inner(*args, **kw):
            full_path = os.path.join(TEST_DOCUMENTS_FOLDER, path)
            if not os.path.exists(full_path):
                raise SkipTest("Document {full_path} not found")
            with open(full_path) as f:
                document = json.load(f)
                as_object = BaseActivityStreamsObject.load(document)
                new_args = args + (as_object,)
                return function_at_test(*new_args, **kw)

        return inner

    return decorator


def use_nodeinfo(domain_name, path):
    def decorator(function_at_test):
        @wraps(function_at_test)
        def inner(*args, **kw):
            full_path = os.path.join(TEST_DOCUMENTS_FOLDER, path)
            if not os.path.exists(full_path):
                raise SkipTest("Document {full_path} not found")

            metadata = {
                "links": [
                    {
                        "rel": "http://nodeinfo.diaspora.software/ns/schema/2.0",
                        "href": f"https://{domain_name}/nodeinfo/2.0",
                    }
                ]
            }

            with open(full_path) as doc:
                httpretty.register_uri(
                    httpretty.GET,
                    f"https://{domain_name}/.well-known/nodeinfo",
                    body=json.dumps(metadata),
                )
                httpretty.register_uri(
                    httpretty.GET, f"https://{domain_name}/nodeinfo/2.0", body=doc.read()
                )

                return function_at_test(*args, **kw)

        return inner

    return decorator


@pytest.mark.django_db(transaction=True)
@override_settings(
    FEDERATION={"DEFAULT_DOMAIN": "testserver", "FORCE_INSECURE_HTTP": True},
    ALLOWED_HOSTS=["testserver"],
)
class BaseTestCase(TestCase):
    pass
