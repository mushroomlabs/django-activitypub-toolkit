---
title: Linked Data
---


One of the key pillars of the Open Social Web is the ability for
different nodes to exchange data with each other using a common
language.

In ActivityPub, this language is defined by the
[ActivityStreams](https://www.w3.org/TR/activitystreams-core/)
vocabulary and its grammar is [Linked
Data](https://en.wikipedia.org/wiki/Linked_data), which is usually
expressed through the use of [JSON-LD](https://json-ld.org), which
itself is primarily a way to represent data according to
[RDF](https://www.w3.org/RDF/) standard.


As best explained by the author of the
[Vocata](https://codeberg.org/Vocata/vocata#technical-what-the-fediverse-really-is)
project:


> This social graph is, from an information science perspective, a
> directed graph, consisting of triple statements describing the
> relations between its nodes. The concept, as well as the technical
> implementation employed by ActivityPub, is anything but new: it is
> the well-known RDF (Resource Description Framework) graph model,
> which is also the foundation of some established standards and tools
> on the web:

> - RSS and Atom for blog and podcast feeds
> - OpenGraph meta-data for websites
> - Ontological databases like WikiData
> - ...and many more...

> In ActivityStreams, this graph structure is used to model
> relationships between Actors (users, groups, anyone who does
> something), Activities (create, update, delete, follow,…) and
> Objects (notes, attachments, events,…), all of which have unique
> IRIs (web addresses, colloquially speaking).

> If we got hold of all information from all instances on the
> Fediverse at once, it could be put together in one big, consistent
> graph.

> The role of ActivityPub is to ensure that the sub-graph an instance
> sees includes all nodes that are relevant for the actors on the
> instance. For that purpose, objects (actors and activities) can be
> pulled from other instances (using an HTTP GET request to the URI of
> the desired node), and pushed (using an HTTP POST request to a
> special node (an inbox) on another instance).

> In every pull and push, an even smaller sub-graph is transferred
> between instances, containing exactly the nodes and statements
> relevant to merge the desired object with the other instance's
> sub-graph (technically, what is transferred is the CBD (Concise
> Bounded Description) of the object).

> To conclude, ActivityPub servers keep pushing and pulling
> sub-graphs, so-called Concise Bounded Descriptions, of objects that
> are relevant for their users.

Thinking in the "formal" terms of how the data is modeled might seem
complicated at first, and this is why some of the current
implementations of ActivityPub software take a more relaxed approach
and focus exclusively on producing code that can render JSON files
that can be accepted by other servers. *However*, once one gets a
better grasp of the graph model abstraction, it's easy to realize
that the issues of data parsing and serialization are *practically
already solved* by the RDF tooling, which lets you focus in your
actual application, i.e, present that data to the end
user to achieve their goals.

### How Django ActivityPub Toolkit works with JSON-LD data

The Graph model is powerful as an abstraction, but it has certain
limitations in practical software implementations. While there are a
number of reasonably modern "Graph database" systems that could be
used to let us store and retrieve data while keeping the graph
abstraction, the more traditional "Relational Databases" are still far
more efficient, mature and have a lot more tooling support. The
relational model is also easier to work with when we want to process
data based on out of some of its attributes. E.g: it is a lot
easier/faster to make SQL queries to answer "what are the 100th to
200th items in this collection of items, if we order them by the data
they were published?" than it would ever be to do the same in a strict
graph database.

Django ActivityPub Toolkit's approach to deal with these limitations
is simple: we parse all the data using rdflib, but we convert it to a
more traditional "Django Model" class that can be saved and queried in
a relational database.


### The LinkedDataModel class

The LinkedDataModel class is an [Abstract Django
Model](https://docs.djangoproject.com/en/5.1/topics/db/models/#abstract-base-classes)
that provides the functionality of turning deserializing/serializing
between JSON-LD and the (concrete) django model represented by the
class. If you are only concerned with implementing ActivityPub
applications you won't be working with these classes directly, but if
you are working on any type of application that is going to implement
types that deal with ActivityStreams extensions (emojis, hashtags) or
rely on complete different RDF namespaces (e.g, Mastodon or Lemmy
contexts) this class will help you.

LinkedDataModels need to defined the following class attributes:

 - `NAMESPACES` represent a list of `rdflib.Namespace` instances that will be part of your context.
 - `LINKED_DATA_FIELDS` is a map of django model fields to the JSON-LD document field.


LinkedDataModel provides a `to_jsonld` method that will serialize the
model into the JSON LD model, and expand the namespace appropriately.

Let's say then you'd like to implement a model to keep track of
stickied posts, and you want to use [Lemmy](https://joinlemmy.org)'s
JSON-LD context for it.

Your model would then be something like:

```python
from rdflib import RDF, Namespace

from activitypub.schemas import AS2  # Namespace("https://www.w3.org/ns/activitystreams#")
from activitypub.models import LinkedDataModel

LEMMY = Namespace('https://join-lemmy.org/context.json')

class Comment(LinkedDataModel)
    NAMESPACES = [AS2, LEMMY]
    LINKED_DATA_FIELDS = {'type': str(RDF.type), 'is_stickied': str(LEMMY.stickied), 'content': str(AS2.content), 'published': str(AS2.published)}

    published = models.DateTimeField(auto_now_add=True)
    content = models.TextField()
    is_stickied = models.BooleanField(default=False)

    @property
    def type(self):
        return str(AS2.Note)

```

To serialize your model, it is as simple as:

```python

>>> comment = Comment(content='ActivityPub really is the future', is_sticked=True)
>>> print(comment.to_jsonld()

{
  "@context": [
    "https://join-lemmy.org/context.json",
    "https://www.w3.org/ns/activitystreams"
  ],
  "type": "Note",
  "as:content": "ActivityPub really is the future",
  "as:published": "2025-01-17T17:50:53.139662Z",
  "lemmy:stickied": true,
}

```
