---
title: Publishing to the Fediverse
---

This tutorial teaches you how to publish content from your application to the Fediverse. You will learn to create activities, manage collections, implement addressing for delivery, and handle outgoing federation.

By the end of this tutorial, you will understand how to make your journal entries visible to followers, send notifications to remote servers, and participate fully in federated conversations.

## Understanding Outbound Federation

Publishing to the Fediverse involves creating activities that describe actions, adding them to collections that remote servers can fetch, and optionally delivering them directly to recipient inboxes. This tutorial covers both pull-based publishing (via collections) and push-based delivery (via inbox POSTs).

Your application creates content—journal entries, comments, media—and wraps it in ActivityPub activities. A Create activity announces new content. An Update activity announces changes. Activities get added to the author's outbox, making them discoverable to followers.

## Creating Activities

Activities describe actions. When a user publishes a journal entry, create a Create activity that wraps the entry object. Start by updating the journal entry creation to generate activities.

Update `journal/models.py`:

```python
from activitypub.models import ActivityContext, ObjectContext, Reference, Domain
from django.utils import timezone

class JournalEntry(models.Model):
    # ... existing fields ...
    
    @classmethod
    def create_entry(cls, user, content, entry_type=EntryType.PERSONAL,
                     title=None, duration=None):
        """Create a journal entry with its ActivityPub representation and activity."""
        
        # Generate references
        domain = Domain.get_default()
        entry_ref = ObjectContext.generate_reference(domain)
        activity_ref = ActivityContext.generate_reference(domain)
        
        # Get user's actor
        actor_ref = user.profile.actor_reference
        
        # Create the entry object context
        obj_context = ObjectContext.make(
            reference=entry_ref,
            type=ObjectContext.Types.NOTE,
            content=content,
            name=title,
            published=timezone.now(),
            duration=duration,
            attributed_to=actor_ref,
        )
        
        # Create the application entry
        entry = cls.objects.create(
            reference=entry_ref,
            user=user,
            entry_type=entry_type,
        )
        
        # Create the Create activity
        activity = ActivityContext.make(
            reference=activity_ref,
            type=ActivityContext.Types.CREATE,
            actor=actor_ref,
            object=entry_ref,
            published=timezone.now(),
        )
        
        # Add to actor's outbox
        actor_ctx = actor_ref.get_by_context(ActorContext)
        if actor_ctx and actor_ctx.outbox:
            outbox = actor_ctx.outbox.get_by_context(CollectionContext)
            if outbox:
                outbox.append(activity_ref)
        
        return entry
```

This creates three objects: the journal entry (Note), the application model, and the Create activity. The activity goes into the actor's outbox collection, making it available to anyone who fetches that collection.

## Managing Collections

