---
title: Getting Started
---

This tutorial builds a federated journal application where users write entries about their daily activities and share them across the Fediverse. You will learn how Django ActivityPub Toolkit enables applications to operate on the social graph rather than replicating it.

By the end of this tutorial, you will have a working application that federates journal entries using ActivityStreams vocabulary, demonstrates reference-first architecture, and integrates with existing ActivityPub servers.

## Prerequisites

You need Python 3.9 or higher, basic Django knowledge, and familiarity with virtual environments. Understanding HTTP and JSON helps but is not required. No prior ActivityPub or Linked Data experience is necessary—the tutorial explains concepts as they appear.

## Project Setup

Create a new Django project for the journal application:

```bash
mkdir fedjournal
cd fedjournal
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

pip install django django-activitypub-toolkit
django-admin startproject config .
python manage.py startapp journal
```

Add the toolkit and your app to `INSTALLED_APPS` in `config/settings.py`:

```python
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'activitypub',
    'journal',
]
```

Configure the toolkit's basic settings:

```python
FEDERATION = {
    'DEFAULT_URL': 'http://localhost:8000',
    'SOFTWARE_NAME': 'FedJournal',
    'SOFTWARE_VERSION': '0.1.0',
    'ACTOR_VIEW': 'journal:actor',
    'OBJECT_VIEW': 'journal:entry-detail',
}
```

Run initial migrations:

```bash
python manage.py migrate
```

## Understanding the Architecture

A journal application stores entries users write. Each entry has content, a timestamp, and optionally metadata like duration or tags. Users own their entries and can share them with followers.

The toolkit's architecture separates application concerns from federation concerns. Your application model handles business logic—user relationships, entry categorization, privacy settings. ActivityPub context models handle federation—the content that appears in the Fediverse, publication timestamps, addressing.

The `Reference` connects these layers. Both your application model and the context models link to the same reference. The reference has a URI that identifies this resource globally across the Fediverse.

## Understanding Contexts and Namespaces

Before creating your application model, you need to understand how the toolkit defines JSON-LD contexts and vocabularies. The `Context` dataclass from `activitypub.contexts` defines how different ActivityPub vocabularies are structured and used.

### The Context Dataclass

A `Context` instance defines a JSON-LD context document and its associated namespace:

```python
from activitypub.contexts import Context
from rdflib import Namespace

# Example: ActivityStreams 2.0 context
AS2 = Namespace("https://www.w3.org/ns/activitystreams#")
AS2_CONTEXT = Context(
    url="https://www.w3.org/ns/activitystreams",
    namespace=AS2,
    document={
        "@context": {
            "@vocab": "_:",
            "xsd": "http://www.w3.org/2001/XMLSchema#",
            "as": "https://www.w3.org/ns/activitystreams#",
            # ... vocabulary definitions
        }
    }
)
```

Each `Context` has four fields:
- `url`: The URL where the context document can be fetched
- `document`: The JSON-LD context document as a Python dict
- `namespace`: An RDF namespace for creating URIs (optional)
- `content_type`: HTTP content type, defaults to "application/ld+json"

**Important**: While namespaces are used for RDF bookkeeping, context models are organized by object type rather than namespace. A single context model handles all fields for a specific kind of object (like "Lemmy Community"), regardless of which namespaces those fields come from.

### Namespaces and Vocabularies

The toolkit defines several standard namespaces for common ActivityPub vocabularies:

```python
from activitypub.contexts import AS2, SEC, MASTODON, LEMMY

# ActivityStreams 2.0 namespace
note_uri = AS2.Note  # https://www.w3.org/ns/activitystreams#Note

# Security namespace
public_key_uri = SEC.publicKey  # https://w3id.org/security#publicKey

# Platform-specific namespaces
featured_uri = MASTODON.featured  # http://joinmastodon.org/ns#featured
```

These namespaces enable type-safe URI construction and are used throughout the toolkit for mapping between RDF predicates and Django model fields.

### Context Configuration

Contexts are configured in your Django settings under the `FEDERATION` key. The toolkit automatically loads standard contexts, but you can add custom ones:

```python
FEDERATION = {
    'DEFAULT_URL': 'http://localhost:8000',
    'SOFTWARE_NAME': 'FedJournal',
    'SOFTWARE_VERSION': '0.1.0',
    'ACTOR_VIEW': 'journal:actor',
    'OBJECT_VIEW': 'journal:entry-detail',
    # Custom contexts are added here if needed
}
```

The `PRESET_CONTEXTS` property provides access to all configured contexts for serialization and processing.

### How Contexts Enable Federation

When your application serves JSON-LD documents, the toolkit includes appropriate `@context` declarations. This tells other servers how to interpret your data:

