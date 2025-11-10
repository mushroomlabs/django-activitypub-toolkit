---
title: Building a Generic ActivityPub Server
---

This tutorial teaches you to build a generic ActivityPub server that implements both Server-to-Server (S2S) and Client-to-Server (C2S) protocols. Unlike domain-specific applications, this server accepts any ActivityStreams object type and works with any ActivityPub client.

By the end of this tutorial, you will have a complete ActivityPub implementation supporting actor management, outbox posting, inbox delivery, collections, and client authentication.

## Understanding Generic Servers

A generic ActivityPub server provides protocol-level functionality without imposing domain-specific constraints. Clients can create Notes, Articles, Events, or any other ActivityStreams type. The server stores, federates, and serves these objects without understanding their semantic meaning.

This approach enables the vision of multiple clients sharing a common social graph. A microblogging client, photo gallery client, and event calendar client can all use the same server, each presenting different views of the same underlying data.

The toolkit's architecture makes this natural. Context models handle ActivityStreams vocabulary. No application-specific models are required. The server acts as a pure protocol implementation.

## Project Setup

Create a new Django project for the generic server:

```bash
mkdir apserver
cd apserver
python -m venv venv
source venv/bin/activate

pip install django django-activitypub-toolkit djangorestframework django-oauth-toolkit
django-admin startproject config .
python manage.py startapp actors
```

Configure `config/settings.py`:

```python
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'oauth2_provider',
    'activitypub',
    'actors',
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'oauth2_provider.contrib.rest_framework.OAuth2Authentication',
    ],
}

OAUTH2_PROVIDER = {
    'SCOPES': {
        'read': 'Read access',
        'write': 'Write access',
        'follow': 'Follow and unfollow users',
    }
}

FEDERATION = {
    'DEFAULT_URL': 'http://localhost:8000',
    'SOFTWARE_NAME': 'GenericAP',
    'SOFTWARE_VERSION': '1.0.0',
}
```

Run initial migrations:

```bash
python manage.py migrate
```

## Actor Management

Users manage actors. A single user can control multiple actors, useful for clients supporting multiple accounts. Create the model in `actors/models.py`:

```python
from django.db import models
from django.contrib.auth.models import User
from activitypub.models import Reference, ActorContext, CollectionContext, Domain, SecV1Context

class ManagedActor(models.Model):
    """Links Django users to actors they control."""
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='managed_actors')
    actor_reference = models.OneToOneField(
        Reference,
        on_delete=models.CASCADE,
        related_name='managed_by'
    )
    display_name = models.CharField(max_length=100, help_text="Friendly name for this actor")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['user', 'actor_reference']
    
    def __str__(self):
        return f"{self.user.username} manages {self.display_name}"
    
    @property
    def actor(self):
        """Access the actor context."""
        return self.actor_reference.get_by_context(ActorContext)
    
    @classmethod
    def create_actor(cls, user, preferred_username, display_name, actor_type='Person'):
        """Create a new actor with all required collections."""
        domain = Domain.get_default()
        actor_ref = ActorContext.generate_reference(domain)
        
        # Map actor type string to enum
        type_mapping = {
            'Person': ActorContext.Types.PERSON,
            'Service': ActorContext.Types.SERVICE,
            'Application': ActorContext.Types.APPLICATION,
            'Group': ActorContext.Types.GROUP,
            'Organization': ActorContext.Types.ORGANIZATION,
        }
        actor_type_enum = type_mapping.get(actor_type, ActorContext.Types.PERSON)
        
        # Create actor
        actor = ActorContext.make(
            reference=actor_ref,
            type=actor_type_enum,
            preferred_username=preferred_username,
            name=display_name,
        )
        
        # Generate keypair for signing
        SecV1Context.generate_keypair(owner=actor_ref)
        
        # Create collections
        for collection_name in ['inbox', 'outbox', 'followers', 'following']:
            coll_ref = CollectionContext.generate_reference(domain)
            coll = CollectionContext.make(
                reference=coll_ref,
                type=CollectionContext.Types.ORDERED_COLLECTION,
            )
            setattr(actor, collection_name, coll_ref)
        
        actor.save()
        
        # Create management record
        managed = cls.objects.create(
            user=user,
            actor_reference=actor_ref,
            display_name=display_name
        )
        
        return managed
```

Run migrations:

```bash
python manage.py makemigrations
python manage.py migrate
```

## OAuth Authentication Setup

OAuth enables clients to authenticate on behalf of users. Configure OAuth in `config/urls.py`:

```python
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('o/', include('oauth2_provider.urls', namespace='oauth2_provider')),
    path('', include('actors.urls')),
]
```

Create a superuser and OAuth application:

```bash
python manage.py createsuperuser
python manage.py runserver
```

Visit `http://localhost:8000/admin/` and create an OAuth application:

1. Navigate to OAuth2 Provider → Applications
2. Click "Add Application"
3. Select your user
4. Client type: "Confidential"
5. Authorization grant type: "Resource owner password-based"
6. Name: "Test Client"
7. Save and note the Client ID and Client Secret

## Actor Creation API

Clients need an API to create and list actors. Create `actors/views.py`:

```python
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from actors.models import ManagedActor
from activitypub.models import ActorContext

class ActorListCreateView(APIView):
    """List and create actors for the authenticated user."""
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """List actors managed by this user."""
        actors = ManagedActor.objects.filter(user=request.user)
        
        data = []
        for managed in actors:
            actor = managed.actor
            data.append({
                'id': managed.id,
                'actor_uri': actor.reference.uri,
                'preferred_username': actor.preferred_username,
                'display_name': managed.display_name,
                'type': actor.get_type_display(),
                'inbox': actor.inbox.uri if actor.inbox else None,
                'outbox': actor.outbox.uri if actor.outbox else None,
            })
        
        return Response(data)
    
    def post(self, request):
        """Create a new actor."""
        preferred_username = request.data.get('preferred_username')
        display_name = request.data.get('display_name', preferred_username)
        actor_type = request.data.get('type', 'Person')
        
        if not preferred_username:
            return Response(
                {'error': 'preferred_username is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if username is taken
        if ActorContext.objects.filter(preferred_username=preferred_username).exists():
            return Response(
                {'error': 'Username already taken'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            managed = ManagedActor.create_actor(
                user=request.user,
                preferred_username=preferred_username,
                display_name=display_name,
                actor_type=actor_type
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        actor = managed.actor
        return Response({
            'id': managed.id,
            'actor_uri': actor.reference.uri,
            'preferred_username': actor.preferred_username,
            'display_name': managed.display_name,
            'inbox': actor.inbox.uri if actor.inbox else None,
            'outbox': actor.outbox.uri if actor.outbox else None,
        }, status=status.HTTP_201_CREATED)
```

Configure URLs in `actors/urls.py`:

```python
from django.urls import path
from actors.views import ActorListCreateView

app_name = 'actors'

urlpatterns = [
    path('api/actors', ActorListCreateView.as_view(), name='actor-list'),
]
```

## Authenticated ActivityPub Views

The toolkit's `ActivityPubObjectDetailView` handles both inbox and outbox operations. For C2S, add authentication to verify the client is authorized to post to the outbox.

Create `actors/activitypub_views.py`:

```python
from rest_framework.response import Response
from rest_framework import status
from activitypub.views import ActivityPubObjectDetailView
from activitypub.views.activitystreams import is_an_outbox
from activitypub.models import ActorContext
from actors.models import ManagedActor


class AuthenticatedActivityPubView(ActivityPubObjectDetailView):
    """ActivityPub view with OAuth authentication for C2S operations."""
    
    def post(self, request, *args, **kwargs):
        """Handle POST with authentication for outbox, signature check for inbox."""
        reference = self.get_object()
        
        # Check if this is an outbox POST (C2S)
        if is_an_outbox(reference.uri):
            # C2S requires OAuth authentication
            if not request.user or not request.user.is_authenticated:
                return Response(
                    {'error': 'Authentication required for outbox posting'},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            # Verify user owns this outbox
            actor = ActorContext.objects.filter(outbox=reference).first()
            if not actor:
                return Response(
                    {'error': 'Invalid outbox'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            managed = ManagedActor.objects.filter(
                user=request.user,
                actor_reference=actor.reference
            ).first()
            
            if not managed:
                return Response(
                    {'error': 'You do not own this outbox'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        # Proceed with standard processing
        return super().post(request, *args, **kwargs)
```

## URL Routing

Create a catch-all URL pattern that routes ActivityPub requests. Update `actors/urls.py`:

```python
from django.urls import path, re_path
from actors.views import ActorListCreateView
from actors.activitypub_views import AuthenticatedActivityPubView

app_name = 'actors'

urlpatterns = [
    path('api/actors', ActorListCreateView.as_view(), name='actor-list'),
    
    # Catch-all for ActivityPub resources
    re_path(
        r'^(?P<path>.*)$',
        AuthenticatedActivityPubView.as_view(),
        name='activitypub-resource'
    ),
]
```

Update `FEDERATION` settings to configure view names:

```python
FEDERATION = {
    'DEFAULT_URL': 'http://localhost:8000',
    'SOFTWARE_NAME': 'GenericAP',
    'SOFTWARE_VERSION': '1.0.0',
    'ACTOR_VIEW': 'actors:activitypub-resource',
    'OBJECT_VIEW': 'actors:activitypub-resource',
    'ACTIVITY_VIEW': 'actors:activitypub-resource',
    'COLLECTION_VIEW': 'actors:activitypub-resource',
}
```

## Domain Setup

Create the local domain with a management command in `actors/management/commands/setup_domain.py`:

```python
from django.core.management.base import BaseCommand
from activitypub.models import Domain

class Command(BaseCommand):
    help = 'Set up the local domain'
    
    def handle(self, *args, **options):
        domain, created = Domain.objects.get_or_create(
            domain='localhost:8000',
            defaults={'local': True}
        )
        
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created domain: {domain}'))
        else:
            self.stdout.write(self.style.WARNING(f'Domain already exists: {domain}'))
```

Run setup:

```bash
python manage.py setup_domain
```

## Testing C2S: Creating an Actor

Test the API using OAuth authentication. First, get an access token:

```bash
curl -X POST -d "grant_type=password&username=yourusername&password=yourpassword&client_id=YOUR_CLIENT_ID&client_secret=YOUR_CLIENT_SECRET" http://localhost:8000/o/token/
```

This returns an access token. Use it to create an actor:

```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"preferred_username": "alice", "display_name": "Alice Smith", "type": "Person"}' \
  http://localhost:8000/api/actors
```

Response:

```json
{
  "id": 1,
  "actor_uri": "http://localhost:8000/actors/uuid-here",
  "preferred_username": "alice",
  "display_name": "Alice Smith",
  "inbox": "http://localhost:8000/collections/uuid-here",
  "outbox": "http://localhost:8000/collections/uuid-here"
}
```

## Testing C2S: Posting to Outbox

Post an activity to the actor's outbox:

```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/activity+json" \
  -d '{
    "@context": "https://www.w3.org/ns/activitystreams",
    "type": "Create",
    "actor": "http://localhost:8000/actors/uuid-here",
    "object": {
      "type": "Note",
      "content": "Hello from a generic ActivityPub client!"
    }
  }' \
  http://localhost:8000/collections/outbox-uuid-here
```

The server:

1. Authenticates the OAuth token
2. Verifies the user owns this outbox
3. Generates an ID for the activity if not provided
4. Parses the JSON-LD into an RDF graph
5. Creates context models (ActivityContext, ObjectContext)
6. Adds the activity to the outbox collection
7. Returns 201 Created with the activity URI

## Testing S2S: Fetching Resources

Remote servers fetch resources via HTTP GET with ActivityPub content negotiation:

```bash
curl -H "Accept: application/activity+json" http://localhost:8000/actors/uuid-here
```

Returns the actor document with inbox, outbox, and collection URLs.

Fetch the outbox:

```bash
curl -H "Accept: application/activity+json" http://localhost:8000/collections/outbox-uuid-here
```

Returns the collection with activities in reverse chronological order.

## Testing S2S: Inbox Delivery

Remote servers POST activities to the inbox with HTTP Signature authentication:

```bash
curl -X POST \
  -H "Content-Type: application/activity+json" \
  -H "Signature: keyId=\"https://remote.example/users/bob#key\",headers=\"(request-target) host date\",signature=\"...\"" \
  -d '{
    "@context": "https://www.w3.org/ns/activitystreams",
    "id": "https://remote.example/activities/123",
    "type": "Follow",
    "actor": "https://remote.example/users/bob",
    "object": "http://localhost:8000/actors/uuid-here"
  }' \
  http://localhost:8000/collections/inbox-uuid-here
```

The server:

1. Verifies the HTTP Signature
2. Resolves the actor to fetch their public key
3. Creates a Notification record
4. Processes the activity asynchronously
5. Returns 202 Accepted

## Discovery Endpoints

The toolkit provides built-in views for WebFinger and NodeInfo discovery. However, these require the `Account` model which links users to actors. For a generic server using only context models, create a simple adapter.

Create `actors/discovery.py`:

```python
from django.http import Http404
from activitypub.views.discovery import Webfinger, NodeInfo, NodeInfo2
from activitypub.models import ActorContext


class GenericWebfinger(Webfinger):
    """WebFinger for generic server without Account model."""
    
    def resolve_account(self, request, subject_name):
        """Resolve actor by username instead of Account."""
        try:
            username, domain = subject_name.split('@')
        except ValueError:
            raise Http404
        
        try:
            actor_ctx = ActorContext.objects.get(preferred_username=username)
        except ActorContext.DoesNotExist:
            raise Http404
        
        # Return a minimal object with actor attribute
        class MinimalAccount:
            def __init__(self, actor_ctx):
                self.actor = actor_ctx.reference
        
        return MinimalAccount(actor_ctx)
```

