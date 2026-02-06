---
title: Pull-Based Federation
---

Most ActivityPub servers implement a push-based architecture where
activities are delivered to inboxes and processed immediately. Django
ActivityPub Toolkit supports both push and pull patterns, with an
emphasis on pull-based access that better aligns with the vision of
the Fediverse as a shared social graph.

## Push Versus Pull

In a push-based system, when Alice posts a note, her server
immediately sends Create activities to the inboxes of all her
followers. Each recipient server processes the activity, stores the
post, and makes it available to their users. This works well for
timeline delivery but creates tight coupling between servers.

Push-based federation requires servers to maintain active knowledge of
who should receive each activity. It front-loads the work of
distribution but duplicates data across many servers. If Bob's server
is offline when Alice posts, it might never receive that post.

Pull-based federation inverts this model. Alice's server makes the
post available at a stable URI. When Bob's server needs to display
Alice's posts, it fetches them directly from her server. Nothing is
pushed to Bob's inbox unless Bob takes an explicit action like
replying.

This approach treats the Fediverse more like the web itself. Resources
have addresses. Clients fetch what they need when they need it.
Servers cache aggressively but can always refetch canonical data from
the source.

## References as Pointers

The reference-based architecture supports this model naturally. When
your application encounters a reference to a remote resource, it can
choose whether to resolve that reference immediately or defer
resolution until the data is actually needed.

An activity stream might display a list of posts with titles and
authors. You need references to those posts and their authors, but you
don't need to fetch full actor profiles until someone clicks to view a
profile page. The references are enough to construct links.

When you do need the data, calling `resolve()` on a reference triggers
a fetch from the authoritative source. The toolkit parses the returned
JSON-LD document, stores it in LinkedDataDocument, and populates the
relevant context models. Subsequent access hits the local cache.

```python
from activitypub.core.models import Reference

# Get a reference to a remote post
post_ref = Reference.objects.get(uri='https://remote.example/posts/123')

# Don't need the full data yet, just the URI for a link
link = f'<a href="{post_ref.uri}">View Post</a>'

# Now we need the actual content
if not post_ref.is_resolved:
    post_ref.resolve()

# Access cached data through context
obj = post_ref.get_by_context(ObjectContext)
content = obj.content
```

This lazy resolution pattern gives you control over network requests
and lets you optimize for your application's access patterns.

## Inbox Processing

Push-based delivery hasn't disappeared entirely. ActivityPub specifies
inboxes precisely because some activities require notification. When
someone mentions you, follows you, or replies to your post, their
server POSTs an activity to your inbox.

Django ActivityPub Toolkit handles incoming activities through the
`Notification` model. Each notification links a sender reference, a
target collection (typically an inbox), and a resource reference (the
activity being delivered).

Processing a notification involves several steps. First, authenticate
the signature to verify the sender. Then check authorization to ensure
the sender has permission to deliver to this inbox. Extract and store
the activity document. Finally, trigger any application-specific
handlers for the activity type.

```python
# Simplified notification processing flow
notification = Notification.objects.get(pk=notification_id)

# Authenticate: verify HTTP signature
notification.authenticate()

# Check if authenticated
if not notification.is_authorized:
    return

# Document is already stored from POST request
activity_ref = notification.resource
activity = activity_ref.get_by_context(ActivityContext)

# Application handles specific activity types
if activity.type == ActivityContext.Types.FOLLOW:
    handle_follow_request(activity)
elif activity.type == ActivityContext.Types.CREATE:
    handle_create_activity(activity)
```

The notification model tracks whether a message has been verified and
processed, preventing duplicate processing and enabling retry logic.

## Outbox as Canonical Source

In a pull-based model, an actor's outbox serves as the authoritative
source for their activities. Instead of pushing Create activities to
all followers, the actor's server adds the activity to the outbox
collection and lets followers pull from that collection when they need
updates.

Collections in Django ActivityPub Toolkit are first-class objects, not
just views over a queryset. An outbox collection explicitly contains
references to activities. Adding an item to a collection creates a
persistent record of membership.

