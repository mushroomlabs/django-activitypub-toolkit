---
title: Authentication and Authorization
---

Trust and security in federated systems require mechanisms to verify the authenticity of messages and control access to resources. Django ActivityPub Toolkit provides authentication for both local users and remote actors, along with extensible authorization policies.

## Authentication in Federated Systems

ActivityPub servers handle two distinct authentication scenarios: verifying messages from remote servers and authenticating local users who control actors on your server.

Remote authentication uses HTTP Signatures, a standard for signing HTTP requests using public-key cryptography. Each actor publishes a public key as part of their actor document. When their server sends a request, it signs the request headers with the corresponding private key. The receiving server fetches the actor's public key and verifies the signature. This proves the request originated from a server that controls the actor's domain and has not been tampered with in transit.

Local authentication connects Django users to ActivityPub actors through the Identity system. A single Django user can control multiple actors, each representing a distinct identity within the fediverse. This separation allows users to maintain different personas or manage multiple accounts while authenticating once to your application.

## Local User Authentication

The Identity system bridges Django's authentication with ActivityPub actors. Each Identity links a Django user to an ActorContext, establishing ownership and control.

```python
from activitypub.core.models import Identity, ActorContext, Reference

# Create an actor for a user
actor_ref = Reference.make('https://myserver.com/actors/alice')
actor = ActorContext.objects.create(
    reference=actor_ref,
    preferred_username='alice',
    name='Alice Smith'
)

# Link it to a Django user
identity = Identity.objects.create(
    user=user,
    actor=actor,
    is_primary=True
)
```

Users can have multiple identities, but only one can be marked as primary. The primary identity represents the user's default actor for operations that don't specify which identity to use.

The `ActorMiddleware` automatically attaches the actor to incoming requests when a user is authenticated and has exactly one identity. This provides convenient access to the current actor without manual lookups:

```python
# In a view with ActorMiddleware enabled
def my_view(request):
    if hasattr(request, 'actor'):
        # User is authenticated and has a single identity
        actor = request.actor
        # Perform operations as this actor
```

For applications where users manage multiple identities, views must explicitly determine which identity the user is acting as. The OAuth authorization flow demonstrates this pattern by prompting users to select an identity when authorizing client applications.

### Authentication Backends

The toolkit provides `ActorUsernameAuthenticationBackend` for authenticating users by actor username and domain rather than Django username:

```python
# settings.py
AUTHENTICATION_BACKENDS = [
    'activitypub.core.authentication_backends.ActorUsernameAuthenticationBackend',
    'django.contrib.auth.backends.ModelBackend',
]
```

This backend authenticates users by looking up an Identity with the specified username and domain, then verifying the password against the associated Django user. This allows users to log in using their ActivityPub actor identifier rather than their Django username.

### OAuth and Identity Selection

The OAuth integration extends django-oauth-toolkit to support identity-scoped tokens. When a client application requests authorization, the user selects which identity to authorize. Access tokens are bound to that identity, and API requests authenticated with the token operate in the context of that specific actor.

```python
from activitypub.extras.oauth.models import OAuthAccessToken

# Access tokens are bound to identities
token = OAuthAccessToken.objects.get(token=token_string)
actor = token.identity.actor

# The token response includes the actor URI
# {
#   "access_token": "...",
#   "token_type": "Bearer",
#   "expires_in": 3600,
#   "actor": "https://myserver.com/actors/alice"
# }
```

Client applications receive the actor URI in the token response, allowing them to identify which actor they're operating as. This supports multi-account clients that manage multiple identities across different servers.

The OAuth validator includes custom OIDC claims for ActivityPub identity information:

```python
# Claims available in the activitypub scope
{
    "sub": "https://myserver.com/actors/alice",
    "preferred_username": "alice",
    "subject_username": "alice@myserver.com",
    "display_name": "Alice Smith",
    "profile": "https://myserver.com/actors/alice",
    "identity_id": 123
}
```

These claims allow client applications to retrieve actor information without additional API requests.

### User-Controlled Domains

The `UserDomain` model allows users to control entire domains hosted on your server. This supports multi-tenant scenarios where different users manage separate namespaces:

