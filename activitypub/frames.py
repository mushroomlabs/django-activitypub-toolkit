import logging
from typing import Any, Callable, Dict, Literal, Optional, Type

from activitypub.schemas import AS2

logger = logging.getLogger(__name__)


class FramingContext:
    """
    Represents the context in which a resource is being framed.

    Controls how deeply to embed resources and what mode to use
    (main subject vs embedded vs reference-only).
    """

    MAIN_SUBJECT = "main_subject"
    EMBEDDED = "embedded"
    REFERENCE_ONLY = "reference"

    def __init__(
        self,
        mode: Literal["main_subject", "embedded", "reference"] = MAIN_SUBJECT,
        predicate: Optional[str] = None,
        depth: int = 0,
        max_depth: int = 2,
    ):
        self.mode = mode
        self.predicate = predicate
        self.depth = depth
        self.max_depth = max_depth

    def descend(self, predicate: str) -> "FramingContext":
        """Create a child context for an embedded resource"""
        return FramingContext(
            mode=FramingContext.EMBEDDED,
            predicate=predicate,
            depth=self.depth + 1,
            max_depth=self.max_depth,
        )

    @property
    def is_main_subject(self) -> bool:
        return self.mode == FramingContext.MAIN_SUBJECT

    @property
    def is_embedded(self) -> bool:
        return self.mode == FramingContext.EMBEDDED

    @property
    def is_reference_only(self) -> bool:
        return self.mode == FramingContext.REFERENCE_ONLY

    @property
    def at_max_depth(self) -> bool:
        return self.depth >= self.max_depth


class FramingRule:
    """
    Declarative rule for how to handle a predicate in different contexts.

    Each rule specifies:
    - Which predicate it applies to
    - What action to take (omit/reference/embed)
    - Optional condition for when the rule applies
    """

    OMIT = "omit"
    REFERENCE = "reference"
    EMBED = "embed"

    def __init__(
        self,
        predicate: str,
        action: Literal["omit", "reference", "embed"] = REFERENCE,
        when: Optional[Callable[[FramingContext], bool]] = None,
    ):
        self.predicate = predicate
        self.action = action
        self.when = when

    def should_apply(self, framing_context: FramingContext) -> bool:
        """Check if this rule applies in the given context"""
        if self.when is None:
            return True
        return self.when(framing_context)

    def get_action(self, framing_context: FramingContext) -> Optional[str]:
        """Get the action to take if this rule applies"""
        if not self.should_apply(framing_context):
            return None
        return self.action


