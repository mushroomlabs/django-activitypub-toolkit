# Block Spam or Malicious Servers

This guide shows you how to block domains and servers that send unwanted or malicious ActivityPub activities.

## Domain Blocking

Block entire domains to prevent any federation with them:

```python
from activitypub.models import Domain

# Block a domain
blocked_domain = Domain.objects.create(
    name="spam.example",
    local=False,
    blocked=True
)
```

Once blocked, the toolkit will automatically reject all incoming activities from actors on that domain.

## Check Domain Status

Query blocked domains:

```python
# Get all blocked domains
blocked_domains = Domain.objects.filter(blocked=True)

# Check if a specific domain is blocked
domain = Domain.objects.get(name="suspicious.example")
if domain.blocked:
    print("Domain is blocked")
```

## Block Domains in Admin

Use Django admin to manage blocked domains:

```python
# In admin.py
from django.contrib import admin
from activitypub.models import Domain

@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ('name', 'local', 'blocked')
    list_filter = ('local', 'blocked')
    search_fields = ('name',)
```

## Automatic Blocking

Implement automatic blocking based on activity patterns:

```python
from activitypub.signals import activity_received

@receiver(activity_received)
def check_for_spam(sender, activity, **kwargs):
    """Automatically block domains that send spam."""
    sender_domain = activity.sender.domain
    
    # Check for spam patterns
    if is_spam_activity(activity):
        sender_domain.blocked = True
        sender_domain.save()
        logger.warning(f"Blocked domain {sender_domain.name} for spam")
```

## Content-Based Blocking

Block activities based on content:

```python
def should_block_activity(activity):
    """Check if activity should be blocked."""
    obj = activity.object.get_by_context(ObjectContext)
    
    # Block based on content
    if obj and 'spam' in obj.content.lower():
        return True
    
    # Block based on actor reputation
    if activity.actor.domain.blocked:
        return True
    
    return False

@receiver(activity_processed)
def block_spam_activities(sender, activity, **kwargs):
    if should_block_activity(activity):
        # Don't process the activity
        return
    # Process normally
```

## Rate Limiting

Implement rate limiting to prevent abuse:

```python
from django.core.cache import cache

def check_rate_limit(domain_name, max_requests=100, window=3600):
    """Check if domain has exceeded rate limit."""
    cache_key = f"domain_requests_{domain_name}"
    request_count = cache.get(cache_key, 0)
    
    if request_count >= max_requests:
        return False  # Block
    
    cache.set(cache_key, request_count + 1, window)
    return True

@receiver(activity_received)
def rate_limit_domains(sender, activity, **kwargs):
    domain_name = activity.sender.domain.name
    
    if not check_rate_limit(domain_name):
        activity.sender.domain.blocked = True
        activity.sender.domain.save()
        logger.warning(f"Rate limited and blocked domain {domain_name}")
```

## User-Level Blocking

Allow users to block specific actors:

```python
class UserBlock(models.Model):
    """User-specific blocks."""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    blocked_actor = models.ForeignKey(Reference, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

@receiver(activity_processed)
def filter_blocked_actors(sender, activity, **kwargs):
    """Filter out activities from user-blocked actors."""
    # Check if any local user has blocked this actor
    blocked_by_users = UserBlock.objects.filter(
        blocked_actor=activity.actor
    ).exists()
    
    if blocked_by_users:
        # Don't deliver to blocked users
        return
```

## Moderation Queue

Implement a moderation queue for suspicious activities:

```python
class ModerationQueue(models.Model):
    """Activities requiring moderation."""
    activity_reference = models.OneToOneField(Reference, on_delete=models.CASCADE)
    reason = models.CharField(max_length=200)
    moderator = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    approved = models.BooleanField(null=True)  # True=approved, False=rejected, None=pending
    created_at = models.DateTimeField(auto_now_add=True)

@receiver(activity_processed)
def moderate_suspicious_activities(sender, activity, **kwargs):
    if is_suspicious(activity):
        ModerationQueue.objects.create(
            activity_reference=activity.reference,
            reason="Suspicious content"
        )
        # Don't process until moderated
        return
    
    # Process normally
```

## Server-Level Blocking

Block at the server level for extreme cases:

```python
# Block all activities from a server
FEDERATION = {
    # ... other settings ...
    'BLOCKED_SERVERS': [
        'badserver.example',
        'spamnetwork.org',
    ],
}
```

## Monitoring and Alerts

Set up monitoring for blocked domains:

```python
def send_block_alert(domain):
    """Send alert when domain is blocked."""
    # Send email, Slack notification, etc.
    send_notification(
        f"Domain {domain.name} has been blocked",
        f"Reason: {domain.block_reason}"
    )

# Extend Domain model
class Domain(models.Model):
    # ... existing fields ...
    block_reason = models.TextField(blank=True)
    
    def block(self, reason=""):
        self.blocked = True
        self.block_reason = reason
        self.save()
        send_block_alert(self)
```

## Unblocking Domains

Provide a way to unblock domains:

```python
def unblock_domain(domain_name):
    """Unblock a previously blocked domain."""
    try:
        domain = Domain.objects.get(name=domain_name, blocked=True)
        domain.blocked = False
        domain.block_reason = ""
        domain.save()
        logger.info(f"Unblocked domain {domain_name}")
    except Domain.DoesNotExist:
        logger.warning(f"Domain {domain_name} not found or not blocked")
```

## Best Practices

- **Start permissive**: Block only when necessary
- **Monitor patterns**: Look for abuse trends
- **Document reasons**: Keep records of why domains were blocked
- **Regular review**: Periodically review and unblock legitimate domains
- **User control**: Allow users to block individual actors
- **Graduated response**: Use warnings before blocking

## Testing Blocks

Test that blocking works:

```bash
# Try to send activity from blocked domain
curl -X POST http://localhost:8000/users/username/inbox \
  -H "Content-Type: application/activity+json" \
  -d '{"type": "Like", "actor": "https://blocked.example/user", ...}'

# Should receive rejection
```

Blocking helps maintain a healthy federated community while protecting your users from spam and abuse.