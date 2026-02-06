from datetime import datetime

from django.test import TestCase
from django.utils.timezone import make_aware

from activitypub.adapters.lemmy.factories import CommentFactory
from activitypub.adapters.lemmy.serializers import CommentSerializer
from activitypub.core.factories import DomainFactory, ObjectFactory, SourceContentContextFactory
from activitypub.core.models import ObjectContext


class CommentSerializerTestCase(TestCase):
    def setUp(self):
        local_domain = DomainFactory(scheme="https", name="local.example.com", port=443)
        note_markdown = SourceContentContextFactory(
            content="test comment", media_type="text/markdown"
        )
        as2_note = ObjectFactory(
            reference__path="/comment/123",
            reference__domain=local_domain,
            type=ObjectContext.Types.NOTE,
            published=make_aware(datetime(year=2023, month=6, day=30)),
        )
        as2_note.source.add(note_markdown.reference)

        self.comment = CommentFactory(reference=as2_note.reference)

    def test_comment_serializer_reads_context_fields(self):
        serializer = CommentSerializer(instance=self.comment)
        data = serializer.data

        self.assertEqual(data["content"], "test comment")
        self.assertEqual(data["published"], "2023-06-30T00:00:00Z")

    def test_comment_serializer_handles_missing_context_fields(self):
        empty_note = ObjectFactory(type=ObjectContext.Types.NOTE)
        comment = CommentFactory(reference=empty_note.reference)
        serializer = CommentSerializer(instance=comment)
        data = serializer.data

        self.assertIsNone(data.get("published"))
        self.assertIsNone(data.get("content"))

    def test_comment_serializer_includes_all_fields(self):
        serializer = CommentSerializer(instance=self.comment)
        data = serializer.data

        # Check that expected fields are present
        expected_fields = ["id", "ap_id", "local", "published"]
        for field in expected_fields:
            self.assertIn(field, data, f"Field '{field}' should be in serialized data")