Update `config/urls.py`:

```python
from activitypub.views.discovery import NodeInfo, NodeInfo2, HostMeta
from actors.discovery import GenericWebfinger

urlpatterns = [
    path('admin/', admin.site.urls),
    path('o/', include('oauth2_provider.urls', namespace='oauth2_provider')),
    path('.well-known/webfinger', GenericWebfinger.as_view(), name='webfinger'),
    path('.well-known/nodeinfo', NodeInfo.as_view(), name='nodeinfo'),
    path('.well-known/host-meta', HostMeta.as_view(), name='host-meta'),
    path('nodeinfo/2.0', NodeInfo2.as_view(), name='nodeinfo-2.0'),
    path('', include('actors.urls')),
]
```

## Admin Interface

Create admin views for managing actors in `actors/admin.py`:

```python
from django.contrib import admin
from actors.models import ManagedActor

@admin.register(ManagedActor)
class ManagedActorAdmin(admin.ModelAdmin):
    list_display = ('user', 'display_name', 'get_username', 'created_at')
    list_filter = ('created_at', 'user')
    search_fields = ('display_name', 'user__username')
    readonly_fields = ('actor_reference', 'created_at')
    
    def get_username(self, obj):
        return obj.actor.preferred_username if obj.actor else None
    get_username.short_description = 'Username'
```

## Handling Different Object Types

The generic server accepts any ActivityStreams type. Clients can create Notes, Articles, Events, Images, or custom types:

```json
{
  "@context": "https://www.w3.org/ns/activitystreams",
  "type": "Create",
  "actor": "http://localhost:8000/actors/uuid",
  "object": {
    "type": "Event",
    "name": "Federated Meetup",
    "startTime": "2025-02-01T19:00:00Z",
    "location": {
      "type": "Place",
      "name": "Community Center"
    }
  }
}
```

The server creates `ObjectContext` instances for all objects, storing common properties like `type`, `name`, `content`, and `published`. Type-specific properties remain in the JSON-LD document but may not have dedicated Django fields unless you create custom context models.

## Client Implementation Example

A simple Python client using this server:

```python
import requests

class ActivityPubClient:
    def __init__(self, base_url, access_token):
        self.base_url = base_url
        self.headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/activity+json',
        }
    
    def create_actor(self, username, display_name):
        response = requests.post(
            f'{self.base_url}/api/actors',
            json={
                'preferred_username': username,
                'display_name': display_name,
            },
            headers=self.headers
        )
        return response.json()
    
    def post_note(self, outbox_url, content):
        activity = {
            '@context': 'https://www.w3.org/ns/activitystreams',
            'type': 'Create',
            'object': {
                'type': 'Note',
                'content': content,
            }
        }
        response = requests.post(outbox_url, json=activity, headers=self.headers)
        return response.json()

# Usage
client = ActivityPubClient('http://localhost:8000', 'your-access-token')
actor = client.create_actor('testuser', 'Test User')
client.post_note(actor['outbox'], 'Hello, Fediverse!')
```

## Production Considerations

For production deployment:

**HTTPS:** Configure TLS certificates. ActivityPub requires HTTPS for federation.

**Domain:** Use a real domain name, not localhost. Update `FEDERATION.DEFAULT_URL` and create the corresponding Domain record.

**Database:** Use PostgreSQL or another production database instead of SQLite.

**Task Queue:** Configure Celery for asynchronous notification processing. The toolkit uses `process_incoming_notification.delay()` which requires a task queue.

**Rate Limiting:** Implement rate limiting on API endpoints and inbox delivery to prevent abuse.

**OAuth Scopes:** Refine OAuth scopes to control what clients can do (read vs write vs follow).

**Backup:** Regular backups of the database and media files.

## Summary

You have built a complete generic ActivityPub server. It implements both C2S (client-to-server) and S2S (server-to-server) protocols. Clients authenticate via OAuth and post activities to outboxes. Remote servers deliver activities to inboxes via HTTP Signatures.

The server stores ActivityStreams objects using only the toolkit's context models. No application-specific models are required. This enables any ActivityPub client to work with the server, creating any type of ActivityStreams object.

This architecture realizes the vision of the Fediverse as a shared social graph. Multiple clients—microblogging apps, photo galleries, event calendars—can use the same server. Each client presents a different view of the user's social data without requiring separate accounts or servers.

The generic server pattern demonstrates the toolkit's flexibility. By relying on context models and references, you can build protocol-level infrastructure that adapts to any use case. Applications add domain-specific logic as separate layers without modifying the core federation mechanics.