```json
{
  "@context": "https://www.w3.org/ns/activitystreams",
  "id": "http://localhost:8000/entries/1",
  "type": "Note",
  "content": "My journal entry",
  "published": "2025-01-15T10:00:00Z"
}
```

The context document defines terms like `Note`, `content`, and `published`, mapping them to full URIs. This enables semantic interoperability across different ActivityPub implementations.

## Creating the Application Model

Create your application model in `journal/models.py`:

```python
from django.db import models
from django.contrib.auth.models import User
from activitypub.models import Reference, ObjectContext

class JournalEntry(models.Model):
    class EntryType(models.TextChoices):
        PERSONAL = 'personal', 'Personal'
        WORK = 'work', 'Work'
        EXERCISE = 'exercise', 'Exercise'
        LEARNING = 'learning', 'Learning'
        CREATIVE = 'creative', 'Creative'

    reference = models.OneToOneField(
        Reference,
        on_delete=models.CASCADE,
        related_name='journal_entry'
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    entry_type = models.CharField(
        max_length=20,
        choices=EntryType.choices,
        default=EntryType.PERSONAL
    )

    class Meta:
        ordering = ['-id']
        verbose_name_plural = 'journal entries'

    def __str__(self):
        return f"{self.user.username}'s {self.entry_type} entry"

    @property
    def as2(self):
        """Access the ActivityStreams context for this entry."""
        return self.reference.get_by_context(ObjectContext)
```

The `reference` field links to the toolkit's `Reference` model. This reference serves as the anchor connecting your application data to the federated social graph. The `entry_type` field is application-specific—it categorizes entries for your business logic but doesn't federate. Federated data like content and publication time live in the ActivityStreams context, accessed through `entry.as2`.

## Setting Up the Domain

The domain represents your server instance in the federation. You can run multiple domains on the same server. There is a convenient method to register domains. Simply run this command:

```bash
python manage.py register_local_instance -u http://localhost:8000 # (Or any URL you your development server can listen on)
```

## Creating Journal Entries

When a user writes a journal entry, create both the application record and the ActivityPub context. Add a helper method to your model:

```python
from django.utils import timezone
from datetime import timedelta
from activitypub.models import Reference, ObjectContext, Domain

class JournalEntry(models.Model):
    # ... existing fields ...

    @classmethod
    def create_entry(cls, user, content, entry_type=EntryType.PERSONAL,
                     title=None, duration=None):
        """Create a journal entry with its ActivityPub representation."""
        # Generate a reference for this entry
        domain = Domain.get_default()
        reference = ObjectContext.generate_reference(domain)

        # Create the ActivityPub context using AS2 vocabulary
        obj_context = ObjectContext.make(
            reference=reference,
            type=ObjectContext.Types.NOTE,
            content=content,
            name=title,
            published=timezone.now(),
            duration=duration,
        )

        # Create the application entry
        entry = cls.objects.create(
            reference=reference,
            user=user,
            entry_type=entry_type,
        )

        return entry
```

This pattern demonstrates the reference-first architecture. Generate a reference with a URI. Create the ActivityPub context with federated fields like `content`, `published`, and `duration`. Create your application model linking to the same reference. Both models now share the reference as their connection point.

The context model fields map to ActivityStreams vocabulary defined in the `AS2_CONTEXT`. The `AS2` namespace provides the vocabulary terms:
- `content` maps to `as:content` in the JSON-LD output
- `published` maps to `as:published`
- `duration` maps to `as:duration`
- `name` maps to `as:name`

These mappings are defined in the `AS2_CONTEXT.document` and enable your data to be understood by other ActivityPub servers.

## Admin Interface

Set up Django admin to test entry creation. Create `journal/admin.py`:

```python
from django.contrib import admin
from django.utils import timezone
from datetime import timedelta
from journal.models import JournalEntry

@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ('user', 'entry_type', 'get_published', 'get_title')
    list_filter = ('entry_type', 'user')
    readonly_fields = ('reference', 'get_content', 'get_published', 'get_duration')
    fields = ('user', 'entry_type', 'reference', 'get_content',
              'get_published', 'get_duration')

    def get_published(self, obj):
        return obj.as2.published if obj.as2 else None
    get_published.short_description = 'Published'

    def get_title(self, obj):
        return obj.as2.name if obj.as2 else '(untitled)'
    get_title.short_description = 'Title'

    def get_content(self, obj):
        return obj.as2.content if obj.as2 else None
    get_content.short_description = 'Content'

    def get_duration(self, obj):
        return obj.as2.duration if obj.as2 else None
    get_duration.short_description = 'Duration'

    def has_add_permission(self, request):
        # Disable add through admin - entries should be created through the form
        return False
```