```python
from activitypub.core.models import ActorContext, ActivityContext, ObjectContext

actor = ActorContext.objects.get(preferred_username='alice')

# Create a new post
post_ref = ObjectContext.generate_reference(actor.reference.domain)
post = ObjectContext.make(
    reference=post_ref,
    type=ObjectContext.Types.NOTE,
    content="Pull-based federation is interesting",
    attributed_to=actor.reference,
    published=timezone.now()
)

# Create a Create activity
activity_ref = ActivityContext.generate_reference(actor.reference.domain)
activity = ActivityContext.make(
    reference=activity_ref,
    type=ActivityContext.Types.CREATE,
    actor=actor.reference,
    object=post_ref,
    published=timezone.now()
)

# Add to actor's outbox (a CollectionContext)
outbox = actor.outbox.get_by_context(CollectionContext)
outbox.append(item=activity_ref)
```

Remote servers can fetch the outbox collection to discover new
activities. Pagination handles large outboxes efficiently, with each
page containing a subset of activities ordered by publication time.

## Hybrid Approaches

Most practical systems combine push and pull. Critical notifications
go to inboxes immediately. Bulk content discovery happens through
collection polling or pagination. User-initiated actions like
searching or viewing a profile trigger on-demand fetches.

Django ActivityPub Toolkit doesn't force you into one pattern.
Implement inbox handlers for push delivery of important activities.
Expose collections for pull-based discovery. Use reference resolution
for on-demand fetches. Choose the pattern that fits each use case.

A microblogging application might push replies and mentions to inboxes
while letting users pull timelines from followed actors' outboxes. A
forum application might push nothing but rely entirely on users
browsing to threads and pulling the latest posts.

The toolkit's architecture—references and contexts, explicit
resolution, collection management—supports whichever pattern makes
sense for your application's needs.

## Designing for Pull

When designing pull-centric applications, think about caching and
staleness. You're not receiving a stream of updates. You're fetching
on demand. How often should you refetch? How do you know when data has
changed?

ActivityPub provides some tools for this. The `updated` timestamp
indicates when an object was last modified. ETags and cache headers on
HTTP responses enable conditional requests. Collection pagination
includes timestamps to help identify new items.

Your application decides the caching strategy. A timeline view might
refetch every hour. A profile view might cache for days. Individual
posts might never be refetched unless explicitly requested.

The reference layer supports this by tracking resolution status and
timestamps. You can identify references that haven't been resolved
recently and schedule background jobs to refresh them. Or you can
refresh on access, showing cached data while triggering an async
update.

References to local resources never need resolution—the authoritative
data is already in your database. This asymmetry means local data is
always fresh while remote data requires thoughtful cache management.

## Building ON the Graph

Pull-based patterns enable the multi-application vision. Your
application doesn't need to mirror the entire social graph. It
selectively fetches the subset relevant to its purpose.

An events calendar application fetches Event objects from actors'
outboxes. A music sharing app fetches Audio and Album objects. A photo
gallery fetches Image objects. They all operate on the same actors and
use the same relationship graph, but each application curates its own
view.

This only works if resources have stable URIs and are fetchable on
demand. Push-based patterns that only deliver to inboxes can't support
clients that weren't online when the push happened. Pull-based
patterns enable time-shifted access and purpose-specific filtering.

Django ActivityPub Toolkit's architecture makes this natural.
References are stable pointers into the graph. Context models let you
work with whatever vocabulary matters to your application. Resolution
is explicit and controllable. You decide what data to cache and when
to fetch fresh copies.

The result is an application that participates in the Fediverse
without trying to replicate it entirely—a client of the social graph
rather than a silo maintaining its own copy.


Traditional ActivityPub servers mix three concerns: managing user
accounts, storing social data, and presenting that data through a
specific interface. If you want a different interface, you typically
need to migrate your entire account to a different server.

Pull-based architecture separates these concerns. Your account lives
somewhere (perhaps controlled by you, perhaps by a trusted service).
That account's data lives somewhere (again, perhaps distributed across
multiple locations). Applications fetch the data they need to present
it however they choose.

An activity tracker app doesn't need to store every post from everyone
you follow. It fetches your exercise activities and displays them in a
specialized interface. A reading list app fetches links and articles.
A photo gallery app fetches images. They all operate on the same
underlying graph without duplicating the entire dataset.
