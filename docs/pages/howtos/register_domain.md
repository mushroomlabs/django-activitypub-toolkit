# Register a Domain

This guide shows you how to create and manage `Domain` records using Django's admin interface or shell.

## When You Need This

You need to register a domain in two scenarios:

1. **Local domain** - Your application's own domain that hosts ActivityPub actors.
2. **Remote domain** - A federation peer's domain you want to track or block.

## Register Your Local Domain

Your application needs exactly one local domain. This is typically done during initial setup or deployment.

### Using Django Admin

Navigate to the Domains section in Django admin and create a new domain record:

- **Name**: Your domain name (e.g., `example.com`)
- **Local**: Check this box
- **Blocked**: Leave unchecked

### Using Django Shell

```python
from activitypub.core.models import Domain

local_domain = Domain.objects.create(
    name="example.com",
    local=True,
    blocked=False
)
```

The domain's `url` property automatically constructs the full URL using the configured scheme from settings (defaults to `https`).

## Register a Remote Domain

Remote domains represent federation peers. The toolkit automatically creates remote domain records when it encounters actors or activities from unknown domains, but you can manually register them to set specific policies.

### Block a Domain

To prevent all federation with a specific domain:

```python
from activitypub.core.models import Domain

blocked_domain = Domain.objects.create(
    name="spam.example",
    local=False,
    blocked=True
)
```

Any incoming activities from actors on blocked domains will be rejected automatically.

### Allow a Specific Domain

To ensure a domain is allowed (explicitly not blocked):

```python
from activitypub.core.models import Domain

trusted_domain, created = Domain.objects.get_or_create(
    name="mastodon.social",
    defaults={"local": False, "blocked": False}
)
```

## Query Domains

### List All Local Domains

```python
local_domains = Domain.objects.filter(local=True)
```

Your application should have exactly one local domain.

### List Blocked Domains

```python
blocked_domains = Domain.objects.filter(blocked=True)
```

### Check If a Domain Is Blocked

```python
domain = Domain.objects.get(name="suspicious.example")
if domain.blocked:
    print("This domain is blocked")
```

## Domain Properties

Each `Domain` instance provides these properties:

- **`url`** - Full URL including scheme (e.g., `https://example.com`)
- **`netloc`** - Network location (domain name only)
- **`local`** - Boolean indicating if this is your application's domain
- **`blocked`** - Boolean indicating if federation with this domain is blocked

## Automatic Discovery

When the toolkit encounters a new remote domain, it can automatically fetch server metadata using NodeInfo. This happens through the `ActivityPubServer` model which links to a domain:

```python
from activitypub.core.models import ActivityPubServer

server = ActivityPubServer.objects.create(domain=remote_domain)
server.get_nodeinfo()  # Fetches and stores software info
```

The server record tracks software family, version, and other metadata useful for handling federation quirks.

## Integration with Actors

Domains link to actors through the reference system. Each actor's `Reference` object stores the domain information, which is used for WebFinger discovery and federation routing. The `ActorAccount` model provides authentication capabilities and links directly to an `ActorContext`, with the domain information accessible through the actor's reference.