class LinkedDataFrame:
    """
    Base class for declarative framing tied to context models.

    Each frame class defines:
    - Which context model it applies to
    - Rules for each predicate based on framing context
    - Nested frames for embedded resources
    """

    context_model_class: Optional[Type] = None
    priority: int = 0
    rules: Dict[str, list[FramingRule]] = {}
    nested_frames: Dict[str, Type["LinkedDataFrame"]] = {}

    def __init__(self, serializer=None):
        self.serializer = serializer

    def to_framed_document(
        self, framing_context: Optional[FramingContext] = None
    ) -> Dict[str, Any]:
        """
        Transform expanded JSON-LD data according to framing rules.

        Applies structural transformations based on context:
        - Omits predicates based on rules
        - References or embeds objects based on rules
        - Respects depth limits
        """
        if framing_context is None:
            framing_context = FramingContext(mode=FramingContext.MAIN_SUBJECT)

        if not self.serializer:
            return {}

        expanded_data = self.serializer.data
        framed = {}

        if "@id" in expanded_data:
            framed["@id"] = expanded_data["@id"]

        # If at reference-only mode, just return @id
        if framing_context.is_reference_only:
            return framed

        # At max depth, we still process fields but don't embed further references
        # This allows showing @type, totalItems, etc. without recursing deeper

        # Process each predicate
        for predicate_uri, values in expanded_data.items():
            if predicate_uri == "@id":
                continue

            # Get the framing action for this predicate
            action = self._get_action_for_predicate(predicate_uri, framing_context)

            if action == FramingRule.OMIT:
                continue
            elif action == FramingRule.REFERENCE:
                framed[predicate_uri] = values
            elif action == FramingRule.EMBED:
                framed[predicate_uri] = self._embed_values(values, predicate_uri, framing_context)
            else:
                # Default: include as reference
                framed[predicate_uri] = values

        return framed

    def _get_action_for_predicate(
        self, predicate_uri: str, framing_context: FramingContext
    ) -> Optional[str]:
        """
        Get the framing action for a predicate based on context.

        Checks all rules for this predicate and returns the action
        from the first matching rule. Returns None for default behavior.
        """
        # At max depth, never embed - only reference or omit
        if framing_context.at_max_depth:
            if predicate_uri not in self.rules:
                return FramingRule.REFERENCE
            rules = self.rules[predicate_uri]
            for rule in rules:
                action = rule.get_action(framing_context)
                if action == FramingRule.EMBED:
                    continue  # Skip embed rules at max depth
                if action is not None:
                    return action
            return FramingRule.REFERENCE

        if predicate_uri not in self.rules:
            return FramingRule.REFERENCE

        rules = self.rules[predicate_uri]
        for rule in rules:
            action = rule.get_action(framing_context)
            if action is not None:
                return action

        return FramingRule.REFERENCE

    def _embed_values(
        self, values: list, predicate_uri: str, parent_context: FramingContext
    ) -> list:
        """Embed referenced objects using nested frames"""
        embedded = []
        child_context = parent_context.descend(predicate_uri)

        for value in values:
            if not isinstance(value, dict) or "@id" not in value:
                embedded.append(value)
                continue

            # Resolve the reference
            ref_uri = value["@id"]

            try:
                from activitypub.models.linked_data import Reference

                reference = Reference.objects.filter(uri=ref_uri).first()  # type: ignore

                if not reference:
                    embedded.append(value)
                    continue

                # Get the appropriate frame for this reference
                frame_class = self._get_nested_frame_for_predicate(predicate_uri, reference)

                if frame_class is None:
                    embedded.append(value)
                    continue

                # Serialize and frame the referenced object
                from activitypub.serializers import LinkedDataSerializer

                context = getattr(self.serializer, "context", {})
                nested_serializer = LinkedDataSerializer(reference, context=context)
                frame = frame_class(serializer=nested_serializer)
                embedded.append(frame.to_framed_document(child_context))

            except Exception as e:
                logger.warning(f"Failed to embed {ref_uri}: {e}")
                embedded.append(value)

        return embedded

    def _get_nested_frame_for_predicate(
        self, predicate_uri: str, reference
    ) -> Optional[Type["LinkedDataFrame"]]:
        """
        Get the frame class to use for embedding a reference.

        First checks explicit nested_frames mapping, then falls back
        to the frame registry based on the reference's context model.
        """
        if predicate_uri in self.nested_frames:
            return self.nested_frames[predicate_uri]

        return FrameRegistry.get_frame_class_for_reference(reference)

    @classmethod
    def get_context_model_class(cls):
        """Get the context model this frame applies to"""
        return cls.context_model_class


class FrameRegistry:
    """
    Global registry mapping context models to frame classes.

    Provides automatic frame selection based on which context
    models have data for a given reference.
    """

    _registry: Dict[Type, Type[LinkedDataFrame]] = {}

    @classmethod
    def register(cls, context_model: Type, frame_class: Type[LinkedDataFrame]):
        """Register a frame for a context model"""
        cls._registry[context_model] = frame_class

    @classmethod
    def get_frame_class_for_reference(cls, reference) -> Optional[Type[LinkedDataFrame]]:
        """
        Get the appropriate frame class for a reference.

        Returns the frame class (not instance) with highest priority
        among context models that have data.
        """
        from activitypub.settings import app_settings

        candidates = []

        for context_model_class in app_settings.AUTOLOADED_CONTEXT_MODELS:
            context_obj = reference.get_by_context(context_model_class)
            if context_obj and context_model_class in cls._registry:
                frame_class = cls._registry[context_model_class]
                candidates.append(frame_class)

        if not candidates:
            return LinkedDataFrame

        # Select the highest priority frame
        return max(candidates, key=lambda fc: fc.priority)

    @classmethod
    def get_frame_for_reference(cls, reference, serializer=None) -> LinkedDataFrame:
        """
        Get an instantiated frame for a reference.

        Automatically selects the appropriate frame class and instantiates it.
        """
        frame_class = cls.get_frame_class_for_reference(reference)
        if frame_class is None:
            return LinkedDataFrame(serializer=serializer)
        return frame_class(serializer=serializer)

    @classmethod
    def auto_frame(cls, serializer) -> LinkedDataFrame:
        """
        Convenience method to automatically create a frame for a serializer.

        Usage in tasks/views:
            frame = FrameRegistry.auto_frame(serializer)
            document = frame.to_framed_document()
        """
        reference = serializer.instance
        return cls.get_frame_for_reference(reference, serializer=serializer)


