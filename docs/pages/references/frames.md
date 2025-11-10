# Frames Reference

Frames control the structure and embedding of JSON-LD data during
serialization. They provide context-aware transformations that change
how resources are represented based on where they appear in a
document.

## Overview

The framing system solves a fundamental problem in federated
serialization: the same resource needs different representations
depending on context. An actor embedded in an activity should show
minimal information, but when requested directly should include full
details with collection references. A collection should embed its
first page when requested directly, but only show a reference when
embedded in an actor.

The framing architecture provides:

- **Automatic frame selection** - No manual frame specification needed
- **Context-aware rules** - Different behaviors for main subject vs
  embedded resources
- **Depth control** - Prevents infinite recursion while allowing
  useful nesting
- **Declarative configuration** - Frame behavior defined through
  rules, not imperative code

## Core Classes

### FramingContext

Tracks the position of a resource within the document tree.

**Attributes:**

- `mode` - One of `MAIN_SUBJECT`, `EMBEDDED`, or `REFERENCE_ONLY`
- `predicate` - The predicate under which this resource appears (when
  embedded)
- `depth` - Current nesting level (0 for main subject)
- `max_depth` - Maximum allowed depth before falling back to
  references

**Properties:**

- `is_main_subject` - True if this is the primary resource being
  serialized
- `is_embedded` - True if this resource is nested within another
- `at_max_depth` - True if nesting limit has been reached

### FramingRule

Declarative rule specifying how to handle a predicate in different
contexts.

**Actions:**

- `OMIT` - Exclude the predicate entirely
- `REFERENCE` - Include as `{"@id": "..."}` only
- `EMBED` - Fully embed the referenced object

**Example:**

```python
from activitypub.frames import FramingRule
from activitypub.schemas import AS2

# Only embed replies when resource is main subject
FramingRule(
    predicate=str(AS2.replies),
    action=FramingRule.EMBED,
    when=lambda ctx: ctx.is_main_subject
)
```

### LinkedDataFrame

Base class for all frames. Provides the core framing logic and
extension points.

**Class Attributes:**

- `context_model_class` - The context model this frame applies to
- `priority` - Used to resolve conflicts when multiple frames match
- `rules` - Dictionary mapping predicates to lists of FramingRules
- `nested_frames` - Dictionary mapping predicates to frame classes for
  embedding

**Methods:**

- `to_framed_document(framing_context=None)` - Apply framing rules to
  produce shaped output
- `_get_action_for_predicate(predicate_uri, framing_context)` -
  Determine action for a predicate
- `_embed_values(values, predicate_uri, parent_context)` - Recursively
  embed referenced objects

## Frame Registry

The `FrameRegistry` maintains the global mapping between context
models and frame classes, enabling automatic frame selection.

**Methods:**

- `FrameRegistry.register(context_model, frame_class)` - Register a
  frame for a context model
- `FrameRegistry.auto_frame(serializer)` - Automatically select and
  instantiate appropriate frame
- `FrameRegistry.get_frame_for_reference(reference,
  serializer=None)` - Get frame for a reference

**Usage:**

```python
from activitypub.frames import FrameRegistry
from activitypub.serializers import LinkedDataSerializer

# Automatic frame selection
serializer = LinkedDataSerializer(instance=reference, context={'viewer': viewer})
frame = FrameRegistry.auto_frame(serializer)
document = frame.to_framed_document()
```

## Built-in Frames

### ObjectFrame

Generic frame for ActivityStreams objects. Handles replies collections
based on context.

**Priority:** 0 (lowest)

**Rules:**
- Replies: Referenced when main subject, omitted when embedded

### ActorFrame

Frame for actor resources (Person, Service, Group, etc.).

**Priority:** 5

**Rules:**
- Collections (inbox, outbox, followers, following): Referenced when
  main subject, omitted when embedded
- Shows full actor details when the actor is the document subject
- Shows minimal details when actor is embedded in an activity

### CollectionFrame

Frame for collection resources.

**Priority:** 8

**Rules:**
- `first`: Embedded when main subject, referenced when embedded
- `items`/`orderedItems`: Referenced when main subject, omitted when
  embedded

**Nested Frames:**
- `first` → `CollectionPageFrame`

### CollectionPageFrame

Frame for collection page resources.

**Priority:** 10

**Rules:**
- `items`/`orderedItems`: Always referenced (never omit)

### QuestionFrame

Frame for Question objects with embedded choice options.

**Priority:** 10 (overrides ObjectFrame)

**Rules:**
- Inherits from ObjectFrame
- `oneOf`: Always embedded
- `anyOf`: Always embedded

**Nested Frames:**
- `oneOf` → `ChoiceFrame`
- `anyOf` → `ChoiceFrame`

### ChoiceFrame

Simplified frame for question choice options.

**Priority:** 0

**Rules:**
- `replies`: Embedded (shows collection with totalItems)
- `likes`: Omitted
- `shares`: Omitted

**Nested Frames:**
- `replies` → `CollectionFrame`

### ActivityFrame

Frame for activity resources.

**Priority:** 10

**Rules:**
- `actor`: Referenced (not embedded)
- `object`: Referenced (not embedded, to avoid embedding complexity)

**Nested Frames:**
- `actor` → `ActorFrame`
- `object` → `ObjectFrame`

### RepliesCollectionFrame

Specialized collection frame that omits items.

**Priority:** 12

**Rules:**
- Inherits from CollectionFrame
- `items`: Always omitted
- `orderedItems`: Always omitted