This admin configuration shows how application models and context models work together. The journal entry model stores the reference and application-specific fields. The context model accessed through `entry.as2` provides the federated content. Admin methods retrieve data from the context to display it.

Create a simple form for adding entries. Add to `journal/admin.py`:

```python
from django import forms

class JournalEntryForm(forms.Form):
    user = forms.ModelChoiceField(
        queryset=User.objects.all(),
        required=True
    )
    entry_type = forms.ChoiceField(
        choices=JournalEntry.EntryType.choices,
        required=True
    )
    title = forms.CharField(max_length=200, required=False)
    content = forms.CharField(widget=forms.Textarea, required=True)
    duration_minutes = forms.IntegerField(required=False, min_value=0)

@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    # ... existing configuration ...

    def changelist_view(self, request, extra_context=None):
        if request.method == 'POST':
            form = JournalEntryForm(request.POST)
            if form.is_valid():
                duration = None
                if form.cleaned_data['duration_minutes']:
                    duration = timedelta(minutes=form.cleaned_data['duration_minutes'])

                JournalEntry.create_entry(
                    user=form.cleaned_data['user'],
                    content=form.cleaned_data['content'],
                    entry_type=form.cleaned_data['entry_type'],
                    title=form.cleaned_data['title'] or None,
                    duration=duration,
                )
                self.message_user(request, 'Journal entry created successfully')

        extra_context = extra_context or {}
        extra_context['entry_form'] = JournalEntryForm()
        return super().changelist_view(request, extra_context)
```

Create a template for the admin form at `journal/templates/admin/journal/journalentry/change_list.html`:

```django
{% raw %}
{% extends "admin/change_list.html" %}

{% block content_title %}
<h1>Journal Entries</h1>
<div style="background: #f8f8f8; padding: 20px; margin: 20px 0; border-radius: 5px;">
    <h2>Create New Entry</h2>
    <form method="post">
        {% csrf_token %}
        {{ entry_form.as_p }}
        <button type="submit">Create Entry</button>
    </form>
</div>
{% endblock %}

{% block result_list %}
    {{ block.super }}
{% endblock %}
{% endraw %}
```

Run migrations and create a superuser:

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
```

## Serving ActivityPub Resources

Your application needs views that serve journal entries as JSON-LD when requested by ActivityPub clients. Create `journal/views.py`:

```python
from django.shortcuts import get_object_or_404
from activitypub.views import LinkedDataModelView
from journal.models import JournalEntry

class EntryDetailView(LinkedDataModelView):
    """Serve individual journal entries as ActivityPub objects."""

    def get_object(self):
        # Extract entry ID from URL
        entry_id = self.kwargs.get('pk')
        entry = get_object_or_404(JournalEntry, pk=entry_id)
        return entry.reference
```

The view retrieves the journal entry from your application model, then returns its reference. The toolkit's `LinkedDataModelView` handles serialization automatically. It walks through all context models attached to the reference and merges them into JSON-LD. For journal entries, this includes the `ObjectContext` with content, publication time, and duration.

Configure URLs in `journal/urls.py`:

```python
from django.urls import path
from journal.views import EntryDetailView

app_name = 'journal'

urlpatterns = [
    path('entries/<int:pk>', EntryDetailView.as_view(), name='entry-detail'),
]
```

Include journal URLs in `config/urls.py`:

```python
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('journal.urls')),
]
```

## Testing Federation

Start the development server and create a journal entry through the admin interface:

```bash
python manage.py runserver
```

Visit `http://localhost:8000/admin/`, log in, and create a journal entry using the form. Note the entry's ID from the list view.

Test the ActivityPub endpoint:

```bash
curl -H "Accept: application/activity+json" http://localhost:8000/entries/1
```

You should receive JSON-LD representing your journal entry:

```json
{
  "@context": "https://www.w3.org/ns/activitystreams",
  "id": "http://localhost:8000/entries/1",
  "type": "Note",
  "content": "Went for a 5km run this morning. Weather was perfect.",
  "name": "Morning Run",
  "published": "2025-01-15T08:00:00Z",
  "duration": "PT45M"
}
```

This response demonstrates how your application data transforms into ActivityPub format. The `content` comes from the context model. The `type` indicates this is a Note. The `published` timestamp and `duration` are ISO 8601 formatted. The `name` provides the optional title.

## Understanding the Data Flow

The separation between application models and context models enables flexible federation. Your `JournalEntry` model stores application-specific data like `entry_type`. The `ObjectContext` stores vocabulary-specific data like `content` and `published`. Both point to the same `Reference`.

Check this relationship in the Django shell:

```python
python manage.py shell

from journal.models import JournalEntry
from activitypub.models import ObjectContext

entry = JournalEntry.objects.first()
print(f"Entry reference: {entry.reference.uri}")
print(f"Entry type (app-specific): {entry.entry_type}")

obj_context = entry.as2
print(f"Context reference: {obj_context.reference.uri}")
print(f"Same reference: {entry.reference == obj_context.reference}")
print(f"Content (federated): {obj_context.content}")
print(f"Published (federated): {obj_context.published}")
print(f"Duration (federated): {obj_context.duration}")
```

Both models point to the same reference. The reference has a URI that identifies this resource globally. Any ActivityPub server can fetch this URI and receive the journal entry data. Your application model handles business logic. The context model handles federation. The reference connects them.

## Querying Federated Data

Because context models are Django models, you can query them using the ORM. Find all entries published in the last week:

```python
from datetime import timedelta
from django.utils import timezone
from activitypub.models import ObjectContext

week_ago = timezone.now() - timedelta(days=7)
recent_contexts = ObjectContext.objects.filter(
    published__gte=week_ago,
    reference__journal_entry__isnull=False
)

for ctx in recent_contexts:
    entry = ctx.reference.journal_entry
    print(f"{entry.user.username}: {ctx.content[:50]}")
```

Find entries with duration over 30 minutes:

```python
from datetime import timedelta

long_entries = ObjectContext.objects.filter(
    duration__gt=timedelta(minutes=30),
    reference__journal_entry__isnull=False
)
```

This demonstrates why the toolkit uses context models instead of storing data in JSON blobs. You can filter, sort, and join using SQL. The data lives in relational tables optimized for queries. Federation and database efficiency work together rather than conflicting.

## Working with Remote Data

The reference architecture enables working with entries from other servers. When your application encounters a reference to a remote journal entry, resolve it to fetch the data.

Create a command to fetch and display a remote entry in `journal/management/commands/fetch_entry.py`:

```python
from django.core.management.base import BaseCommand
from activitypub.models import Reference, ObjectContext

class Command(BaseCommand):
    help = 'Fetch and display a remote journal entry'

    def add_arguments(self, parser):
        parser.add_argument('uri', type=str, help='URI of the entry to fetch')

    def handle(self, *args, **options):
        uri = options['uri']

        # Create or get reference
        reference = Reference.make(uri)

        # Resolve if not already cached
        if not reference.is_resolved:
            self.stdout.write(f"Fetching {uri}...")
            reference.resolve()
        else:
            self.stdout.write(f"Using cached data for {uri}")

        # Access the ActivityStreams context
        obj = reference.get_by_context(ObjectContext)
        if obj:
            self.stdout.write(self.style.SUCCESS(f"Type: {obj.type}"))
            self.stdout.write(self.style.SUCCESS(f"Content: {obj.content}"))
            self.stdout.write(self.style.SUCCESS(f"Published: {obj.published}"))
            if obj.duration:
                self.stdout.write(self.style.SUCCESS(f"Duration: {obj.duration}"))
        else:
            self.stdout.write(self.style.ERROR("Could not parse as ActivityStreams object"))
```

This command demonstrates pull-based federation. You have a URI. You create a reference for it. You resolve the reference, which fetches the remote JSON-LD document and populates context models. Then you access the data through the context.

The resolved data lives in your database. Subsequent access queries the context model directly without network requests. Rate limiting prevents excessive refetching. The pattern works identically for local and remote resources—your code doesn't change based on where data originates.

## Next Steps

You have built a federated journal application. The application demonstrates several key concepts:

The reference serves as the primary abstraction. Your application models link to references, not directly to ActivityPub contexts. This separation enables working with both local and remote resources uniformly.

Context models handle vocabulary-specific data. `ObjectContext` stores ActivityStreams properties. Your application model stores business logic fields. The reference connects them.

Federation happens at the HTTP layer. The view serves your entries as JSON-LD. Remote servers fetch these URLs. Your application fetches remote URLs. The toolkit handles the transformation between Django models and Linked Data.

Federated data lives in relational tables. You query using Django's ORM. Filters, joins, and aggregations work normally. The context model pattern provides both federation and database efficiency.

To extend this application, consider:

Adding user profiles with actor contexts so users can follow each other. Creating collections for user timelines showing their entries. Implementing inbox handling to receive responses from remote users. Building a web interface to browse entries and interact with the federation. Adding custom context models for specialized vocabularies like exercise tracking or mood logging.

The tutorial focused on the data layer and federation mechanics. A complete application needs authentication, authorization, and user interface. But the foundation—references linking application models to federated contexts—remains the same regardless of those additional layers.

You have learned the reference-first approach, how to create federated resources, and how to work with both local and remote data. These patterns apply whether building a journal, a photo gallery, a forum, or any other application that participates in the Fediverse.