```python
from activitypub.core.models import UserDomain, Domain

# Create a local domain controlled by a user
domain = Domain.objects.create(
    url='https://alice-space.example.com',
    local=True
)

user_domain = UserDomain.objects.create(
    domain=domain,
    owner=user
)
```

When a user controls a domain, they can create actors within that namespace and manage resources associated with those actors. This pattern supports applications that provide personal fediverse instances or allow users to bring their own domains.

The validation ensures only local domains can be assigned to users, preventing users from claiming ownership of remote domains they don't control.

## Remote Actor Authentication

When your server receives an ActivityPub message—typically a POST to an inbox—the toolkit creates a `Notification` instance linking the sender, target, and resource references. Authentication happens through the `authenticate()` method, which processes all proof mechanisms attached to the notification.

```python
from activitypub.core.models import Notification

notification = Notification.objects.get(pk=notification_id)
notification.authenticate()

if notification.is_authorized:
    # Process the notification
    handle_activity(notification.resource)
else:
    # Reject or log the failed authentication
    logger.warning(f"Unauthorized notification from {notification.sender.uri}")
```

The `authenticate()` method walks through all `NotificationIntegrityProof` instances associated with the notification. For remote notifications, it optionally resolves the sender's actor document to fetch their public keys. Each proof implementation attempts verification and, if successful, creates a `NotificationProofVerification` record.

A notification is considered authorized if it has at least one successful verification or if it originates from a local sender. This simple rule provides a foundation that applications can extend with more sophisticated policies.

## Integrity Proofs

The `NotificationIntegrityProof` model is an abstract base that proof mechanisms extend. Django ActivityPub Toolkit includes two concrete implementations: HTTP Signature proofs and document signature proofs.

HTTP Signature proofs verify the signature on the HTTP request that delivered the notification. When an inbox view receives a POST request, it extracts the `Signature` header, parses its components, and creates an `HttpMessageSignature` record containing the signature, the signed message text, and a reference to the key ID.

```python
# Simplified inbox view flow
def post(self, request):
    # Extract HTTP signature from request headers
    http_sig = HttpMessageSignature.extract(request)

    # Parse the activity document
    activity_data = request.data
    activity_ref = Reference.make(activity_data['id'])
    document = LinkedDataDocument.make(activity_data)
    document.load()

    # Create notification
    notification = Notification.objects.create(
        sender=Reference.make(activity_data['actor']),
        target=inbox_ref,
        resource=activity_ref
    )

    # Create HTTP signature proof
    if http_sig:
        HttpSignatureProof.objects.create(
            notification=notification,
            http_message_signature=http_sig
        )

    # Authenticate and process
    notification.authenticate()
    if notification.is_authorized:
        process_notification(notification)
```

The `HttpSignatureProof` implements verification by fetching the signing key from the actor's security context and calling `verify_signature()` with the signature bytes and the signed message text. If verification succeeds, it creates a `NotificationProofVerification` record linking the notification to the proof.

Document signature proofs work similarly but verify signatures embedded in the JSON-LD document itself rather than in HTTP headers. Some ActivityPub implementations include a `signature` property in their activity documents, allowing the document to be verified independently of transport.

## Key Management

Actors need cryptographic keys to sign requests. The `SecV1Context` model stores keys using the Security Vocabulary v1 namespace. Each key has an owner (the actor that controls it), public key material in PEM format, and optionally private key material for local actors.

Generating a keypair for a local actor is straightforward:

```python
from activitypub.core.models import SecV1Context, Reference

actor_ref = Reference.objects.get(uri='https://myserver.com/actors/alice')
keypair = SecV1Context.generate_keypair(owner=actor_ref)

# The keypair is now associated with the actor
print(keypair.key_id)  # 'https://myserver.com/actors/alice#key-01234567'
```

The generated key includes a URI that remote servers can fetch. When serializing the actor document, the toolkit includes the public key in the actor's `publicKey` property. Remote servers cache this key when they resolve the actor reference.

Keys can be revoked by setting the `revoked` timestamp. Revoked keys fail verification even if the signature is cryptographically valid. This allows actors to rotate keys if they suspect compromise.

The toolkit automatically uses the actor's key for signing outgoing requests when resolving remote resources. The `HttpDocumentResolver` checks if the local actor has a keypair and, if so, attaches signed authentication to HTTP GET requests.

