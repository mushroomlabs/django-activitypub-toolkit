---
title: Creating Custom Context Models
---

This tutorial teaches you how to extend Django ActivityPub Toolkit with custom context models for specialized vocabularies. You will learn to handle vocabulary extensions from platforms like Mastodon and Lemmy, and create entirely new vocabularies for your domain-specific needs.

By the end of this tutorial, you will understand how to map RDF predicates to Django fields, implement context detection logic, and integrate custom contexts into the toolkit's processing pipeline.

## Understanding Context Models

Context models translate between RDF graphs and Django's relational model. Each context model represents a specific vocabulary or namespace. The toolkit includes context models for ActivityStreams 2.0 (AS2) and Security Vocabulary v1 (SECv1). Your applications can add context models for any vocabulary.

A context model extends `AbstractContextModel` and defines:

- `NAMESPACE` - The RDF namespace URI
- `LINKED_DATA_FIELDS` - Mapping from Django field names to RDF predicates
- `should_handle_reference()` - Logic to detect when this context applies
- Django fields for storing vocabulary data

Multiple context models can attach to the same reference. An actor might have `ActorContext` for AS2 properties and `SecV1Context` for cryptographic keys. Your custom context adds additional vocabulary without interfering with existing contexts.

## Scenario: Adding Mastodon Extensions

Mastodon extends ActivityPub with several custom properties. The `featured` property links to a collection of pinned posts. The `sensitive` flag marks content requiring warnings. These extensions use Mastodon's vocabulary namespace.

Create a context model for Mastodon extensions in a new file `journal/mastodon_context.py`:

```python
from django.db import models
import rdflib
from activitypub.models import AbstractContextModel, ReferenceField

# Define Mastodon's namespace
MASTODON = rdflib.Namespace('http://joinmastodon.org/ns#')

class MastodonContext(AbstractContextModel):
    """Context model for Mastodon-specific extensions."""
    
    NAMESPACE = str(MASTODON)
    LINKED_DATA_FIELDS = {
        'featured': MASTODON.featured,
        'sensitive': MASTODON.sensitive,
    }
    
    # Featured collection - posts the actor has pinned
    featured = models.ForeignKey(
        'activitypub.Reference',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mastodon_featured_by'
    )
    
    # Content warning flag
    sensitive = models.BooleanField(default=False)
    
    @classmethod
    def should_handle_reference(cls, g, reference):
        """Check if this reference has Mastodon properties."""
        subject_uri = rdflib.URIRef(reference.uri)
        
        # Check for any Mastodon predicate
        featured_val = g.value(subject=subject_uri, predicate=MASTODON.featured)
        sensitive_val = g.value(subject=subject_uri, predicate=MASTODON.sensitive)
        
        return featured_val is not None or sensitive_val is not None
    
    class Meta:
        verbose_name = 'Mastodon Context'
        verbose_name_plural = 'Mastodon Contexts'
```

The `LINKED_DATA_FIELDS` dictionary maps Django field names to RDF predicates. When processing a graph, the toolkit walks through this mapping and extracts values for each predicate.

The `should_handle_reference()` method determines whether this context applies to a reference. Check if the graph contains any predicates from your vocabulary. Return `True` if the context should process this reference, `False` otherwise.

## Registering the Context Model

Add your custom context to the autoloaded models list in `config/settings.py`:

```python
FEDERATION = {
    'DEFAULT_URL': 'http://localhost:8000',
    'SOFTWARE_NAME': 'FedJournal',
    'SOFTWARE_VERSION': '0.1.0',
    'ACTOR_VIEW': 'journal:actor',
    'OBJECT_VIEW': 'journal:entry-detail',
    'AUTOLOADED_CONTEXT_MODELS': [
        'activitypub.models.LinkContext',
        'activitypub.models.ObjectContext',
        'activitypub.models.ActorContext',
        'activitypub.models.ActivityContext',
        'activitypub.models.EndpointContext',
        'activitypub.models.QuestionContext',
        'activitypub.models.CollectionContext',
        'activitypub.models.CollectionPageContext',
        'activitypub.models.SecV1Context',
        'journal.mastodon_context.MastodonContext',
    ],
}
```

Run migrations to create the database table:

```bash
python manage.py makemigrations
python manage.py migrate
```

