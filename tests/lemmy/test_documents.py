import os

import httpretty

from activitypub.adapters.lemmy.models import LemmyContextModel
from tests.core.base import BaseTestCase, use_nodeinfo, with_document_file

TEST_DOCUMENTS_FOLDER = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "fixtures/documents")
)


class CoreTestCase(BaseTestCase):
    @httpretty.activate
    @use_nodeinfo("https://lemmy.example.com", "nodeinfo/lemmy.json")
    @use_nodeinfo("https://www.w3.org", "nodeinfo/lemmy.json")
    @with_document_file("lemmy/post.json", base_folder=TEST_DOCUMENTS_FOLDER)
    def test_can_load_lemmy_post(self, document):
        context = document.reference.get_by_context(LemmyContextModel)
        self.assertEqual(context.uri, "https://lemmy.example.com/post/123456")

    @httpretty.activate
    @use_nodeinfo("https://lemmy.example.com", "nodeinfo/lemmy.json")
    @use_nodeinfo("https://www.w3.org", "nodeinfo/lemmy.json")
    @with_document_file("lemmy/comment.json", base_folder=TEST_DOCUMENTS_FOLDER)
    def test_can_load_lemmy_comment(self, document):
        context = document.reference.get_by_context(LemmyContextModel)
        self.assertEqual(context.uri, "https://lemmy.example.com/comment/1")
