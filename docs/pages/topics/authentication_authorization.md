---
title: Authentication and Authorization
---

Trust and security in federated systems require mechanisms to verify the authenticity of messages and control access to resources. Django ActivityPub Toolkit provides a flexible authentication framework built around cryptographic proofs and extensible authorization policies.

## The Authentication Problem

When your server receives a message claiming to be from a remote actor, you need to verify that claim. Unlike centralized systems where all requests authenticate against a central authority, federated systems must establish trust across autonomous servers that have never directly coordinated.

ActivityPub addresses this through HTTP Signatures, a standard for signing HTTP requests using public-key cryptography. Each actor publishes a public key as part of their actor document. When their server sends a request, it signs the request headers with the corresponding private key. The receiving server fetches the actor's public key and verifies the signature.

This proves two things: the request originated from a server that controls the actor's domain, and the request has not been tampered with in transit. It does not prove that a specific person authorized the request, only that the request came from the server claiming to host that actor.

## Notification Authentication

When your server receives an ActivityPub message—typically a POST to an inbox—the toolkit creates a `Notification` instance linking the sender, target, and resource references. Authentication happens through the `authenticate()` method, which processes all proof mechanisms attached to the notification.

```python
from activitypub.models import Notification

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
from activitypub.models import SecV1Context, Reference

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
from activitypub.models import NotificationIntegrityProof, NotificationProofVerification
from django.db import models

class BearerTokenProof(NotificationIntegrityProof):
    token_value = models.CharField(max_length=255)
    
    def verify(self, fetch_missing_keys=False):
        # Check token against allowed tokens for this sender
        from myapp.models import TrustedService
        
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

Authentication establishes identity. Authorization determines what actions that identity can perform. The toolkit provides a minimal authorization model that applications extend based on their requirements.

The `is_authorized` property on `Notification` checks for successful verification or local origin. This answers "is this notification from who it claims to be?" but not "should we accept this notification?"

Applications implement authorization policies in their notification handlers or view permissions. Common policies include:

**Domain blocking.** Reject notifications from actors whose domains appear on a blocklist. The `UnblockedDomainOrActorPermission` class demonstrates this pattern.

**Relationship requirements.** Only accept certain activity types from actors that have an established relationship. For example, only process `Create` activities from actors that the target follows.

**Content policies.** Inspect activity objects for policy violations before accepting them. This might include spam filtering, content restrictions, or rate limiting.

**Scope limitations.** Restrict what activities can be posted to specific collections. Public inboxes might accept `Follow` and `Like` activities but reject `Delete` activities for objects they don't own.

```python
def process_notification(notification):
    activity = notification.resource.get_by_context(ActivityContext)
    
    # Authorization: check relationship
    if activity.type == ActivityContext.Types.CREATE:
        target_actor = notification.target.get_by_context(ActorContext)
        sender_in_followers = target_actor.followed_by.filter(
            uri=notification.sender.uri
        ).exists()
        
        if not sender_in_followers:
            logger.info(f"Rejecting Create from non-follower {notification.sender.uri}")
            return
    
    # Authorization: check domain block
    if notification.sender.domain.blocked:
        logger.info(f"Rejecting notification from blocked domain {notification.sender.domain}")
        return
    
    # Process the activity
    handle_activity_type(activity)
```

Authorization logic lives in application code, not in the toolkit. Different applications have different trust models. A public forum might accept posts from any authenticated actor. A private community might only accept from members. A content aggregator might only accept from verified sources.

## Outgoing Request Authentication

When your server fetches resources from remote servers, it should identify itself. Many servers require signed requests to access non-public resources or to prevent abuse.

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