### OutboxFrame

Collection frame that embeds first page.

**Priority:** 12

**Rules:**
- Inherits from CollectionFrame
- `first`: Always embedded

## Creating Custom Frames

Define custom frames by subclassing `LinkedDataFrame`:

```python from activitypub.frames import LinkedDataFrame, FramingRule,
FrameRegistry from activitypub.schemas import AS2 from myapp.models
import CustomContext

class CustomFrame(LinkedDataFrame):
    context_model_class = CustomContext
    priority = 10

    rules = {
        str(AS2.attachment): [
            # Embed attachments when resource is main subject
            FramingRule(
                str(AS2.attachment),
                action=FramingRule.EMBED,
                when=lambda ctx: ctx.is_main_subject
            ),
            # Omit attachments when embedded
            FramingRule(
                str(AS2.attachment),
                action=FramingRule.OMIT,
                when=lambda ctx: ctx.is_embedded
            ),
        ],
        str(AS2.tag): [
            # Always reference tags
            FramingRule(str(AS2.tag), action=FramingRule.REFERENCE),
        ],
    }

    nested_frames = {
        str(AS2.attachment): ObjectFrame,
    }

# Register the frame
FrameRegistry.register(CustomContext, CustomFrame)
```

## Conditional Rules

Rules can include conditional logic through the `when` parameter:

```python
rules = {
    str(AS2.followers): [
        # Show followers collection only to the actor themselves
        FramingRule(
            str(AS2.followers),
            action=FramingRule.REFERENCE,
            when=lambda ctx: ctx.is_main_subject and is_owner(ctx)
        ),
        # Omit for all other viewers
        FramingRule(
            str(AS2.followers),
            action=FramingRule.OMIT,
            when=lambda ctx: not is_owner(ctx)
        ),
    ],
}
```

## Frame Priority

When multiple frames could handle a reference (e.g., `QuestionContext`
is also an `ObjectContext`), the frame with the highest priority wins.

Priority resolution:
1. Find all frames whose `context_model_class` has data for the
   reference
2. Select the frame with the highest `priority` value
3. Use that frame's rules and nested frames

Example:

```python
# QuestionFrame has priority=10, ObjectFrame has priority=0
# When serializing a Question reference, QuestionFrame is selected
```

## Depth Control

The framing system prevents infinite recursion through depth tracking:

- Main subject starts at depth 0
- Each embedding increments depth
- At `max_depth` (default 2), resources show only `@id`, `@type`, and
  scalar fields
- This allows collections to show `totalItems` even when deeply nested

**Example nesting:**
- Question (depth=0, main subject)
  - Choice in `oneOf` (depth=1, embedded)
    - Collection in `replies` (depth=2, at max depth, shows
      id/type/totalItems)

## Integration with Views

Views automatically use frame selection:

```python
from activitypub.views import LinkedDataModelView

class UserOutboxView(LinkedDataModelView):
    def get_object(self):
        return user.profile.actor.outbox

    # No need to specify frame - CollectionFrame auto-selected
```

To override automatic selection:

```python
from activitypub.frames import OutboxFrame

class UserOutboxView(LinkedDataModelView):
    def get_frame_class(self):
        return OutboxFrame  # Manual override
```

## Integration with Tasks

Tasks also use automatic frame selection:

```python
from activitypub.frames import FrameRegistry
from activitypub.serializers import LinkedDataSerializer

# In a task
serializer = LinkedDataSerializer(instance=notification.resource, context={'viewer': viewer})
frame = FrameRegistry.auto_frame(serializer)
document = frame.to_framed_document()
```

## Advanced Patterns

### Conditional Embedding Based on Privacy

```python
class PrivateObjectFrame(ObjectFrame):
    def _get_action_for_predicate(self, predicate_uri, framing_context):
        # Custom logic based on viewer permissions
        viewer = self.serializer.context.get('viewer')
        if not self._can_view_field(predicate_uri, viewer):
            return FramingRule.OMIT
        return super()._get_action_for_predicate(predicate_uri, framing_context)
```

### Dynamic Nested Frames

```python
class SmartFrame(LinkedDataFrame):
    def _get_nested_frame_for_predicate(self, predicate_uri, reference):
        # Select frame based on reference type
        if is_question(reference):
            return QuestionFrame
        return super()._get_nested_frame_for_predicate(predicate_uri, reference)
```

## Best Practices

1. **Use automatic selection** - Let the registry choose frames based
   on context models
2. **Inherit from existing frames** - Extend `ObjectFrame`,
   `CollectionFrame`, etc. rather than starting from scratch
3. **Set appropriate priorities** - More specific frames should have
   higher priority
4. **Use `when` conditionals** - Make rules context-aware rather than
   creating multiple frame classes
5. **Limit nesting depth** - Respect `max_depth` to prevent
   performance issues
6. **Test different contexts** - Verify frames work correctly both as
   main subject and when embedded

## Debugging Frames

Enable debug logging to see frame selection and rule application:

```python
import logging
logging.getLogger('activitypub.frames').setLevel(logging.DEBUG)
```

Check which frame was selected:

```python
frame = FrameRegistry.auto_frame(serializer)
print(f"Selected frame: {frame.__class__.__name__}")
print(f"Context model: {frame.context_model_class}")
print(f"Priority: {frame.priority}")
```

Inspect framed output before compaction:

```python
expanded_document = frame.to_framed_document()
# Examine structure before JSON-LD compaction
```