Now when the toolkit processes JSON-LD documents with Mastodon properties, it automatically creates `MastodonContext` instances.

## Testing the Custom Context

Create a test document with Mastodon properties. In the Django shell:

```python
python manage.py shell

from activitypub.models import LinkedDataDocument, Reference

# Simulate receiving a document with Mastodon extensions
document = {
    "id": "https://mastodon.social/@alice/123456",
    "@context": [
        "https://www.w3.org/ns/activitystreams",
        {
            "toot": "http://joinmastodon.org/ns#",
            "featured": {"@id": "toot:featured", "@type": "@id"},
            "sensitive": "toot:sensitive"
        }
    ],
    "type": "Note",
    "content": "This is a test post",
    "published": "2025-01-15T10:00:00Z",
    "sensitive": True
}

# Process the document
doc = LinkedDataDocument.make(document)
doc.load()

# Check that both contexts were created
ref = Reference.objects.get(uri='https://mastodon.social/@alice/123456')
obj_ctx = ref.get_by_context('activitypub.models.ObjectContext')
mastodon_ctx = ref.get_by_context('journal.mastodon_context.MastodonContext')

print(f"Object content: {obj_ctx.content}")
print(f"Sensitive flag: {mastodon_ctx.sensitive}")
```

The same reference now has two contexts. `ObjectContext` handles standard AS2 properties. `MastodonContext` handles Mastodon extensions. They coexist without conflict.

## Accessing Custom Context Data

Update your journal entry model to provide access to Mastodon properties:

```python
class JournalEntry(models.Model):
    # ... existing fields ...
    
    @property
    def mastodon(self):
        """Access Mastodon-specific context."""
        from journal.mastodon_context import MastodonContext
        return self.reference.get_by_context(MastodonContext)
    
    @property
    def is_sensitive(self):
        """Check if content is marked sensitive."""
        mastodon_ctx = self.mastodon
        return mastodon_ctx.sensitive if mastodon_ctx else False
```

Now you can query entries by their Mastodon properties:

```python
# Find all sensitive entries
from journal.mastodon_context import MastodonContext

sensitive_contexts = MastodonContext.objects.filter(sensitive=True)
sensitive_entries = JournalEntry.objects.filter(
    reference__mastodon_mastodoncontext_context__in=sensitive_contexts
)
```

## Creating Domain-Specific Vocabularies

Beyond handling existing vocabularies, you can create entirely new vocabularies for your domain. Suppose you want to extend journal entries with mood tracking.

Define a custom vocabulary namespace and context model in `journal/mood_context.py`:

```python
from django.db import models
import rdflib
from activitypub.models import AbstractContextModel

# Define your custom namespace
MOOD = rdflib.Namespace('https://fedjournal.example/ns/mood#')

class MoodContext(AbstractContextModel):
    """Context model for mood tracking vocabulary."""
    
    NAMESPACE = str(MOOD)
    CONTEXT_URL = 'https://fedjournal.example/contexts/mood.jsonld'
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
    'AUTOLOADED_CONTEXT_MODELS': [
        # ... standard contexts ...
        'journal.mastodon_context.MastodonContext',
        'journal.mood_context.MoodContext',
    ],
}
```

Run migrations:

```bash
python manage.py makemigrations
python manage.py migrate
```

## Creating Entries with Custom Context

Update the entry creation method to include mood data:

```python
class JournalEntry(models.Model):
    # ... existing code ...
    
    @classmethod
    def create_entry(cls, user, content, entry_type=EntryType.PERSONAL,
                     title=None, duration=None, mood_level=None, mood_type=None):
        """Create a journal entry with mood tracking."""
        from journal.mood_context import MoodContext
        
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
        from journal.mood_context import MoodContext
        return self.reference.get_by_context(MoodContext)
```

Update the admin form to include mood fields:

```python
class JournalEntryForm(forms.Form):
    user = forms.ModelChoiceField(queryset=User.objects.all(), required=True)
    entry_type = forms.ChoiceField(choices=JournalEntry.EntryType.choices, required=True)
    title = forms.CharField(max_length=200, required=False)
    content = forms.CharField(widget=forms.Textarea, required=True)
    duration_minutes = forms.IntegerField(required=False, min_value=0)
    mood_level = forms.ChoiceField(
        choices=[('', '---')] + list(MoodContext.MoodLevel.choices),
        required=False
    )
    mood_type = forms.ChoiceField(
        choices=[('', '---')] + list(MoodContext.MoodType.choices),
        required=False
    )

# Update the changelist_view to handle mood data
def changelist_view(self, request, extra_context=None):
    if request.method == 'POST':
        form = JournalEntryForm(request.POST)
        if form.is_valid():
            # ... existing duration handling ...
            
            mood_level = form.cleaned_data.get('mood_level')
            mood_type = form.cleaned_data.get('mood_type')
            
            JournalEntry.create_entry(
                user=form.cleaned_data['user'],
                content=form.cleaned_data['content'],
                entry_type=form.cleaned_data['entry_type'],
                title=form.cleaned_data['title'] or None,
                duration=duration,
                mood_level=int(mood_level) if mood_level else None,
                mood_type=mood_type if mood_type else None,
            )
            self.message_user(request, 'Journal entry created successfully')
    
    # ... rest of method ...
```

## Serializing Custom Context

When serving entries with custom context, the serializer automatically includes all contexts. However, you need to publish your vocabulary's JSON-LD context document so other servers can understand your terms.

Create a context document that defines your vocabulary. This would typically be served at `CONTEXT_URL`:

```json
{
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
```

When your entries serialize, they include this context and the mood properties become part of the JSON-LD output:

```json
{
  "@context": [
    "https://www.w3.org/ns/activitystreams",
    "https://fedjournal.example/contexts/mood.jsonld"
  ],
  "id": "http://localhost:8000/entries/1",
  "type": "Note",
  "content": "Had a great workout today!",
  "published": "2025-01-15T10:00:00Z",
  "duration": "PT45M",
  "mood:level": 5,
  "mood:type": "energetic"
}
```

Other servers might not understand your mood vocabulary, but they can still process the standard AS2 properties. Servers that do implement mood tracking can extract and use that data.

## Querying Across Contexts

Custom contexts integrate with Django's ORM, enabling complex queries across vocabularies:

```python
from django.db.models import Q
from journal.mood_context import MoodContext
from activitypub.models import ObjectContext

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

## Custom Serializers for Context Models

If your context needs specialized serialization logic, create a custom serializer and register it:

```python
# journal/serializers.py
from activitypub.serializers import ContextModelSerializer

class MoodContextSerializer(ContextModelSerializer):
    def show_mood_notes(self, instance, viewer):
        """Only show mood notes to the entry's author."""
        entry = instance.reference.journal_entry
        return viewer and viewer == entry.user.reference
```

Register it in settings:

```python
FEDERATION = {
    # ... other settings ...
    'CUSTOM_SERIALIZERS': {
        'journal.mood_context.MoodContext': 'journal.serializers.MoodContextSerializer',
    },
}
```

Now mood notes only appear in serialized output when the viewer is the author.

## Best Practices

**Namespace carefully.** Use URIs you control for custom vocabularies. Include your domain name to ensure global uniqueness. Document your vocabulary so others can implement it.

**Check conservatively.** The `should_handle_reference()` method should only return `True` when you're confident the data belongs to your vocabulary. Avoid claiming references that other contexts might handle.

**Handle missing data gracefully.** Not every reference will have your context. Check for `None` when accessing custom context properties. Provide sensible defaults.

**Version your vocabulary.** If you change predicate meanings or add breaking changes, use a new namespace version. This allows gradual migration without breaking existing implementations.

**Test with real data.** Fetch documents from servers that use the vocabularies you're extending. Verify your context model correctly extracts data from real-world JSON-LD.

## Summary

You have learned to create custom context models for both existing platform extensions and entirely new vocabularies. Context models map RDF predicates to Django fields, enabling relational queries over federated data.

The pattern applies universally: define the namespace, map predicates to fields, implement detection logic, register the context, and run migrations. Multiple contexts coexist on references, each handling its vocabulary independently.

Custom contexts enable applications to extend ActivityPub without forking the protocol. Your mood tracking vocabulary might gain adoption. Other servers implementing it can federate mood data with yours. This is how the Fediverse evolves—through vocabulary extension rather than protocol modification.

The next tutorial covers handling incoming activities, where you will learn to process federated actions that arrive at your server's inbox.
