---
title: Domains
---

The `Domain` model is used to:

 - Keep track of what type of software is running on remote servers
   via the [Nodeinfo](https://nodeinfo.diaspora.software/) standard.
 - Provide a [shared
   inbox](https://w3c.github.io/activitypub/#shared-inbox-delivery)
   for the local domains hosted on our server.
 - Generate instances of the [ActivityPub models](./activitypub) with
   a proper reference.

## Nodeinfo

The method `get_nodeinfo` queries first the `.well-known/nodeinfo`
url to find which version of the standard the server is using, as well
what is the final endpoint to be queried.

```python

>>> from activitypub.models import Domain

>>> # Convenience method that parses and gets domain based on hostname
>>> mastodon_social = Domain.make('https://mastodon.social')

>>> mastodon_social.get_nodeinfo()

>>> print(mastodon_social.get_software_family_display())

'mastodon'

```


## Generating ActivityPub objects with proper id

Django `reverse` method only generates the path of any URL that
matches the url pattern provided. To get the full URI, django requires
the request object. Given that we might be generating these objects
outside of the request cycle, `reverse_view` provides a convenience
method that can generate an absolute URI for you.

Let's say that your application has an [custom endpoint for
posts](./application_settings), which has the url_pattern
`/posts/<str:pk>` with the `ap:post-detail` view name.

```
>>> from activitypub.models import Domain, Object, generate_ulid

>>> domain = Domain.make('https://myserver.example.com')
>>> object_id = generate_ulid()  # ids are ULIDs for all ActivityPub models
>>> print(object_id)

'01JG2YRA8XFQMXG366HEA71PS6'

>>> print(domain.reverse_view('ap:post_detail', pk=object_id))
'https://myserver.example.com/posts/01JG2YRA8XFQMXG366HEA71PS6'
```

The reverse_view method only generates the URL. You will still need to
save assign it as the id to any object that you want to create. To
simplify this, the build methods (build_object, build_activity,
build_collection) can be used. For example:


```python
>>> from activitypub.models import Domain, Object, generate_ulid
>>> domain = Domain.make('https://myserver.example.com')
>>> my_note = domain.build_object(type=Object.Types.NOTE, name='This is a test note', id=object_id)

>>> print(my_note.id)

'01JJ0P2RK8HAGSHYBGHTAS549F'

>>> print(my_note.uri)  # uri is a property that returns the URI of the associated reference
'https://myserver.example.com/posts/01JJ0P2RK8HAGSHYBGHTAS549F'

```


## Shared Inboxes

```
from activitypub.models import Account, Actor, Collection, Domain

>>> domain = Domain.get_default()
>>> instance_actor_uri = domain.reverse_view("my-app:system-actor")
>>> user_actor_uri = domain.reverse_view("my-app:user-actor-detail", pk="alice")
>>> shared_inbox_uri = domain.reverse_view("my-app:system-shared-inbox")

>>> system_actor = Actor.make(
        uri=instance_actor_uri,
        type=Actor.Types.APPLICATION,
        preferred_username=domain.name,
        shared_inbox=Collection.make(
            uri=shared_inbox_uri, name=f"{domain.name}'s Shared Inbox"
    ))

>>> user_actor = Actor.make(
        uri=user_actor_uri,
        type=Actor.Types.PERSON,
        preferred_username="alice",
        shared_inbox=domain.shared_inbox
    ))

```


This would create two actors: one for the instance and another for
alice. They would both have the same collection as shared_inbox.
