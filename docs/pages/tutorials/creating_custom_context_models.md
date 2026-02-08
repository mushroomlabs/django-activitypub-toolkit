---
title: Creating Custom Context Models
---

This tutorial teaches you how to extend Django ActivityPub Toolkit with custom context models for specialized vocabularies. You will learn to handle vocabulary extensions from platforms like Mastodon, and create entirely new vocabularies for your domain-specific needs.

By the end of this tutorial, you will understand how to map RDF predicates to Django fields, implement context detection logic, and integrate custom contexts into the toolkit's processing pipeline.

## Understanding Context Definitions

Before implementing context models, you need to understand how the toolkit defines JSON-LD contexts and vocabularies. The `Context` dataclass from `activitypub.contexts` defines the structure and semantics of different ActivityPub vocabularies.

### The Context Dataclass

A `Context` instance defines a JSON-LD context document and its associated namespace:

```python
from activitypub.contexts import Context
from rdflib import Namespace

# Define a custom vocabulary namespace
MY_VOCAB = Namespace("https://myapp.example/ns/vocab#")

# Create a context definition
MY_CONTEXT = Context(
    url="https://myapp.example/contexts/vocab.jsonld",
    namespace=MY_VOCAB,
    document={
        "@context": {
            "myvocab": "https://myapp.example/ns/vocab#",
            "customProperty": {
                "@id": "myvocab:customProperty",
                "@type": "http://www.w3.org/2001/XMLSchema#string"
            },
            "rating": {
                "@id": "myvocab:rating",
                "@type": "http://www.w3.org/2001/XMLSchema#integer"
            }
        }
    }
)
```

Each `Context` has four fields:

- `url`: The URL where the context document can be fetched
- `document`: The JSON-LD context document as a Python dict
- `namespace`: An RDF namespace for creating URIs (optional)
- `content_type`: HTTP content type, defaults to "application/ld+json"

### Namespaces and Vocabulary Terms

Namespaces provide type-safe access to vocabulary terms:

```python
from activitypub.contexts import AS2, SEC, MASTODON

# Standard ActivityStreams terms
note_type = AS2.Note        # https://www.w3.org/ns/activitystreams#Note
content_pred = AS2.content  # https://www.w3.org/ns/activitystreams#content

# Security vocabulary terms
public_key = SEC.publicKey  # https://w3id.org/security#publicKey

# Platform-specific terms
featured = MASTODON.featured  # http://joinmastodon.org/ns#featured
```

### Context Registration

Contexts are registered in Django settings under the `FEDERATION` configuration. The toolkit loads standard contexts automatically, but you can add custom ones:

```python
FEDERATION = {
    # ... other settings ...
    'EXTRA_CONTEXTS': {
        'myapp.contexts.MY_CONTEXT',
    },
}
```

Once registered, contexts are available through the `PRESET_CONTEXTS` setting and used during JSON-LD serialization.

### How Contexts Enable Vocabulary Extensions

Contexts define how your custom vocabulary terms map to JSON-LD. When your application serializes data, the context document tells other servers how to interpret your custom properties:

```json
{
  "@context": [
    "https://www.w3.org/ns/activitystreams",
    "https://myapp.example/contexts/vocab.jsonld"
  ],
  "id": "http://myapp.example/objects/123",
  "type": "Note",
  "content": "A note with custom properties",
  "myvocab:customProperty": "custom value",
  "myvocab:rating": 5
}
```

The context document defines the semantics of `myvocab:customProperty` and `myvocab:rating`, enabling other ActivityPub implementations to understand your extended vocabulary.

## Understanding Context Models

Context models implement the storage and processing layer for specific object types from particular applications or platforms. They translate between RDF graphs and Django's relational model. Context models are composable - each handles only its specific fields without overlapping with other contexts. Multiple context models can process the same reference, each extracting their respective fields.

A context model extends `AbstractContextModel` and defines:

- `CONTEXT` - Reference to the Context definition (required for proper serialization)
- `LINKED_DATA_FIELDS` - Mapping from Django field names to RDF predicates
- `should_handle_reference()` - Logic to detect when this context applies (discriminates by object type, not namespace presence)
- Django fields for storing vocabulary data