class ObjectFrame(LinkedDataFrame):
    """Frame for generic AS2 Object resources"""

    priority = 0

    rules = {
        str(AS2.replies): [
            FramingRule(
                str(AS2.replies),
                action=FramingRule.REFERENCE,
                when=lambda ctx: ctx.is_main_subject,
            ),
            FramingRule(
                str(AS2.replies), action=FramingRule.OMIT, when=lambda ctx: ctx.is_embedded
            ),
        ],
    }


class ActorFrame(LinkedDataFrame):
    """Frame for Actor resources (Person, Service, etc.)"""

    priority = 5

    rules = {
        str(AS2.inbox): [
            FramingRule(
                str(AS2.inbox), action=FramingRule.REFERENCE, when=lambda ctx: ctx.is_main_subject
            ),
            FramingRule(str(AS2.inbox), action=FramingRule.OMIT, when=lambda ctx: ctx.is_embedded),
        ],
        str(AS2.outbox): [
            FramingRule(
                str(AS2.outbox), action=FramingRule.REFERENCE, when=lambda ctx: ctx.is_main_subject
            ),
            FramingRule(
                str(AS2.outbox), action=FramingRule.OMIT, when=lambda ctx: ctx.is_embedded
            ),
        ],
        str(AS2.following): [
            FramingRule(
                str(AS2.following),
                action=FramingRule.REFERENCE,
                when=lambda ctx: ctx.is_main_subject,
            ),
            FramingRule(
                str(AS2.following), action=FramingRule.OMIT, when=lambda ctx: ctx.is_embedded
            ),
        ],
        str(AS2.followers): [
            FramingRule(
                str(AS2.followers),
                action=FramingRule.REFERENCE,
                when=lambda ctx: ctx.is_main_subject,
            ),
            FramingRule(
                str(AS2.followers), action=FramingRule.OMIT, when=lambda ctx: ctx.is_embedded
            ),
        ],
    }


class CollectionPageFrame(LinkedDataFrame):
    """Frame for CollectionPage resources"""

    priority = 10

    rules = {
        str(AS2.items): [
            FramingRule(str(AS2.items), action=FramingRule.REFERENCE),
        ],
        str(AS2.orderedItems): [
            FramingRule(str(AS2.orderedItems), action=FramingRule.REFERENCE),
        ],
    }


class CollectionFrame(LinkedDataFrame):
    """Frame for Collection resources"""

    priority = 8

    rules = {
        str(AS2.first): [
            FramingRule(
                str(AS2.first), action=FramingRule.EMBED, when=lambda ctx: ctx.is_main_subject
            ),
            FramingRule(
                str(AS2.first), action=FramingRule.REFERENCE, when=lambda ctx: ctx.is_embedded
            ),
        ],
        str(AS2.items): [
            FramingRule(
                str(AS2.items), action=FramingRule.REFERENCE, when=lambda ctx: ctx.is_main_subject
            ),
            FramingRule(str(AS2.items), action=FramingRule.OMIT, when=lambda ctx: ctx.is_embedded),
        ],
        str(AS2.orderedItems): [
            FramingRule(
                str(AS2.orderedItems),
                action=FramingRule.REFERENCE,
                when=lambda ctx: ctx.is_main_subject,
            ),
            FramingRule(
                str(AS2.orderedItems), action=FramingRule.OMIT, when=lambda ctx: ctx.is_embedded
            ),
        ],
    }

    nested_frames = {
        str(AS2.first): CollectionPageFrame,
    }