Collections are ordered lists of items. Actors have outboxes (activities they've performed), inboxes (activities received), and potentially followers and following collections. Collections support pagination for efficient traversal.

The `CollectionContext` provides methods for manipulating collections:

```python
from activitypub.models import CollectionContext

# Get an actor's outbox
actor = user.profile.actor
outbox = actor.outbox.get_by_context(CollectionContext)

# Add an item
outbox.append(activity_reference)

# Check if collection contains an item
if outbox.contains(activity_reference):
    print("Activity already in outbox")

# Remove an item
outbox.remove(activity_reference)

# Get items
items = outbox.items.all()  # QuerySet of References
```

Collections automatically maintain ordering. Ordered collections (like outboxes) sort items by creation time in reverse chronological order. Unordered collections maintain insertion order.

## Followers and Following

To enable federation, actors need followers and following collections. Update the `UserProfile` creation to include these:

```python
class UserProfile(models.Model):
    # ... existing fields ...
    
    @classmethod
    def create_for_user(cls, user):
        """Create an actor with all required collections."""
        domain = Domain.get_default()
        actor_ref = ActorContext.generate_reference(domain)
        
        # Create actor context
        actor = ActorContext.make(
            reference=actor_ref,
            type=ActorContext.Types.PERSON,
            preferred_username=user.username,
            name=user.get_full_name() or user.username,
        )
        
        # Create inbox
        inbox_ref = CollectionContext.generate_reference(domain)
        inbox = CollectionContext.make(
            reference=inbox_ref,
            type=CollectionContext.Types.ORDERED_COLLECTION,
        )
        actor.inbox = inbox_ref
        actor.save()
        
        # Create outbox
        outbox_ref = CollectionContext.generate_reference(domain)
        outbox = CollectionContext.make(
            reference=outbox_ref,
            type=CollectionContext.Types.ORDERED_COLLECTION,
        )
        actor.outbox = outbox_ref
        actor.save()
        
        # Create followers collection
        followers_ref = CollectionContext.generate_reference(domain)
        followers = CollectionContext.make(
            reference=followers_ref,
            type=CollectionContext.Types.COLLECTION,
        )
        actor.followers = followers_ref
        actor.save()
        
        # Create following collection
        following_ref = CollectionContext.generate_reference(domain)
        following = CollectionContext.make(
            reference=following_ref,
            type=CollectionContext.Types.COLLECTION,
        )
        actor.following = following_ref
        actor.save()
        
        # Create profile
        profile = cls.objects.create(
            user=user,
            actor_reference=actor_ref
        )
        
        return profile
```

Run migrations to update existing profiles:

```bash
python manage.py makemigrations
python manage.py migrate
```

Create a command to add missing collections to existing profiles:

```python
# journal/management/commands/add_collections.py
from django.core.management.base import BaseCommand
from journal.models import UserProfile
from activitypub.models import ActorContext, CollectionContext, Domain

class Command(BaseCommand):
    help = 'Add missing collections to user profiles'
    
    def handle(self, *args, **options):
        domain = Domain.get_default()
        
        for profile in UserProfile.objects.all():
            actor = profile.actor
            updated = False
            
            if not actor.followers:
                followers_ref = CollectionContext.generate_reference(domain)
                CollectionContext.make(
                    reference=followers_ref,
                    type=CollectionContext.Types.COLLECTION,
                )
                actor.followers = followers_ref
                updated = True
            
            if not actor.following:
                following_ref = CollectionContext.generate_reference(domain)
                CollectionContext.make(
                    reference=following_ref,
                    type=CollectionContext.Types.COLLECTION,
                )
                actor.following = following_ref
                updated = True
            
            if updated:
                actor.save()
                self.stdout.write(
                    self.style.SUCCESS(f'Updated collections for {profile.user.username}')
                )
```

## Accepting Follow Requests

When a remote user sends a Follow activity, it creates a `FollowRequest` (from the previous tutorial). Accepting the follow adds the follower to your followers collection and sends an Accept activity.

Create a method to accept follows in `journal/models.py`:

```python
class FollowRequest(models.Model):
    # ... existing fields ...
    
    def accept(self):
        """Accept this follow request."""
        if self.accepted:
            return  # Already accepted
        
        # Add follower to the followers collection
        actor = self.profile.actor
        followers = actor.followers.get_by_context(CollectionContext)
        if followers:
            followers.append(self.follower_reference)
        
        # Create Accept activity
        domain = Domain.get_default()
        accept_ref = ActivityContext.generate_reference(domain)
        
        accept_activity = ActivityContext.make(
            reference=accept_ref,
            type=ActivityContext.Types.ACCEPT,
            actor=self.profile.actor_reference,
            object=self.activity_reference,
            published=timezone.now(),
        )
        
        # Add to outbox
        outbox = actor.outbox.get_by_context(CollectionContext)
        if outbox:
            outbox.append(accept_ref)
        
        # Mark as accepted
        self.accepted = True
        self.save()
        
        # TODO: Deliver Accept activity to follower's inbox
        
        return accept_activity
```

Create an admin action to accept follow requests:

```python
# journal/admin.py
from django.contrib import admin
from journal.models import FollowRequest

@admin.register(FollowRequest)
class FollowRequestAdmin(admin.ModelAdmin):
    list_display = ('profile', 'get_follower_uri', 'accepted', 'created_at')
    list_filter = ('accepted', 'created_at')
    actions = ['accept_requests']
    
    def get_follower_uri(self, obj):
        return obj.follower_reference.uri
    get_follower_uri.short_description = 'Follower'
    
    def accept_requests(self, request, queryset):
        for follow_request in queryset.filter(accepted=False):
            follow_request.accept()
        self.message_user(request, f'Accepted {queryset.count()} follow requests')
    accept_requests.short_description = 'Accept selected follow requests'
```

## Activity Addressing

Activities include addressing fields that determine who should receive them. The `to` field indicates public delivery. The `cc` field indicates courtesy copies. The `bcc` field indicates private delivery that shouldn't be disclosed.

The special URI `https://www.w3.org/ns/activitystreams#Public` represents public addressing. Activities addressed to Public appear in public timelines.

Update entry creation to include addressing:

```python
from activitypub.schemas import AS2

PUBLIC = 'https://www.w3.org/ns/activitystreams#Public'

class JournalEntry(models.Model):
    # ... existing code ...
    
    @classmethod
    def create_entry(cls, user, content, entry_type=EntryType.PERSONAL,
                     title=None, duration=None, public=True):
        """Create a journal entry with proper addressing."""
        
        # ... existing creation code ...
        
        # Create the Create activity with addressing
        activity = ActivityContext.make(
            reference=activity_ref,
            type=ActivityContext.Types.CREATE,
            actor=actor_ref,
            object=entry_ref,
            published=timezone.now(),
        )
        
        # Set addressing
        if public:
            # Public post: to=Public, cc=followers
            activity.to.add(Reference.make(PUBLIC))
            if actor_ctx.followers:
                activity.cc.add(actor_ctx.followers)
        else:
            # Followers-only post: to=followers
            if actor_ctx.followers:
                activity.to.add(actor_ctx.followers)
        
        activity.save()
        
        # Add to outbox
        # ... existing outbox code ...
        
        return entry
```

The `to` and `cc` fields are many-to-many relationships to references. You can address activities to individual actors, collections, or the Public constant.

## Serving Collections

Collections need to be accessible via HTTP for remote servers to fetch them. Create views that serve user outboxes and follower collections.

Update `journal/views.py`:

```python
from activitypub.views import LinkedDataModelView
from journal.models import UserProfile

class UserOutboxView(LinkedDataModelView):
    """Serve a user's outbox collection."""
    
    def get_object(self):
        username = self.kwargs.get('username')
        profile = get_object_or_404(UserProfile, user__username=username)
        return profile.actor.outbox
    
    # Frame selection is automatic - CollectionFrame will be used

class UserFollowersView(LinkedDataModelView):
    """Serve a user's followers collection."""
    
    def get_object(self):
        username = self.kwargs.get('username')
        profile = get_object_or_404(UserProfile, user__username=username)
        return profile.actor.followers

class UserFollowingView(LinkedDataModelView):
    """Serve a user's following collection."""
    
    def get_object(self):
        username = self.kwargs.get('username')
        profile = get_object_or_404(UserProfile, user__username=username)
        return profile.actor.following
```

Update `journal/urls.py`:

```python
from django.urls import path
from journal.views import (
    EntryDetailView,
    UserInboxView,
    UserOutboxView,
    UserFollowersView,
    UserFollowingView,
)

app_name = 'journal'

urlpatterns = [
    path('entries/<int:pk>', EntryDetailView.as_view(), name='entry-detail'),
    path('users/<str:username>/inbox', UserInboxView.as_view(), name='user-inbox'),
    path('users/<str:username>/outbox', UserOutboxView.as_view(), name='user-outbox'),
    path('users/<str:username>/followers', UserFollowersView.as_view(), name='user-followers'),
    path('users/<str:username>/following', UserFollowingView.as_view(), name='user-following'),
]
```

Now remote servers can fetch user outboxes to discover activities and check follower lists to verify relationships.

## Actor Views

Actors need to be served as JSON-LD so remote servers can discover inbox URLs, public keys, and collection endpoints. Create an actor view:

```python
class UserActorView(LinkedDataModelView):
    """Serve a user's actor document."""
    
    def get_object(self):
        username = self.kwargs.get('username')
        profile = get_object_or_404(UserProfile, user__username=username)
        return profile.actor_reference
```

Add to URLs:

```python
urlpatterns = [
    # ... existing patterns ...
    path('users/<str:username>', UserActorView.as_view(), name='user-actor'),
]
```

Update settings to configure view names:

```python
FEDERATION = {
    'DEFAULT_URL': 'http://localhost:8000',
    'SOFTWARE_NAME': 'FedJournal',
    'SOFTWARE_VERSION': '0.1.0',
    'ACTOR_VIEW': 'journal:user-actor',
    'OBJECT_VIEW': 'journal:entry-detail',
    'COLLECTION_VIEW': 'journal:user-outbox',  # Generic collection view
}
```

## WebFinger Discovery

Remote servers discover actors using WebFinger. When someone searches for `user@localhost:8000`, their server queries `/.well-known/webfinger?resource=acct:user@localhost:8000`. The response provides the actor's ActivityPub URL.

Create a WebFinger view:

```python
from django.http import JsonResponse
from django.views import View
from django.urls import reverse
from journal.models import UserProfile

class WebFingerView(View):
    """Handle WebFinger requests for user discovery."""
    
    def get(self, request):
        resource = request.GET.get('resource', '')
        
        # Parse acct: URI
        if not resource.startswith('acct:'):
            return JsonResponse({'error': 'Invalid resource'}, status=400)
        
        acct = resource[5:]  # Remove 'acct:' prefix
        
        try:
            username, domain = acct.split('@')
        except ValueError:
            return JsonResponse({'error': 'Invalid account format'}, status=400)
        
        # Find user
        try:
            profile = UserProfile.objects.get(user__username=username)
        except UserProfile.DoesNotExist:
            return JsonResponse({'error': 'User not found'}, status=404)
        
        # Build actor URL
        actor_url = request.build_absolute_uri(
            reverse('journal:user-actor', kwargs={'username': username})
        )
        
        # Return WebFinger response
        return JsonResponse({
            'subject': resource,
            'aliases': [actor_url],
            'links': [
                {
                    'rel': 'self',
                    'type': 'application/activity+json',
                    'href': actor_url,
                },
            ],
        })
```

Add to root URLs in `config/urls.py`:

```python
from django.urls import path, include
from journal.views import WebFingerView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('.well-known/webfinger', WebFingerView.as_view(), name='webfinger'),
    path('', include('journal.urls')),
]
```

Now remote servers can discover your users by their `username@domain` addresses.

## Push Delivery (Optional)

The toolkit supports pull-based federation through collections. Remote servers fetch your outbox to discover new activities. For real-time delivery, you can implement push delivery by POSTing activities to follower inboxes.

This requires:

1. Resolving follower references to get their inbox URLs
2. Signing HTTP requests with your actor's keypair
3. POSTing the activity JSON to each inbox
4. Handling delivery failures and retries

The toolkit provides infrastructure for this, but implementing full push delivery is beyond this tutorial's scope. Most applications start with pull-based federation and add push delivery later for improved responsiveness.

## Testing Federation

Test your outbound federation by creating a journal entry and checking the outbox:

```bash
python manage.py shell

from django.contrib.auth.models import User
from journal.models import JournalEntry

user = User.objects.first()
entry = JournalEntry.create_entry(
    user=user,
    content="Testing federation!",
    title="Test Entry",
    public=True
)

# Check the outbox
actor = user.profile.actor
outbox = actor.outbox.get_by_context(CollectionContext)
items = outbox.items.all()
for item in items:
    print(f"Activity: {item.item.uri}")
```

Fetch the outbox via HTTP:

```bash
curl -H "Accept: application/activity+json" http://localhost:8000/users/youruser/outbox
```

You should see a collection containing Create activities for your journal entries.

Test actor discovery:

```bash
curl -H "Accept: application/activity+json" http://localhost:8000/users/youruser
```

The actor document includes inbox, outbox, followers, and following URLs.

Test WebFinger:

```bash
curl "http://localhost:8000/.well-known/webfinger?resource=acct:youruser@localhost:8000"
```

The response provides the actor URL for ActivityPub discovery.

## Summary

You have implemented outbound federation for your journal application. Users create journal entries that generate Create activities. Activities go into outboxes where followers can discover them. Actors have followers and following collections that track relationships. WebFinger enables user discovery across servers.

Your application now fully participates in the Fediverse. It receives activities via inboxes (previous tutorial) and publishes activities via outboxes (this tutorial). Remote users can follow your users, see their journal entries, and interact with them through likes and replies.

The reference-first architecture remains central. Activities reference objects. Collections contain references to activities. Actors reference collections. Everything connects through references that work uniformly for local and remote resources.

You have completed the tutorial series. You can now build full-featured ActivityPub applications using Django ActivityPub Toolkit, extending it with custom vocabularies, handling complex activity patterns, and integrating deeply with the federated social web.
