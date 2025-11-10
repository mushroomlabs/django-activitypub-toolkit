# Register an Account

This guide shows you how to create `Account` records that link usernames to `Actor` context models for federation.

## Understanding Accounts

The `Account` model provides human-readable identifiers (`@username@domain`) for actors in the fediverse. Every federated actor needs an account to be discoverable via WebFinger and to have a recognizable identity.

The relationship is:

- **Account** - Social identifier (`@alice@example.com`)
- **Actor** - ActivityPub entity (has inbox, outbox, followers, etc.)
- **Reference** - Graph node (URI pointer)

## Create a Local Account

Local accounts represent users on your application's domain.

### Prerequisites

You must have a local domain registered. See [Register a Domain](register_domain.md) for setup instructions.

### Using Django Shell

```python
from activitypub.models import Account, Actor, ActorContext, Domain, Reference

local_domain = Domain.objects.get(local=True)
username = "alice"

actor_uri = f"https://{local_domain.name}/actors/{username}"
actor_ref = Reference.make(actor_uri)

actor = ActorContext.make(
    reference=actor_ref,
    type=ActorContext.Types.PERSON,
    preferred_username=username,
    name="Alice Smith",
)

account = Account.objects.create(
    actor=actor,
    domain=local_domain,
    username=username
)
```

The account is now discoverable at `@alice@example.com` via WebFinger.

### With Collections

Actors typically need collections for inbox, outbox, followers, and following. Create them alongside the actor:

```python
from activitypub.models import CollectionContext

inbox_ref = Reference.make(f"{actor_uri}/inbox")
outbox_ref = Reference.make(f"{actor_uri}/outbox")
followers_ref = Reference.make(f"{actor_uri}/followers")
following_ref = Reference.make(f"{actor_uri}/following")

inbox = CollectionContext.make(inbox_ref, type=CollectionContext.Types.ORDERED)
outbox = CollectionContext.make(outbox_ref, type=CollectionContext.Types.ORDERED)
followers = CollectionContext.make(followers_ref, type=CollectionContext.Types.UNORDERED)
following = CollectionContext.make(following_ref, type=CollectionContext.Types.UNORDERED)

actor.inbox = inbox_ref
actor.outbox = outbox_ref
actor.followers = followers_ref
actor.following = following_ref
actor.save()
```

### With Cryptographic Keys

For signing outgoing activities, create a keypair:

```python
from activitypub.models import SecV1Context

key_ref = Reference.make(f"{actor_uri}#main-key")
keypair = SecV1Context.generate(
    reference=key_ref,
    owner=actor_ref
)
```

The actor now has a public key published in its ActivityPub representation and can sign HTTP requests.

## Query Accounts

### Get Account by Subject Name

```python
account = Account.objects.get_by_subject_name("@alice@example.com")
```

### List Local Accounts

```python
local_accounts = Account.local.all()
```

This uses the `local` manager which filters for accounts on local domains.

### Get Actor from Account

```python
account = Account.objects.get(username="alice", domain__local=True)
actor = account.actor
```

### Get Account from Actor

```python
actor = ActorContext.objects.get(reference__uri=actor_uri)
account = actor.account
```

## Register Remote Accounts

Remote accounts are typically created automatically when your application receives activities from unknown actors. The toolkit resolves actor URIs, creates the necessary models, and links them.

You rarely need to create remote accounts manually, but if required:

```python
remote_domain = Domain.objects.get(name="mastodon.social")
remote_actor_uri = "https://mastodon.social/users/bob"

# This would normally happen during resolution
remote_ref = Reference.make(remote_actor_uri)
remote_actor = ActorContext.make(
    reference=remote_ref,
    type=ActorContext.Types.PERSON,
    preferred_username="bob"
)

remote_account = Account.objects.create(
    actor=remote_actor,
    domain=remote_domain,
    username="bob"
)
```

In practice, call `remote_ref.resolve()` and the toolkit handles this automatically.

## Account Properties

The `Account` model provides a computed `subject_name` property:

```python
account = Account.objects.get(username="alice", domain__local=True)
print(account.subject_name)  # @alice@example.com
```

This is also available as an annotated field when using the default manager:

```python
accounts = Account.objects.all()
for account in accounts:
    print(account._subject_name)  # Annotated field
```

## Integration with WebFinger

Once an account exists, configure your URL routing to use the built-in WebFinger view:

```python
from django.urls import path
from activitypub.views.discovery import WebFingerView

urlpatterns = [
    path('.well-known/webfinger', WebFingerView.as_view(), name='webfinger'),
]
```

Queries for `acct:alice@example.com` will now return actor information.

See [Publishing to the Fediverse](../tutorials/publishing_to_fediverse.md) for complete federation setup including WebFinger configuration.