class ChoiceFrame(LinkedDataFrame):
    """
    Frame for choice options.

    Embeds replies collection (to show id and totalItems),
    but omits likes and shares.
    """

    priority = 0

    rules = {
        str(AS2.replies): [
            FramingRule(str(AS2.replies), action=FramingRule.EMBED),
        ],
        str(AS2.likes): [
            FramingRule(str(AS2.likes), action=FramingRule.OMIT),
        ],
        str(AS2.shares): [
            FramingRule(str(AS2.shares), action=FramingRule.OMIT),
        ],
    }

    nested_frames = {
        str(AS2.replies): CollectionFrame,
    }


class QuestionFrame(ObjectFrame):
    """Frame for Question objects with embedded choices"""

    priority = 10

    rules = {
        **ObjectFrame.rules,
        str(AS2.oneOf): [
            FramingRule(str(AS2.oneOf), action=FramingRule.EMBED),
        ],
        str(AS2.anyOf): [
            FramingRule(str(AS2.anyOf), action=FramingRule.EMBED),
        ],
    }

    nested_frames = {
        str(AS2.oneOf): ChoiceFrame,
        str(AS2.anyOf): ChoiceFrame,
    }


class ActivityFrame(LinkedDataFrame):
    """Frame for Activity resources"""

    priority = 10

    rules = {
        str(AS2.actor): [
            FramingRule(
                str(AS2.actor), action=FramingRule.REFERENCE, when=lambda ctx: ctx.is_main_subject
            ),
        ],
        str(AS2.object): [
            FramingRule(
                str(AS2.object), action=FramingRule.REFERENCE, when=lambda ctx: ctx.is_main_subject
            ),
        ],
    }

    nested_frames = {
        str(AS2.actor): ActorFrame,
        str(AS2.object): ObjectFrame,
    }


class RepliesCollectionFrame(CollectionFrame):
    """Frame for replies collections that omits items"""

    priority = 12

    rules = {
        **CollectionFrame.rules,
        str(AS2.items): [
            FramingRule(str(AS2.items), action=FramingRule.OMIT),
        ],
        str(AS2.orderedItems): [
            FramingRule(str(AS2.orderedItems), action=FramingRule.OMIT),
        ],
    }


class As2ObjectFrame(ObjectFrame):
    """Legacy alias for ObjectFrame"""

    nested_frames = {
        str(AS2.replies): RepliesCollectionFrame,
    }


class OutboxFrame(CollectionFrame):
    """Frame for Outbox collections with embedded first page"""

    priority = 12

    rules = {
        **CollectionFrame.rules,
        str(AS2.first): [
            FramingRule(str(AS2.first), action=FramingRule.EMBED),
        ],
    }

    nested_frames = {
        str(AS2.first): CollectionPageFrame,
    }


def _register_frames():
    """Register all frame classes with their context models"""
    from activitypub.models.as2 import (
        ActivityContext,
        ActorContext,
        ObjectContext,
        QuestionContext,
    )
    from activitypub.models.collections import CollectionContext, CollectionPageContext

    FrameRegistry.register(ActorContext, ActorFrame)
    FrameRegistry.register(CollectionContext, CollectionFrame)
    FrameRegistry.register(CollectionPageContext, CollectionPageFrame)
    FrameRegistry.register(ObjectContext, ObjectFrame)
    FrameRegistry.register(QuestionContext, QuestionFrame)
    FrameRegistry.register(ActivityContext, ActivityFrame)


__all__ = (
    "FramingContext",
    "FramingRule",
    "LinkedDataFrame",
    "FrameRegistry",
    "RepliesCollectionFrame",
    "As2ObjectFrame",
    "QuestionFrame",
    "OutboxFrame",
    "ActorFrame",
    "CollectionFrame",
    "CollectionPageFrame",
    "ObjectFrame",
    "ActivityFrame",
    "ChoiceFrame",
)