Multiple context models can attach to the same reference. An actor might have `ActorContext` for AS2 properties and `SecV1Context` for cryptographic keys. A note might have `ObjectContext` for basic Note properties and `MastodonNoteContext` for Mastodon-specific extensions. Your custom context model adds additional vocabulary without interfering with existing contexts. Context models are composable - each handles only its specific fields.

## Scenario: Handling Mastodon Notes

Mastodon extends the basic ActivityStreams Note type with platform-specific features like content warnings, visibility settings, and sensitive media flags. The AS2 context handles basic Note properties (type, content, published), while a specialized Mastodon context handles Mastodon-specific extensions. Context models are composable - each handles only its specific fields without overlapping.

First, examine the existing Mastodon context definition:

```python
from activitypub.contexts import MASTODON_CONTEXT, MASTODON, AS2

# The context defines Mastodon's vocabulary extensions
print(MASTODON_CONTEXT.url)  # https://docs.joinmastodon.org/spec/activitypub/
print(MASTODON_CONTEXT.namespace)  # Namespace('http://joinmastodon.org/ns#')

# Access vocabulary terms
sensitive_pred = MASTODON.sensitive   # Mastodon-specific property
blurhash_pred = MASTODON.blurhash     # Media preview hash
```

Now create a context model that handles ONLY Mastodon-specific fields. AS2 fields are handled by other context models:

```python
from django.db import models
from activitypub.core.models import AbstractContextModel
from activitypub.contexts import MASTODON_CONTEXT, MASTODON, AS2
import rdflib

class MastodonNoteContext(AbstractContextModel):
    """Context model for Mastodon Note objects - handles Mastodon-specific fields only."""

    CONTEXT = MASTODON_CONTEXT
    LINKED_DATA_FIELDS = {
        # Mastodon-specific fields only (don't overlap with AS2 or other contexts)
        'sensitive': MASTODON.sensitive,
        'atom_uri': MASTODON.atomUri,
        'conversation': MASTODON.conversation,
        'voters_count': MASTODON.votersCount,
    }

    # Content moderation fields
    sensitive = models.BooleanField(default=False, help_text="Contains sensitive content")

    # Mastodon-specific metadata
    atom_uri = models.URLField(max_length=500, null=True, blank=True)
    conversation = models.URLField(max_length=500, null=True, blank=True)
    voters_count = models.IntegerField(null=True, blank=True)

    @classmethod
    def should_handle_reference(cls, g, reference, source):
        """Check if this is a Mastodon Note by type + Mastodon-specific fields.
        The `source` reference is the actor that sent the activity and is used for authority checks.
        """
        subject_uri = rdflib.URIRef(reference.uri)

        # Must be a Note type (handled by AS2 context)
        type_val = g.value(subject=subject_uri, predicate=AS2.type)
        if type_val != AS2.Note:
            return False

        # Must have Mastodon-specific properties to confirm it's from Mastodon
        mastodon_fields = (
            g.value(subject=subject_uri, predicate=MASTODON.sensitive) or
            g.value(subject=subject_uri, predicate=MASTODON.atomUri) or
            g.value(subject=subject_uri, predicate=MASTODON.conversation)
        )

        return mastodon_fields is not None
```

## Registering the Context Model

Add your custom context model to the extra context models list in `config/settings.py`:

```python
FEDERATION = {
    'DEFAULT_URL': 'http://localhost:8000',
    'SOFTWARE_NAME': 'FedJournal',
    'SOFTWARE_VERSION': '0.1.0',
    'ACTOR_VIEW': 'journal:actor',
    'OBJECT_VIEW': 'journal:entry-detail',
    'EXTRA_CONTEXT_MODELS': [
        'journal.mastodon_context.MastodonNoteContext',
    ],
}
```

Run migrations to create the database table:

```bash
python manage.py makemigrations
python manage.py migrate
```

Now when the toolkit processes JSON-LD documents representing Mastodon notes, it automatically creates `MastodonNoteContext` instances that handle Mastodon-specific fields for that object type.

## Testing the Custom Context

Create a test document representing a Mastodon note. In the Django shell:

```python
python manage.py shell

from activitypub.core.models import LinkedDataDocument, Reference

# Simulate receiving a Mastodon note document
document = {
    "id": "https://mastodon.social/users/alice/statuses/123456",
    "@context": [
        "https://www.w3.org/ns/activitystreams",
        "https://docs.joinmastodon.org/spec/activitypub/"
    ],
    "type": "Note",
    "content": "<p>Check out this amazing sunset photo! 🌅</p>",
    "published": "2025-01-15T18:30:00Z",
    "sensitive": True,
    "atomUri": "https://mastodon.social/users/alice/statuses/123456",
    "conversation": "tag:mastodon.social,2025-01-15:objectId=123456:objectType=Conversation",
    "attachment": [
        {
            "type": "Image",
            "url": "https://files.mastodon.social/media/sunset.jpg"
        }
    ]
}

# Process the document
doc = LinkedDataDocument.make(document)
doc.load()

# Check that both contexts were created
ref = Reference.objects.get(uri='https://mastodon.social/users/alice/statuses/123456')

# AS2 context handles basic Note properties
as2_ctx = ref.get_by_context('activitypub.core.models.ObjectContext')

# Mastodon context handles Mastodon-specific extensions
mastodon_ctx = ref.get_by_context('journal.mastodon_context.MastodonNoteContext')

print(f"Note content: {as2_ctx.content if as2_ctx else 'N/A'}")
print(f"Sensitive: {mastodon_ctx.sensitive}")
print(f"Conversation: {mastodon_ctx.conversation}")
```

Context models are composable. The AS2 context handles basic Note properties (type, content, published), while the Mastodon context handles only Mastodon-specific extensions like the sensitive flag and conversation threading. Together they represent the complete Mastodon note object without field overlap.

## Accessing Custom Context Data

Update your journal entry model to provide access to Mastodon note properties:

```python
from journal.mastodon_context import MastodonNoteContext

class JournalEntry(models.Model):
    """Application model for journal entries."""
    reference = models.OneToOneField(Reference, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    # ... other fields ...

    @property
    def mastodon(self):
        """Access Mastodon note context."""
        return self.reference.get_by_context(MastodonNoteContext)

    @property
    def is_sensitive(self):
        """Check if entry contains sensitive content."""
        mastodon_ctx = self.mastodon
        return mastodon_ctx.sensitive if mastodon_ctx else False

    @property
    def conversation_id(self):
        """Get Mastodon conversation ID for threading."""
        mastodon_ctx = self.mastodon
        return mastodon_ctx.conversation if mastodon_ctx else None
```

Now you can query entries by their Mastodon properties:

```python
# Find all entries marked as sensitive
from journal.mastodon_context import MastodonNoteContext

sensitive_entries = MastodonNoteContext.objects.filter(sensitive=True)
entries = JournalEntry.objects.filter(
    reference__journal_mastodoncontext_context__in=sensitive_entries
)
```

## Creating Domain-Specific Vocabularies

Beyond handling existing vocabularies, you can create entirely new vocabularies for your domain. Suppose you want to extend journal entries with mood tracking.

First, define your custom Context in `journal/contexts.py`:

```python
from activitypub.contexts import Context
from rdflib import Namespace

# Define your custom namespace
MOOD = Namespace('https://fedjournal.example/ns/mood#')

# Create the context definition
MOOD_CONTEXT = Context(
    url='https://fedjournal.example/contexts/mood.jsonld',
    namespace=MOOD,
    document={
        "@context": {
            "mood": "https://fedjournal.example/ns/mood#",
            "level": {
                "@id": "mood:level",
                "@type": "http://www.w3.org/2001/XMLSchema#integer"
            },
            "type": {
                "@id": "mood:type",
                "@type": "@id"
            },
            "notes": "mood:notes"
        }
    }
)
```

Register your custom context in settings:

```python
FEDERATION = {
    # ... other settings ...
    'EXTRA_CONTEXTS': {
        'journal.contexts.MOOD_CONTEXT',
    },
}
```

Now create the context model that implements storage for mood properties in `journal/mood_context.py`:

```python
from django.db import models
from activitypub.core.models import AbstractContextModel
from journal.contexts import MOOD, MOOD_CONTEXT

class MoodContext(AbstractContextModel):
    """Context model for mood tracking vocabulary."""

    CONTEXT = MOOD_CONTEXT
    LINKED_DATA_FIELDS = {
        'mood_level': MOOD.level,
        'mood_type': MOOD.type,
        'mood_notes': MOOD.notes,
    }

    class MoodLevel(models.IntegerChoices):
        VERY_LOW = 1, 'Very Low'
        LOW = 2, 'Low'
        NEUTRAL = 3, 'Neutral'
        HIGH = 4, 'High'
        VERY_HIGH = 5, 'Very High'

    class MoodType(models.TextChoices):
        HAPPY = 'happy', 'Happy'
        SAD = 'sad', 'Sad'
        ANXIOUS = 'anxious', 'Anxious'
        CALM = 'calm', 'Calm'
        ENERGETIC = 'energetic', 'Energetic'
        TIRED = 'tired', 'Tired'

    mood_level = models.IntegerField(
        choices=MoodLevel.choices,
        null=True,
        blank=True
    )
    mood_type = models.CharField(
        max_length=20,
        choices=MoodType.choices,
        null=True,
        blank=True
    )
    mood_notes = models.TextField(blank=True)

    @classmethod
    def should_handle_reference(cls, g, reference):
        """Check if this reference has mood properties."""
        subject_uri = rdflib.URIRef(reference.uri)

        # Check for any mood predicate
        level_val = g.value(subject=subject_uri, predicate=MOOD.level)
        type_val = g.value(subject=subject_uri, predicate=MOOD.type)

        return level_val is not None or type_val is not None

    class Meta:
        verbose_name = 'Mood Context'
        verbose_name_plural = 'Mood Contexts'
```

Register it in settings:

```python
FEDERATION = {
    # ... other settings ...
    'EXTRA_CONTEXT_MODELS': [
        'journal.mood_context.MoodContext',
    ],
}
```

Run migrations:

```bash
python manage.py makemigrations
python manage.py migrate
```

## Creating Entries with Mastodon Context

You can create journal entries that include Mastodon-specific metadata. This allows entries to federate with Mastodon servers while preserving platform-specific features like content warnings:

```python
from journal.mastodon_context import MastodonNoteContext

class JournalEntry(models.Model):
    # ... existing code ...

    @classmethod
    def create_entry(cls, user, content, entry_type=EntryType.PERSONAL,
                     title=None, duration=None, sensitive=False):
        """Create a journal entry with optional Mastodon context."""
        # Generate reference and create AS2 context
        domain = Domain.get_default()
        reference = ObjectContext.generate_reference(domain)

        obj_context = ObjectContext.make(
            reference=reference,
            type=ObjectContext.Types.NOTE,
            content=content,
            name=title,
            published=timezone.now(),
            duration=duration,
        )

        # Create Mastodon context if entry is marked sensitive
        if sensitive:
            MastodonNoteContext.objects.create(
                reference=reference,
                sensitive=True,
            )

        # Create application entry
        entry = cls.objects.create(
            reference=reference,
            user=user,
            entry_type=entry_type,
        )

        return entry
```

## Creating Entries with Mood Tracking

Beyond handling existing platform vocabularies, you can also create domain-specific vocabularies. The following example shows how to add mood tracking to journal entries.

Update the entry creation method to include both Mastodon and mood data:

```python
from journal.mood_context import MoodContext

class JournalEntry(models.Model):
    # ... existing code ...

    @classmethod
    def create_entry(cls, user, content, entry_type=EntryType.PERSONAL,
                     title=None, duration=None, mood_level=None, mood_type=None):
        """Create a journal entry with mood tracking."""
        # Generate reference and create AS2 context
        domain = Domain.get_default()
        reference = ObjectContext.generate_reference(domain)

        obj_context = ObjectContext.make(
            reference=reference,
            type=ObjectContext.Types.NOTE,
            content=content,
            name=title,
            published=timezone.now(),
            duration=duration,
        )

        # Create mood context if mood data provided
        if mood_level is not None or mood_type is not None:
            MoodContext.objects.create(
                reference=reference,
                mood_level=mood_level,
                mood_type=mood_type,
            )

        # Create application entry
        entry = cls.objects.create(
            reference=reference,
            user=user,
            entry_type=entry_type,
        )

        return entry

    @property
    def mood(self):
        """Access mood tracking context."""
        return self.reference.get_by_context(MoodContext)
```

Update the admin form to include both sensitive content flag and mood fields:

```python
class JournalEntryForm(forms.Form):
    user = forms.ModelChoiceField(queryset=User.objects.all(), required=True)
    entry_type = forms.ChoiceField(choices=JournalEntry.EntryType.choices, required=True)
    title = forms.CharField(max_length=200, required=False)
    content = forms.CharField(widget=forms.Textarea, required=True)
    duration_minutes = forms.IntegerField(required=False, min_value=0)
    sensitive = forms.BooleanField(required=False, help_text="Mark as sensitive content")
    mood_level = forms.ChoiceField(
        choices=[('', '---')] + list(MoodContext.MoodLevel.choices),
        required=False
    )
    mood_type = forms.ChoiceField(
        choices=[('', '---')] + list(MoodContext.MoodType.choices),
        required=False
    )

# Update the changelist_view to handle Mastodon and mood data
def changelist_view(self, request, extra_context=None):
    if request.method == 'POST':
        form = JournalEntryForm(request.POST)
        if form.is_valid():
            # ... existing duration handling ...

            sensitive = form.cleaned_data.get('sensitive', False)
            mood_level = form.cleaned_data.get('mood_level')
            mood_type = form.cleaned_data.get('mood_type')

            JournalEntry.create_entry(
                user=form.cleaned_data['user'],
                content=form.cleaned_data['content'],
                entry_type=form.cleaned_data['entry_type'],
                title=form.cleaned_data['title'] or None,
                duration=duration,
                sensitive=sensitive,
                mood_level=int(mood_level) if mood_level else None,
                mood_type=mood_type if mood_type else None,
            )
            self.message_user(request, 'Journal entry created successfully')

    # ... rest of method ...
```

## Querying Across Contexts

Custom contexts integrate with Django's ORM, enabling complex queries across vocabularies:

```python
from django.db.models import Q
from journal.mood_context import MoodContext
from activitypub.core.models import ObjectContext

# Find energetic entries over 30 minutes
energetic_long_entries = JournalEntry.objects.filter(
    reference__activitypub_objectcontext_context__duration__gt=timedelta(minutes=30),
    reference__journal_moodcontext_context__mood_type=MoodContext.MoodType.ENERGETIC
)

# Find sensitive entries with low mood
sensitive_low_mood = JournalEntry.objects.filter(
    reference__journal_mastodoncontext_context__sensitive=True,
    reference__journal_moodcontext_context__mood_level__lte=MoodContext.MoodLevel.LOW
)

# Aggregate mood statistics
from django.db.models import Count

mood_distribution = MoodContext.objects.values('mood_type').annotate(
    count=Count('id')
).order_by('-count')
```

The ability to query across contexts while maintaining vocabulary separation is a key advantage of this architecture.

## Best Practices

**Namespace carefully.** Use URIs you control for custom vocabularies. Include your domain name to ensure global uniqueness. Document your vocabulary so others can implement it.

**Check conservatively.** The `should_handle_reference()` method should only return `True` when you're confident the data belongs to your vocabulary. Avoid claiming references that other contexts might handle.

**Handle missing data gracefully.** Not every reference will have your context. Check for `None` when accessing custom context properties. Provide sensible defaults.

**Version your vocabulary.** If you change predicate meanings or add breaking changes, use a new namespace version. This allows gradual migration without breaking existing implementations.

**Test with real data.** Fetch documents from servers that use the vocabularies you're extending. Verify your context model correctly extracts data from real-world JSON-LD.

## Summary

You have learned to create custom Context definitions and their corresponding context models for both existing platform extensions and entirely new vocabularies. Context definitions establish the vocabulary semantics, while context models provide the storage and processing implementation.

The pattern applies universally: define your Context with namespace and document, register it in settings, create the context model with field mappings, implement detection logic, register the model, and run migrations. Multiple contexts coexist on references, each handling its vocabulary independently.

Custom contexts enable applications to extend ActivityPub without forking the protocol. Your mood tracking vocabulary might gain adoption. Other servers implementing it can federate mood data with yours. This is how the Fediverse evolves—through vocabulary extension rather than protocol modification.

To learn how to present your custom context data to remote viewers when they fetch your objects, see the Publishing to the Fediverse tutorial, which covers projections for controlling JSON-LD output.

The next tutorial covers handling incoming activities, where you will learn to process federated actions that arrive at your server's inbox.