## Extending Authentication Mechanisms

Applications with specialized authentication requirements can implement custom proof types by extending `NotificationIntegrityProof`. The proof model needs to implement verification logic and create a `NotificationProofVerification` when verification succeeds.

Consider an application that wants to support bearer token authentication for trusted external services:

```python
from activitypub.core.models import NotificationIntegrityProof, NotificationProofVerification
from django.db import models
from myapp.models import TrustedService

class BearerTokenProof(NotificationIntegrityProof):
    token_value = models.CharField(max_length=255)

    def verify(self, fetch_missing_keys=False):
        # Check token against allowed tokens for this sender
        service = TrustedService.objects.filter(
            actor_reference=self.notification.sender,
            token=self.token_value,
            revoked=False
        ).first()

        if service:
            return NotificationProofVerification.objects.create(
                notification=self.notification,
                proof=self
            )
```

The inbox view extracts the bearer token from the `Authorization` header and creates a `BearerTokenProof` instance. When `notification.authenticate()` runs, it processes all proofs including the custom one.

This pattern extends to any authentication mechanism: OAuth tokens, API keys, challenge-response schemes, or even integration with external authentication services. The proof abstraction separates authentication logic from notification processing.

## Authorization Policies

Authentication establishes identity. Authorization determines what actions that identity can perform.

For remote notifications, the `is_authorized` property on `Notification` checks for successful cryptographic verification or local origin. This answers "is this notification from who it claims to be?" but not "should we accept this notification?" Applications implement additional authorization policies in their notification handlers based on relationships, content rules, or domain policies.

For local users accessing resources, the toolkit provides Django REST Framework permission classes. The `IsOutboxOwnerOrReadOnly` permission demonstrates the pattern:

```python
from rest_framework import permissions
from activitypub.core.models import ActorContext, Reference

class IsOutboxOwnerOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj: Reference):
        if request.method in permissions.SAFE_METHODS:
            return True

        if not request.user.is_authenticated:
            return False

        actors = ActorContext.objects.filter(identity__user=request.user)
        return actors.filter(outbox=obj).exists()
```

This permission allows anyone to read an outbox but restricts write operations to the user who owns the actor. The pattern checks whether any of the user's identities control the resource in question.

Applications extend this model with domain-specific policies:

```python
class CanModerateContent(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        # Check if any of the user's actors have moderator status
        return ActorContext.objects.filter(
            identity__user=request.user,
            moderator_status=True
        ).exists()

class IsActorOwner(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        # For actor resources, check identity ownership
        return Identity.objects.filter(
            user=request.user,
            actor=obj
        ).exists()
```

Authorization for incoming federated activities typically happens in notification processors rather than view permissions. Processors inspect the activity type, sender relationships, and content before deciding whether to accept the activity:

```python
def process_notification(notification):
    if not notification.is_authorized:
        logger.warning(f"Rejecting unauthorized notification from {notification.sender.uri}")
        return

    activity = notification.resource.get_by_context(ActivityContext)

    # Domain-level blocking
    if notification.sender.domain.blocked:
        logger.info(f"Rejecting notification from blocked domain")
        return

    # Relationship-based authorization
    if activity.type == ActivityContext.Types.CREATE:
        target_actor = notification.target.get_by_context(ActorContext)
        if not target_actor.followed_by.filter(uri=notification.sender.uri).exists():
            logger.info(f"Rejecting Create from non-follower")
            return

    # Process the activity
    handle_activity_type(activity)
```

Different applications require different trust models. A public forum might accept posts from any authenticated actor. A private community might only accept from members. A content aggregator might only accept from verified sources. The toolkit provides the authentication primitives; applications implement authorization policies appropriate to their use case.

## Outgoing Request Authentication

When your server fetches resources from remote servers or delivers activities, it should identify itself. Many servers require signed requests to access non-public resources or to prevent abuse.

The `HttpDocumentResolver` automatically signs outgoing requests using the local server's actor keypair. When resolving a reference, it looks up the default domain's actor and, if that actor has a keypair, attaches an HTTP Signature to the GET request.

```python
# Automatic signing in document resolver
domain = Domain.get_default()
server, _ = ActivityPubServer.objects.get_or_create(domain=domain)
signing_key = server and server.actor and server.actor.main_cryptographic_keypair

if signing_key:
    auth = signing_key.signed_request_auth
    response = requests.get(uri, headers={...}, auth=auth)
```

