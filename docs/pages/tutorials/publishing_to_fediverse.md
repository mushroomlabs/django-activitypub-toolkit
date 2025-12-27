---
title: Publishing to the Fediverse
---

This tutorial teaches you how to publish content from your application to the Fediverse by creating activities and delivering them to follower inboxes. You will learn to create objects and activities, address them properly, and use the notification system to deliver activities to remote servers.

By the end of this tutorial, you will understand the complete publishing workflow: creating content objects, wrapping them in activities, and delivering those activities to all followers' inboxes using HTTP-signed requests.

## Understanding Publishing

Publishing to the Fediverse means creating ActivityPub activities and delivering them to remote inboxes. When a user creates a journal entry, you generate a Create activity and send it to everyone who follows that user. When they update content, you send an Update activity. When they delete something, you send a Delete activity.

The publishing workflow has three main steps:

1. **Create the content object** - An ObjectContext representing the actual content (a Note, Article, Image, etc.)
2. **Create the activity** - An ActivityContext that wraps the object and describes what happened (Create, Update, Delete, etc.)
3. **Deliver to followers** - Iterate through follower inboxes and create Notification records that trigger HTTP delivery

The toolkit handles the HTTP delivery automatically. You create the activities and notifications, and the `send_notification` task handles signing requests and POSTing to remote servers.

## Prerequisites

This tutorial assumes you have completed the previous tutorial on handling incoming activities. You should have actors with inboxes and outboxes already set up, and the catch-all URL pattern configured.

## Creating Content Objects

Start by creating an ObjectContext that represents your content. For a journal application, this might be a Note or Article. The object includes the content itself, attribution, and timestamps.

Update your journal entry creation to include ActivityPub objects. In `journal/models.py`:

```python
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from activitypub.models import (
    ObjectContext,
    ActivityContext,
    CollectionContext,
    Reference,
    Domain,
)

class JournalEntry(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    reference = models.OneToOneField(
        Reference,
        on_delete=models.CASCADE,
        related_name='journal_entry'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    @classmethod
    def create_entry(cls, user, content, title=None):
        """Create a journal entry with its ActivityPub representation."""
        
        domain = Domain.get_default()
        
        # Create the object reference
        entry_ref = ObjectContext.generate_reference(domain)
        
        # Get the user's actor
        actor_ref = user.profile.actor_reference
        
        # Create the object context
        obj = ObjectContext.make(
            reference=entry_ref,
            type=ObjectContext.Types.NOTE,
            content=content,
            name=title,
            published=timezone.now(),
            attributed_to=actor_ref,
        )
        
        # Create the application model
        entry = cls.objects.create(
            user=user,
            reference=entry_ref,
        )
        
        return entry
```

The `ObjectContext.make()` method creates the object and automatically generates collections for replies, likes, and shares through Django signals. You do not need to create these collections manually.

Run migrations to add the reference field:

```bash
python manage.py makemigrations
python manage.py migrate
```

## Creating Activities

Activities describe what happened to objects. A Create activity announces new content. An Update activity announces changes. A Delete activity announces removal.

Extend the entry creation to include a Create activity:

```python
@classmethod
def create_entry(cls, user, content, title=None):
    """Create a journal entry with its ActivityPub representation and activity."""
    
    domain = Domain.get_default()
    
    # Create the object reference
    entry_ref = ObjectContext.generate_reference(domain)
    
    # Get the user's actor
    actor_ref = user.profile.actor_reference
    
    # Create the object context
    obj = ObjectContext.make(
        reference=entry_ref,
        type=ObjectContext.Types.NOTE,
        content=content,
        name=title,
        published=timezone.now(),
        attributed_to=actor_ref,
    )
    
    # Create the application model
    entry = cls.objects.create(
        user=user,
        reference=entry_ref,
    )
    
    # Create the Create activity
    activity_ref = ActivityContext.generate_reference(domain)
    activity = ActivityContext.make(
        reference=activity_ref,
        type=ActivityContext.Types.CREATE,
        actor=actor_ref,
        object=entry_ref,
        published=timezone.now(),
    )
    
    return entry, activity
```

The activity has three critical fields:

- `actor` - Who performed the action (the user's actor reference)
- `object` - What was acted upon (the entry reference)
- `type` - What kind of action occurred (CREATE)

## Adding to Outbox

Activities should be added to the actor's outbox collection. This makes them discoverable through the outbox endpoint and provides a record of what the actor has published.

```python
from activitypub.models import ActorContext

@classmethod
def create_entry(cls, user, content, title=None):
    """Create a journal entry with activity and add to outbox."""
    
    domain = Domain.get_default()
    entry_ref = ObjectContext.generate_reference(domain)
    actor_ref = user.profile.actor_reference
    
    # Create object
    obj = ObjectContext.make(
        reference=entry_ref,
        type=ObjectContext.Types.NOTE,
        content=content,
        name=title,
        published=timezone.now(),
        attributed_to=actor_ref,
    )
    
    # Create entry
    entry = cls.objects.create(
        user=user,
        reference=entry_ref,
    )
    
    # Create activity
    activity_ref = ActivityContext.generate_reference(domain)
    activity = ActivityContext.make(
        reference=activity_ref,
        type=ActivityContext.Types.CREATE,
        actor=actor_ref,
        object=entry_ref,
        published=timezone.now(),
    )
    
    # Add to outbox
    actor = actor_ref.get_by_context(ActorContext)
    if actor and actor.outbox:
        outbox = actor.outbox.get_by_context(CollectionContext)
        if outbox:
            outbox.append(activity_ref)
    
    return entry, activity
```

The outbox collection maintains a reverse-chronological list of activities the actor has performed. Remote servers can fetch this collection to discover the actor's history.

## Activity Addressing

Activities include addressing fields that determine who should receive them. The `to` field indicates primary recipients. The `cc` field indicates courtesy copy recipients. The `bcc` field indicates blind copy recipients whose addresses are not disclosed.

The special URI `https://www.w3.org/ns/activitystreams#Public` represents public addressing. Activities addressed to Public appear in public timelines and are visible to anyone.

Add addressing to your activities:

```python
from activitypub.schemas import AS2
from activitypub.models import ActorContext

@classmethod
def create_entry(cls, user, content, title=None, public=True):
    """Create a journal entry with proper addressing."""
    
    domain = Domain.get_default()
    entry_ref = ObjectContext.generate_reference(domain)
    actor_ref = user.profile.actor_reference
    
    # Create object
    obj = ObjectContext.make(
        reference=entry_ref,
        type=ObjectContext.Types.NOTE,
        content=content,
        name=title,
        published=timezone.now(),
        attributed_to=actor_ref,
    )
    
    # Create entry
    entry = cls.objects.create(
        user=user,
        reference=entry_ref,
    )
    
    # Create activity
    activity_ref = ActivityContext.generate_reference(domain)
    activity = ActivityContext.make(
        reference=activity_ref,
        type=ActivityContext.Types.CREATE,
        actor=actor_ref,
        object=entry_ref,
        published=timezone.now(),
    )
    
    # Set addressing
    actor = actor_ref.get_by_context(ActorContext)
    
    if public:
        # Public post: to=Public, cc=followers
        activity.to.add(Reference.make(str(AS2.Public)))
        if actor and actor.followers:
            activity.cc.add(actor.followers)
    else:
        # Followers-only post: to=followers
        if actor and actor.followers:
            activity.to.add(actor.followers)
    
    activity.save()
    
    # Add to outbox
    if actor and actor.outbox:
        outbox = actor.outbox.get_by_context(CollectionContext)
        if outbox:
            outbox.append(activity_ref)
    
    return entry, activity
```

The addressing fields are many-to-many relationships. You can address activities to individual actors, collections, or the Public constant. For public posts, you typically set `to=Public` and `cc=followers`. For followers-only posts, you set `to=followers`.

## Delivering to Followers

The core of publishing is delivering activities to follower inboxes. The toolkit provides the `followers_inboxes` property on Actor, which returns a queryset of inbox References for all followers. For each inbox, you create a Notification that triggers HTTP delivery.

Add delivery to your entry creation:

```python
from activitypub.models import Notification, Actor
from activitypub.tasks import send_notification

@classmethod
def create_entry(cls, user, content, title=None, public=True):
    """Create and publish a journal entry to followers."""
    
    domain = Domain.get_default()
    entry_ref = ObjectContext.generate_reference(domain)
    actor_ref = user.profile.actor_reference
    
    # Create object
    obj = ObjectContext.make(
        reference=entry_ref,
        type=ObjectContext.Types.NOTE,
        content=content,
        name=title,
        published=timezone.now(),
        attributed_to=actor_ref,
    )
    
    # Create entry
    entry = cls.objects.create(
        user=user,
        reference=entry_ref,
    )
    
    # Create activity
    activity_ref = ActivityContext.generate_reference(domain)
    activity = ActivityContext.make(
        reference=activity_ref,
        type=ActivityContext.Types.CREATE,
        actor=actor_ref,
        object=entry_ref,
        published=timezone.now(),
    )
    
    # Set addressing
    actor = actor_ref.get_by_context(Actor)
    
    if public:
        activity.to.add(Reference.make(str(AS2.Public)))
        if actor and actor.followers:
            activity.cc.add(actor.followers)
    else:
        if actor and actor.followers:
            activity.to.add(actor.followers)
    
    activity.save()
    
    # Add to outbox
    if actor and actor.outbox:
        outbox = actor.outbox.get_by_context(CollectionContext)
        if outbox:
            outbox.append(activity_ref)
    
    # Deliver to followers
    if actor:
        for inbox_ref in actor.followers_inboxes:
            notification = Notification.objects.create(
                resource=activity_ref,
                sender=actor_ref,
                target=inbox_ref,
            )
            send_notification.delay(notification_id=str(notification.id))
    
    return entry, activity
```

The `followers_inboxes` property returns inbox References for all followers. It prefers shared inboxes when available, reducing the number of HTTP requests needed. For each inbox, you create a Notification with:

- `resource` - The activity reference being delivered
- `sender` - The actor reference sending the activity
- `target` - The inbox reference receiving the activity

The `send_notification` task handles the actual HTTP delivery. It serializes the activity to JSON-LD, signs the request using the sender's keypair, and POSTs to the inbox URL. The task runs asynchronously through Celery.

!!! info "Follow Request Handling"
    Before you can deliver activities to followers, users need to follow your actors. When a remote user sends a Follow activity to your inbox, the toolkit automatically creates a `FollowRequest` record. The toolkit handles Follow acceptance automatically based on the actor's `manually_approves_followers` setting. If set to `False` (the default), Follow requests are accepted automatically. Once accepted, the follower is added to the actor's followers collection, and their inbox will receive future activities via `actor.followers_inboxes`.

## Testing Publication

Test the complete publishing workflow by creating an entry and verifying delivery:

```bash
python manage.py shell
```

```python
from django.contrib.auth.models import User
from journal.models import JournalEntry

user = User.objects.first()
entry, activity = JournalEntry.create_entry(
    user=user,
    content="Testing federation!",
    title="Test Entry",
    public=True
)

print(f"Created entry: {entry.reference.uri}")
print(f"Created activity: {activity.reference.uri}")

# Check outbox
from activitypub.models import CollectionContext
actor = user.profile.actor
outbox = actor.outbox.get_by_context(CollectionContext)
print(f"Outbox has {outbox.total_items} items")

# Check notifications
from activitypub.models import Notification
notifications = Notification.objects.filter(resource=activity.reference)
print(f"Created {notifications.count()} notifications")
```

If the user has followers, you should see notifications created for each follower's inbox. The `send_notification` task runs asynchronously, so check the Celery logs to verify delivery:

```bash
celery -A project worker --loglevel=info
```

You should see log entries showing the HTTP POST requests to follower inboxes.

## Updating Content

When content changes, send an Update activity. Add an update method to your model:

```python
from activitypub.models import ObjectContext, ActivityContext, Actor
from activitypub.schemas import AS2

def update_content(self, content, title=None):
    """Update the entry and send Update activity to followers."""
    
    # Update the object
    obj = self.reference.get_by_context(ObjectContext)
    obj.content = content
    if title is not None:
        obj.name = title
    obj.updated = timezone.now()
    obj.save()
    
    # Create Update activity
    domain = Domain.get_default()
    activity_ref = ActivityContext.generate_reference(domain)
    actor_ref = self.user.profile.actor_reference
    
    activity = ActivityContext.make(
        reference=activity_ref,
        type=ActivityContext.Types.UPDATE,
        actor=actor_ref,
        object=self.reference,
        published=timezone.now(),
    )
    
    # Set addressing
    actor = actor_ref.get_by_context(Actor)
    activity.to.add(Reference.make(str(AS2.Public)))
    if actor and actor.followers:
        activity.cc.add(actor.followers)
    activity.save()
    
    # Add to outbox
    if actor and actor.outbox:
        outbox = actor.outbox.get_by_context(CollectionContext)
        if outbox:
            outbox.append(activity_ref)
    
    # Deliver to followers
    if actor:
        for inbox_ref in actor.followers_inboxes:
            notification = Notification.objects.create(
                resource=activity_ref,
                sender=actor_ref,
                target=inbox_ref,
            )
            send_notification.delay(notification_id=str(notification.id))
```

The Update activity uses the same delivery pattern as Create. The `object` field references the updated object, and the activity is delivered to all followers.

## Deleting Content

When content is deleted, send a Delete activity. Add a delete method:

```python
from activitypub.models import ObjectContext, ActivityContext, Actor
from activitypub.schemas import AS2

def delete_entry(self):
    """Delete the entry and send Delete activity to followers."""
    
    # Create Delete activity before deleting the object
    domain = Domain.get_default()
    activity_ref = ActivityContext.generate_reference(domain)
    actor_ref = self.user.profile.actor_reference
    
    activity = ActivityContext.make(
        reference=activity_ref,
        type=ActivityContext.Types.DELETE,
        actor=actor_ref,
        object=self.reference,
        published=timezone.now(),
    )
    
    # Set addressing
    actor = actor_ref.get_by_context(Actor)
    activity.to.add(Reference.make(str(AS2.Public)))
    if actor and actor.followers:
        activity.cc.add(actor.followers)
    activity.save()
    
    # Add to outbox
    if actor and actor.outbox:
        outbox = actor.outbox.get_by_context(CollectionContext)
        if outbox:
            outbox.append(activity_ref)
    
    # Deliver to followers
    if actor:
        for inbox_ref in actor.followers_inboxes:
            notification = Notification.objects.create(
                resource=activity_ref,
                sender=actor_ref,
                target=inbox_ref,
            )
            send_notification.delay(notification_id=str(notification.id))
    
    # Delete the entry and object
    self.reference.delete()
    self.delete()
```

The Delete activity is sent before the object is removed. Remote servers receive the activity and can remove their cached copies of the content.

## Understanding Projections

When remote servers fetch your actors, objects, or activities, the toolkit uses **projections** to control what data appears in the JSON-LD response. Projections provide a declarative way to specify which fields to include, which to omit, and which related objects to embed.

Projections separate presentation logic from data storage. Context models store all available data. Projections determine what subset of that data gets exposed to external viewers, and how it gets formatted.

### The ReferenceProjection Base Class

All projections inherit from `ReferenceProjection`. This base class handles the standard workflow:

1. Find all context models attached to a reference
2. Build an expanded JSON-LD document with all fields as full predicate URIs
3. Apply field filtering, embedding, and omission rules from `Meta`
4. Compact the document using appropriate `@context` definitions

The default projection includes all fields from all context models and outputs references as `{"@id": "uri"}` without embedding. This is appropriate for most scenarios.

### Creating Custom Projections

Create custom projections when you need to control output differently for specific object types. For example, an `ActorProjection` embeds the public key, while a `CollectionProjection` includes total item counts.

Define a projection in `journal/projections.py`:

```python
from activitypub.projections import ReferenceProjection
from activitypub.contexts import AS2
from journal.mood_context import MoodContext

class JournalEntryProjection(ReferenceProjection):
    class Meta:
        # Omit some fields to keep responses compact
        omit = (
            AS2.bcc,  # Never expose blind copy recipients
            AS2.bto,  # Never expose blind copy recipients
        )
```

The `Meta` class supports several options for controlling output:

- **`fields`** - Allowlist of predicates to include (mutually exclusive with `omit`)
- **`omit`** - Denylist of predicates to exclude
- **`embed`** - Predicates whose references should be embedded using the same projection class
- **`overrides`** - Dict mapping predicates to specific projection classes for embedding
- **`extra`** - Dict mapping method names to predicates for computed fields

### Embedding Related Objects

By default, related references appear as `{"@id": "uri"}`. Use `embed` or `overrides` to include the full object inline.

```python
from activitypub.projections import ReferenceProjection, CollectionWithTotalProjection
from activitypub.contexts import AS2

class NoteProjection(ReferenceProjection):
    class Meta:
        overrides = {
            AS2.replies: CollectionWithTotalProjection,  # Embed replies with count
            AS2.likes: CollectionWithTotalProjection,    # Embed likes with count
            AS2.shares: CollectionWithTotalProjection,   # Embed shares with count
        }
```

When a remote server fetches a Note with this projection, the replies, likes, and shares collections are embedded with their total counts rather than just appearing as URIs.

The `embed` option uses the same projection class for embedding:

```python
class QuestionProjection(ReferenceProjection):
    class Meta:
        embed = (AS2.oneOf, AS2.anyOf)  # Embed poll options
```

This embeds the poll choices directly in the Question object, so viewers see the options without making additional HTTP requests.

### Adding Computed Fields

Use the `extra` Meta option to add fields computed at serialization time. Define a method on your projection class and map it to a predicate:

```python
from activitypub.contexts import AS2, SEC_V1_CONTEXT, SECv1
from activitypub.projections import ReferenceProjection, PublicKeyProjection, use_context
from activitypub.models import Reference

class ActorProjection(ReferenceProjection):
    @use_context(SEC_V1_CONTEXT.url)
    def get_public_key(self):
        """Embed the actor's public key for signature verification."""
        references = Reference.objects.filter(
            activitypub_secv1context_context__owner=self.reference
        )
        projections = [PublicKeyProjection(reference=ref, parent=self) for ref in references]
        return [p.get_expanded() for p in projections]
    
    class Meta:
        extra = {"get_public_key": SECv1.publicKey}
```

The `@use_context` decorator registers that this field requires the Security v1 context. The toolkit automatically includes it in the `@context` array when compacting.

The method receives `self` with access to `self.reference` (the Reference being projected) and `self.scope` (viewer and request context). Return data in expanded JSON-LD format (dicts with `@id`, `@value`, `@type` keys).

### Access Control with scope

Projections receive a `scope` dict containing viewer information and the HTTP request. Use this to conditionally include fields based on who's viewing:

```python
class JournalEntryProjection(ReferenceProjection):
    def get_private_notes(self):
        """Only show private notes to the author."""
        viewer = self.scope.get('viewer')
        obj = self.reference.get_by_context(ObjectContext)
        
        # Check if viewer is the author
        if obj and obj.attributed_to.all():
            author = obj.attributed_to.first()
            if viewer and viewer.uri == author.uri:
                mood = self.reference.get_by_context(MoodContext)
                if mood and mood.mood_notes:
                    return [{"@value": mood.mood_notes}]
        
        return None  # Omit field if not authorized
    
    class Meta:
        extra = {"get_private_notes": MOOD.notes}
```

Return `None` to omit the field from output. The field won't appear in the JSON-LD document at all for unauthorized viewers.

### Field-Level Access Control

Context models can also implement `show_<field>()` methods that control visibility:

```python
class MoodContext(AbstractContextModel):
    # ... field definitions ...
    
    def show_mood_notes(self, scope):
        """Only show mood notes to the entry author."""
        viewer = scope.get('viewer')
        obj = self.reference.get_by_context(ObjectContext)
        
        if obj and obj.attributed_to.all():
            author = obj.attributed_to.first()
            return viewer and viewer.uri == author.uri
        
        return False
```

The projection automatically checks for `show_<field>` methods when building output. If the method returns `False`, that field is omitted.

### Using Projections in Views

The `LinkedDataModelView` base class uses projections to render responses. Override `get_projection_class()` to select which projection to use:

```python
from activitypub.views import LinkedDataModelView
from journal.projections import JournalEntryProjection
from journal.models import JournalEntry

class JournalEntryView(LinkedDataModelView):
    def get_projection_class(self, reference):
        """Use custom projection for journal entries."""
        if hasattr(reference, 'journal_entry'):
            return JournalEntryProjection
        
        return super().get_projection_class(reference)
```

The `ActivityPubObjectDetailView` in the toolkit already implements smart projection selection based on context type (actors get `ActorProjection`, collections get collection projections, etc.). You can subclass it and override `get_projection_class()` for application-specific types.

### Built-in Projections

The toolkit provides several projection classes for common ActivityPub patterns:

**`ReferenceProjection`** - Base class, includes all fields, no embedding

**`ActorProjection`** - Embeds public keys for signature verification

**`CollectionProjection`** - Includes items and total count

**`CollectionPageProjection`** - Includes items for a specific page

**`CollectionWithFirstPageProjection`** - Embeds the first page while omitting items

**`CollectionWithTotalProjection`** - Shows only the total count, omits items

**`QuestionProjection`** - Embeds poll choices (oneOf/anyOf)

**`NoteProjection`** - Overrides for replies, likes, and shares collections

**`PublicKeyProjection`** - Minimal projection for embedded public keys

Use these as-is or extend them for application-specific behavior.

### Projection Workflow Example

When a remote server requests `GET https://yourserver.com/entries/123`, here's what happens:

1. `LinkedDataModelView.get()` retrieves the Reference for that URI
2. `get_projection_class(reference)` selects `JournalEntryProjection`
3. The projection's `build()` method:
   - Finds all context models (ObjectContext, MoodContext, etc.)
   - Builds expanded JSON-LD with all predicates as full URIs
   - Applies Meta rules (omit, embed, overrides)
   - Calls extra field methods (e.g., `get_private_notes()`)
   - Checks `show_<field>()` methods for access control
4. `get_compacted()` compacts the document using registered contexts
5. The view returns the compacted JSON-LD in the response

### Testing Projections

Test projections in the Django shell:

```python
from activitypub.models import Reference
from journal.projections import JournalEntryProjection

# Get a reference
ref = Reference.objects.get(uri='http://localhost:8000/entries/1')

# Create projection with viewer context
projection = JournalEntryProjection(
    reference=ref,
    scope={'viewer': None, 'request': None}
)

# Build and get expanded form
projection.build()
expanded = projection.get_expanded()
print(expanded)

# Get compacted form
compacted = projection.get_compacted()
print(compacted)
```

Check that omitted fields don't appear, embedded objects are included, and access control works correctly for different viewers.

### When to Create Custom Projections

Create custom projections when:

- You need to omit sensitive fields (like BCC recipients)
- You want to embed related objects to reduce HTTP requests
- You have computed fields that depend on multiple context models
- You need viewer-specific access control
- You're optimizing for bandwidth (omitting verbose fields)

Use the default `ReferenceProjection` when the automatic behavior (include all fields, don't embed) is sufficient.

### Projections vs. Context Models

Context models store data extracted from incoming JSON-LD. Projections present data when serving JSON-LD. The separation means you can:

- Store comprehensive data from remote servers (all fields)
- Present optimized data to remote servers (selected fields)
- Add computed fields without modifying storage models
- Implement viewer-specific access control at presentation time

This architecture keeps data storage concerns separate from API presentation concerns.

## Understanding HTTP Signatures

The `send_notification` task signs HTTP requests using the sender's keypair. The toolkit automatically creates a keypair for each actor when the actor is created. The public key is embedded in the actor document, and the private key is stored in the `SecV1Context` model.

When sending a notification, the task:

1. Serializes the activity to JSON-LD
2. Retrieves the sender's private key
3. Creates an HTTP signature header using the private key
4. POSTs the activity to the inbox with the signature

Remote servers verify the signature using the public key from the actor document. This proves the activity came from the claimed sender and hasn't been tampered with.

You do not need to implement signature generation yourself. The toolkit handles it automatically through the `send_notification` task.

## Handling Delivery Failures

Not all deliveries succeed. Remote servers might be offline, reject the activity, or return errors. The toolkit records delivery results in `NotificationProcessResult`.

Check delivery results:

```python
from activitypub.models import Notification, NotificationProcessResult

notification = Notification.objects.first()
results = notification.results.all()

for result in results:
    print(f"Result: {result.result}")
    if result.message:
        print(f"Message: {result.message}")
```

Failed deliveries remain in the database with their error status. You can implement retry logic if appropriate, but most applications simply log failures and move on. Temporary failures (like network timeouts) might succeed on retry, but permanent failures (like 404 Not Found) will not.

## Summary

You have learned how to publish content to the Fediverse by creating activities and delivering them to follower inboxes. The publishing workflow involves creating ObjectContext records for content, wrapping them in ActivityContext records that describe what happened, and creating Notification records that trigger HTTP delivery to follower inboxes.

The toolkit handles the HTTP delivery automatically. You create the activities with proper addressing, iterate through `actor.followers_inboxes` to get inbox References, and create Notification records for each inbox. The `send_notification` task signs the requests and POSTs them to remote servers.

This architecture separates content creation from delivery mechanics. You focus on creating activities with the right structure and addressing. The toolkit handles protocol details like HTTP signatures, JSON-LD serialization, and retry logic.

Your application now fully participates in the Fediverse. It receives activities through inboxes (previous tutorial) and publishes activities through outboxes (this tutorial). Users can follow your actors, receive updates when content is published, and interact with your content through likes, shares, and replies.
