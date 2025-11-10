from datetime import datetime, timezone

from activitypub import models
from activitypub.factories import AccountFactory, DomainFactory
from activitypub.frames import ChoiceFrame, ObjectFrame, QuestionFrame, RepliesCollectionFrame
from activitypub.schemas import AS2
from activitypub.serializers import LinkedDataSerializer
from activitypub.tests.base import BaseTestCase


class FrameTestCase(BaseTestCase):
    """
    Test that LinkedDataFrame correctly applies framing rules to expanded JSON-LD.

    These tests verify structural transformations (omit/embed) without compaction.
    """

    def setUp(self):
        self.domain = DomainFactory(scheme="http", name="testserver", local=True)

    def test_frame_omits_predicates(self):
        """Test that frames can omit specified predicates"""
        AccountFactory(username="alice", domain=self.domain)

        # Create a collection with items
        collection_ref = models.Reference.make("http://testserver/collections/test")
        collection = models.CollectionContext.objects.create(
            reference=collection_ref,
            type=models.CollectionContext.Types.UNORDERED,
        )

        # Add some items
        for i in range(3):
            item_ref = models.Reference.make(f"http://testserver/items/{i}")
            collection.append(item=item_ref)

        # Serialize to get expanded JSON-LD
        serializer = LinkedDataSerializer(collection_ref)
        expanded_data = serializer.data

        # Verify items are in the expanded data
        self.assertIn(str(AS2.items), expanded_data)

        # Apply frame that omits items
        frame = RepliesCollectionFrame(serializer=serializer)
        framed_data = frame.to_framed_document()

        # Verify items are omitted
        self.assertNotIn(str(AS2.items), framed_data)
        # But @id should still be there
        self.assertEqual(framed_data["@id"], "http://testserver/collections/test")

    def test_frame_preserves_non_omitted_predicates(self):
        """Test that frames preserve predicates not in omitted_values"""
        account = AccountFactory(username="bob", domain=self.domain)
        actor = account.actor

        note = models.ObjectContext.objects.create(
            reference=models.Reference.make("http://testserver/notes/123"),
            type=models.ObjectContext.Types.NOTE,
            content="Hello, Fediverse!",
            name="Test Note",
            published=datetime(2024, 11, 16, 12, 0, 0, tzinfo=timezone.utc),
        )
        note.attributed_to.add(actor.reference)

        # Serialize to get expanded JSON-LD
        serializer = LinkedDataSerializer(note.reference)

        # Apply a simple frame (ObjectFrame doesn't omit name or content)
        frame = ObjectFrame(serializer=serializer)
        framed_data = frame.to_framed_document()

        # Verify all fields are preserved (still in expanded form)
        self.assertEqual(framed_data["@id"], "http://testserver/notes/123")
        self.assertIn(str(AS2.name), framed_data)
        self.assertIn(str(AS2.content), framed_data)
        self.assertIn(str(AS2.published), framed_data)
        self.assertIn(str(AS2.attributedTo), framed_data)

    def test_question_frame_identifies_embedded_predicates(self):
        """Test that QuestionFrame correctly identifies oneOf as embedded"""
        account = AccountFactory(username="alice", domain=self.domain)
        actor = account.actor

        # Create the Question object
        question = models.ObjectContext.objects.create(
            reference=models.Reference.make("http://testserver/questions/poll-123"),
            type=models.ObjectContext.Types.QUESTION,
            name="What's your favorite color?",
            content="Please choose one of the options below",
            published=datetime(2024, 11, 16, 15, 0, 0, tzinfo=timezone.utc),
        )
        question.attributed_to.add(actor.reference)

        # Create choice options as Note objects
        choice_refs = []
        for choice_name in ["Red", "Blue", "Green"]:
            choice_ref = models.Reference.make(
                f"http://testserver/questions/poll-123/choices/{choice_name.lower()}"
            )
            models.ObjectContext.objects.create(
                reference=choice_ref,
                type=models.ObjectContext.Types.NOTE,
                name=choice_name,
            )
            choice_refs.append(choice_ref)

        # Create QuestionContext to link choices
        question_context = models.QuestionContext.objects.create(reference=question.reference)
        for choice_ref in choice_refs:
            question_context.one_of.add(choice_ref)

        # Serialize to get expanded JSON-LD
        serializer = LinkedDataSerializer(question.reference)
        expanded_data = serializer.data

        # Verify oneOf is in the expanded data
        self.assertIn(str(AS2.oneOf), expanded_data)

        # Apply QuestionFrame
        frame = QuestionFrame(serializer=serializer)

        # Verify frame has the right rules
        self.assertIn(str(AS2.oneOf), frame.rules)
        self.assertIn(str(AS2.anyOf), frame.rules)

    def test_frame_output_is_still_expanded(self):
        """Test that framed output remains in expanded form (full URIs)"""
        account = AccountFactory(username="bob", domain=self.domain)
        actor = account.actor

        note = models.ObjectContext.objects.create(
            reference=models.Reference.make("http://testserver/notes/456"),
            type=models.ObjectContext.Types.NOTE,
            content="Test content",
        )
        note.attributed_to.add(actor.reference)

        # Serialize to get expanded JSON-LD
        serializer = LinkedDataSerializer(note.reference)

        # Apply frame
        frame = ObjectFrame(serializer=serializer)
        framed_data = frame.to_framed_document()

        # Verify output is still expanded (uses full URIs)
        self.assertIn(str(AS2.content), framed_data)
        self.assertIn(str(AS2.attributedTo), framed_data)

        # Should NOT have compact keys
        self.assertNotIn("content", framed_data)
        self.assertNotIn("attributedTo", framed_data)

        # Should NOT have @context
        self.assertNotIn("@context", framed_data)

    def test_frame_finds_nested_frame_by_predicate(self):
        """Test that frames have nested frames mapped to predicates"""
        # Verify QuestionFrame has nested frames defined
        self.assertIn(str(AS2.oneOf), QuestionFrame.nested_frames)
        self.assertIn(str(AS2.anyOf), QuestionFrame.nested_frames)

        # Verify the nested frames are ChoiceFrame
        self.assertEqual(QuestionFrame.nested_frames[str(AS2.oneOf)], ChoiceFrame)
        self.assertEqual(QuestionFrame.nested_frames[str(AS2.anyOf)], ChoiceFrame)
