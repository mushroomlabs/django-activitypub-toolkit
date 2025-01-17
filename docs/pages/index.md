## Django ActivityPub Toolkit

Django ActivityPub Toolkit is a pluggable django application that
focus solely on implementing the ActivityPub API. It is meant to be
used by developers that want to integrate with the Fediverse, rather
than providing an specific use-case.

Currently, ActivityPub is known mostly as the protocol that powers the
"Fediverse", which is loosely described as "a constellation of social
media platforms operating independently". While this is without a
doubt an improvement over the status quo of "Walled Gardens" created
by big tech companies, this approach is still limiting to users, who:

 - are bound to an specific presentational layer.
 - still are not in control of their cryptographic keys, which means
that all interactions with the Social Web have to be mediated by the
server.
 - are never in real control of their online identity

The goal of this project is to build more advanced applications
powered by ActivityPub and bring back an open **web** where clients
can act as fully autonomous nodes whenever possible.

## Related Work

 - [Vocata](https://codeberg.org/Vocata/vocata) as main inspiration
   and showing that it is possible to work with the concept of "The
   Fediverse" as a global shared graph.
 - [Takahē](https://jointakahe.org/) for being the first ActivityPub
   server designed to serve multiple domains from the same
   installation.