The `signed_request_auth` property returns a `requests` authentication handler that signs the request according to the HTTP Signatures specification. It signs the request target, host, date, and user-agent headers, providing proof that the request comes from your server.

Applications making direct HTTP requests to remote servers should use the same pattern. Fetch the local actor's keypair and attach it as authentication to the request. This establishes trust and increases the likelihood that remote servers will respond positively.

### Protecting Actor Resources

Actor outboxes and other writable collections require authentication to prevent unauthorized posting. The toolkit provides authentication checks for these endpoints, ensuring only the actor owner can post to their outbox:

```python
# In a view handling outbox POST requests
class OutboxView(APIView):
    permission_classes = [IsOutboxOwnerOrReadOnly]

    def post(self, request, actor_id):
        # Permission class ensures user owns this actor
        # Process the activity posting
        pass
```

This protection prevents remote actors from posting to local actor outboxes, even if they present valid HTTP signatures. Only authenticated local users who control the actor can write to protected collections.

## Multi-Tenancy and Per-Actor Keys

Systems hosting multiple independent actors might want each actor to have their own keypair rather than sharing a single server keypair. This provides better isolation and makes key rotation simpler.

The toolkit supports this model. Generate a keypair for each actor using `SecV1Context.generate_keypair()`. When serializing actor documents, include the actor-specific public key. When signing outgoing requests on behalf of an actor, use that actor's keypair.

The challenge is determining which actor is making a request. For inbox delivery, the activity's `actor` field identifies who is acting. For GET requests to fetch resources, the server decides which actor's credentials to present, typically using the instance actor or allowing administrators to configure per-actor outgoing authentication.

## Trust Boundaries

Understanding where trust boundaries lie helps design secure federated applications. When your server receives a message with a valid signature, you know it came from the sender's server. You do not know:

**User authorization.** The server controls the private key, not the individual user. The server could send activities without user approval.

**Server honesty.** The remote server could lie about its state. An actor's follower list might not accurately reflect who actually follows them.

**Data persistence.** Activities can be deleted or modified after delivery. Your cached copy might not match the current state on the origin server.

**Identity continuity.** Domain ownership can change. The actor at a URI today might not be the same entity next year.

These limitations are inherent to federated systems. Authorization policies should account for the possibility of misbehaving servers. Design systems that degrade gracefully when trust assumptions fail. Provide mechanisms for users to block problematic actors or domains.

## Extending the Trust Model

Applications can layer additional trust mechanisms on top of basic signature verification. Some possibilities:

**Reputation systems.** Track behavior over time and adjust trust levels based on interaction history. Servers that consistently send valid, appropriate activities earn higher reputation.

**Web of trust.** Weight authentication based on relationships. Activities from actors that your users follow might receive different treatment than activities from unknown actors.

**External verification.** Integrate with external identity providers or verification services. An actor might prove ownership of other accounts or credentials, increasing confidence in their identity.

**Rate limiting.** Even authenticated requests should be rate-limited to prevent abuse. Track request patterns and throttle suspicious behavior.

The notification and proof abstractions provide hooks for these mechanisms. Custom proof types can implement complex verification logic. Authorization handlers can query reputation systems or relationship graphs. The flexible architecture supports trust models ranging from fully open to highly restrictive.

## Practical Considerations

In production deployments, several practical issues arise around authentication and authorization:

**Key storage.** Private keys should be encrypted at rest and never exposed in logs or error messages. Consider using key management services for sensitive deployments.

**Clock skew.** HTTP Signatures include timestamps that must be within a reasonable window of the current time. Ensure system clocks are synchronized via NTP.

**Key rotation.** Plan for periodic key rotation even without suspected compromise. Rotating keys requires publishing new public keys and retiring old ones gracefully.

**Performance.** Cryptographic operations are expensive. Cache verification results where appropriate and consider async processing for high-volume inboxes.

**Debugging.** Signature verification failures can be cryptic. Log enough information to diagnose issues without exposing sensitive key material.

The toolkit handles the mechanics of signature verification, but applications must handle these operational concerns based on their scale and security requirements.
