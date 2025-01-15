import os

import pytest
from django.test import TestCase, override_settings

TEST_DOCUMENTS_FOLDER = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "./fixtures/documents")
)


@pytest.mark.django_db(transaction=True)
@override_settings(
    FEDERATION={"DEFAULT_DOMAIN": "testserver", "FORCE_INSECURE_HTTP": True},
    ALLOWED_HOSTS=["testserver"],
)
class BaseTestCase(TestCase):
    pass
