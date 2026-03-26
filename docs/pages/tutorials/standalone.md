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

pip install django django-activitypub-toolkit djangorestframework
django-admin startproject standalone .
python manage.py startapp actors
```

Configure `standalone/settings.py`:

```python
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'activitypub.core',
    'actors',
]

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

## Identity System

The toolkit provides a built-in Identity system that links Django users to ActivityPub actors. A single user can control multiple actors, each representing a distinct identity.

No additional models are needed. The Identity system is already configured through the installed apps. We can manage them all at the Django Admin.

To access the django admin, you will need to create a superuser:

```bash
python manage.py createsuperuser
```

## OAuth Authentication Setup

A standalone ActivityPub server needs to authenticate two different
kinds of requests: server-to-server federation (handled by HTTP
Signatures, covered later) and client-to-server API requests. For C2S,
clients need to prove they are authorized to act on behalf of a
specific actor. Since a single user may control multiple actors,
simple user-level authentication is not sufficient. We need tokens
that are scoped to a specific actor. One of the many ways to do this
is by leveraging OAuth, so in this section we will see how to set it up.


Install Django OAuth Toolkit:

```bash
pip install django-oauth-toolkit
```

Add it to INSTALLED_APPS and configure DRF to use OAuth authentication:

```python
INSTALLED_APPS = [
    ...
    'oauth2_provider',
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'actors.oauth.ActorScopedOAuth2Authentication',
    ],
}

OAUTH2_PROVIDER = {
    'SCOPES': {
        'read': 'Read access',
        'write': 'Write access',
    },
    'ACCESS_TOKEN_MODEL': 'actors.ActorAccessToken',
}
```

Create `actors/models.py` with a custom access token model that ties each token to a specific actor:

```python
from django.db import models
from oauth2_provider.models import AbstractAccessToken
from activitypub.core.models import ActorContext

class ActorAccessToken(AbstractAccessToken):
    actor = models.ForeignKey(
        ActorContext,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='access_tokens',
    )

    class Meta:
        app_label = 'actors'
```

Create `actors/oauth.py` with a validator that binds the actor during the authorization code exchange, and an authentication class that attaches it to the request:

```python
from oauth2_provider.contrib.rest_framework import OAuth2Authentication
from oauth2_provider.oauth2_validators import OAuth2Validator
from activitypub.core.models import Reference
from .models import ActorAccessToken

class ActorOAuth2Validator(OAuth2Validator):
    def save_authorization_code(self, client_id, code, request, *args, **kwargs):
        # Store the actor URI from login_hint in the authorization code
        # so it can be retrieved during token exchange
        request.actor_uri = request.GET.get('login_hint')
        super().save_authorization_code(client_id, code, request, *args, **kwargs)

    def save_bearer_token(self, token, request, *args, **kwargs):
        super().save_bearer_token(token, request, *args, **kwargs)
        if hasattr(request, 'actor_uri') and request.actor_uri:
            try:
                ref = Reference.objects.get(uri=request.actor_uri)
                actor = ref.actor_context
                ActorAccessToken.objects.filter(
                    token=token['access_token']
                ).update(actor=actor)
            except Exception:
                pass

class ActorScopedOAuth2Authentication(OAuth2Authentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        request.actor = getattr(token, 'actor', None)
        return user, token
```

Add the custom validator to your OAuth settings:

```python
OAUTH2_PROVIDER = {
    ...
    'OAUTH2_VALIDATOR_CLASS': 'actors.oauth.ActorOAuth2Validator',
}
```

Run migrations to create the token table:

```bash
python manage.py makemigrations actors
python manage.py migrate
```

Create an OAuth application in the Django admin under **OAuth2 Provider → Applications**. Set the client type to **Confidential** and the authorization grant type to **Authorization code**.

Clients authenticate by directing the user to the authorization endpoint with the actor URI as a hint:

```
http://localhost:8000/o/authorize/?response_type=code&client_id=YOUR_CLIENT_ID&redirect_uri=YOUR_REDIRECT_URI&scope=read+write&login_hint=http://localhost:8000/actors/uuid-here
```

After the user approves, exchange the authorization code for a token:

```bash
curl -X POST \
  -d "grant_type=authorization_code&code=AUTH_CODE&redirect_uri=YOUR_REDIRECT_URI&client_id=YOUR_CLIENT_ID&client_secret=YOUR_CLIENT_SECRET" \
  http://localhost:8000/o/token/
```

The response includes a bearer token scoped to the specified actor:

```json
{
  "access_token": "your-access-token",
  "token_type": "Bearer",
  "expires_in": 36000,
  "refresh_token": "your-refresh-token",
  "scope": "read write"
}
```

## Actor Creation API

Clients need an API to create and list actors. Create `actors/views.py`:

```python
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from activitypub.core.models import Identity, ActorContext, Reference, Domain, SecV1Context, CollectionContext

class ActorListCreateView(APIView):
    """List and create actors for the authenticated user."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List actors managed by this user."""
        identities = Identity.objects.filter(user=request.user).select_related('actor')

        data = []
        for identity in identities:
            actor = identity.actor
            data.append({
                'id': identity.id,
                'actor_uri': actor.reference.uri,
                'preferred_username': actor.preferred_username,
                'display_name': actor.name,
                'type': actor.get_type_display(),
                'is_primary': identity.is_primary,
                'inbox': actor.inbox.uri if actor.inbox else None,
                'outbox': actor.outbox.uri if actor.outbox else None,
            })

        return Response(data)

    def post(self, request):
        """Create a new actor and identity."""
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

        # Map actor type string to enum
        type_mapping = {
            'Person': ActorContext.Types.PERSON,
            'Service': ActorContext.Types.SERVICE,
            'Application': ActorContext.Types.APPLICATION,
            'Group': ActorContext.Types.GROUP,
            'Organization': ActorContext.Types.ORGANIZATION,
        }
        actor_type_enum = type_mapping.get(actor_type, ActorContext.Types.PERSON)

        try:
            domain = Domain.get_default()
            actor_ref = ActorContext.generate_reference(domain)

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

            # Create identity
            is_primary = not request.user.identities.exists()
            identity = Identity.objects.create(
                user=request.user,
                actor=actor,
                is_primary=is_primary
            )

        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response({
            'id': identity.id,
            'actor_uri': actor.reference.uri,
            'preferred_username': actor.preferred_username,
            'display_name': actor.name,
            'is_primary': identity.is_primary,
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

The toolkit's `ActivityPubObjectDetailView` handles both inbox and outbox operations. For C2S, add authentication to verify the client is authorized to post to the outbox. The `IsOutboxOwnerOrReadOnly` permission class checks if the resource being accessed belongs to the authenticated user making the request.

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
from activitypub.core.models import Domain

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

Test the API using OAuth authentication. First, get an access token using the password grant:

```bash
curl -X POST \
  -d "grant_type=password&username=yourusername&password=yourpassword&client_id=YOUR_CLIENT_ID&client_secret=YOUR_CLIENT_SECRET&scope=read write activitypub" \
  http://localhost:8000/o/token/
```

The response includes an access token and the actor URI if you already have an identity:

```json
{
  "access_token": "your-access-token",
  "token_type": "Bearer",
  "expires_in": 36000,
  "refresh_token": "your-refresh-token",
  "scope": "read write activitypub",
  "actor": "http://localhost:8000/actors/uuid-here"
}
```

Use the access token to create a new actor:

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
  "is_primary": true,
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

The toolkit provides built-in views for WebFinger and NodeInfo discovery. These work with the Identity system to resolve actors by their subject names.

Update `standalone/urls.py` to include discovery endpoints:

```python
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('o/', include('oauth2_provider.urls', namespace='oauth2_provider')),
    path('', include('actors.urls')),
]
```

The toolkit's discovery views automatically work with the Identity system, resolving actors by their preferred username and domain.

## Managing Identities

The toolkit provides a built-in `IdentityAdmin` for managing user identities through the Django admin interface. Navigate to **Activitypub Core → Identities** to view and manage which actors users control.

The admin interface displays:
- User associated with the identity
- Actor reference and handle
- Primary identity designation
- Search and filtering capabilities

No additional admin configuration is required.

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
    def __init__(self, base_url, client_id, client_secret):
        self.base_url = base_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.actor_uri = None

    def authenticate(self, username, password):
        """Authenticate and get access token with actor information."""
        response = requests.post(
            f'{self.base_url}/o/token/',
            data={
                'grant_type': 'password',
                'username': username,
                'password': password,
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'scope': 'read write activitypub',
            }
        )
        data = response.json()
        self.access_token = data['access_token']
        self.actor_uri = data.get('actor')
        return data

    @property
    def headers(self):
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/activity+json',
        }

    def list_actors(self):
        """List all actors for the authenticated user."""
        response = requests.get(
            f'{self.base_url}/api/actors',
            headers=self.headers
        )
        return response.json()

    def create_actor(self, username, display_name, actor_type='Person'):
        """Create a new actor identity."""
        response = requests.post(
            f'{self.base_url}/api/actors',
            json={
                'preferred_username': username,
                'display_name': display_name,
                'type': actor_type,
            },
            headers=self.headers
        )
        return response.json()

    def post_note(self, outbox_url, content):
        """Post a note to an actor's outbox."""
        activity = {
            '@context': 'https://www.w3.org/ns/activitystreams',
            'type': 'Create',
            'actor': self.actor_uri,
            'object': {
                'type': 'Note',
                'content': content,
            }
        }
        response = requests.post(outbox_url, json=activity, headers=self.headers)
        return response.json()

# Usage
client = ActivityPubClient('http://localhost:8000', 'client-id', 'client-secret')

# Authenticate
auth_data = client.authenticate('myusername', 'mypassword')
print(f"Authenticated as: {auth_data.get('actor')}")

# List existing actors
actors = client.list_actors()
print(f"User has {len(actors)} actor(s)")

# Create a new actor if needed
if not actors:
    actor = client.create_actor('alice', 'Alice Smith')
    print(f"Created actor: {actor['actor_uri']}")
else:
    actor = actors[0]

# Post a note
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

You have built a complete generic ActivityPub server using the toolkit's built-in Identity system. The server implements both C2S (client-to-server) and S2S (server-to-server) protocols. Clients authenticate via OAuth with actor-scoped tokens and post activities to outboxes. Remote servers deliver activities to inboxes via HTTP Signatures.

Key features of this implementation:

**Identity Management:** Users control multiple actors through the Identity system. Each OAuth token is bound to a specific actor, allowing clients to operate in the context of that actor.

**OAuth Integration:** Django OAuth Toolkit handles authentication with a custom access token model that ties tokens to actors, and a validator that captures actor selection during authorization.

**Generic Storage:** The server stores ActivityStreams objects using only the toolkit's context models. No application-specific models are required beyond the built-in Identity system.

**Protocol Compliance:** Full support for ActivityPub discovery (WebFinger, NodeInfo), HTTP Signatures for federation, and OAuth 2.0 for client authentication.

This architecture realizes the vision of the Fediverse as a shared social graph. Multiple clients—microblogging apps, photo galleries, event calendars—can use the same server. Each client presents a different view of the user's social data without requiring separate accounts or servers.

The generic server pattern demonstrates the toolkit's flexibility. By relying on context models, references, and the Identity system, you can build protocol-level infrastructure that adapts to any use case. Applications add domain-specific logic as separate layers without modifying the core federation mechanics.
