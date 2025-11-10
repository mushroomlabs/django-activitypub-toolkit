---
title: Tutorials
---

Tutorials provide hands-on, step-by-step guides to building
ActivityPub applications with Django ActivityPub Toolkit. Each
tutorial teaches core concepts through practical examples, building
complete working applications from scratch.

## Getting Started

Start here if you are new to the toolkit. This tutorial builds a
federated journal application where users write entries and share them
across the Fediverse. You will learn the reference-first architecture,
how context models work, and the fundamentals of ActivityPub
federation.

Best for: Developers building their first ActivityPub application or
wanting to understand the toolkit's design principles.

## Creating Custom Context Models

Learn to extend the toolkit with custom vocabularies. This tutorial
shows how to handle platform-specific extensions like Mastodon's
features and how to create entirely new vocabularies for specialized
domains. You will implement context models, register them for
automatic processing, and query across multiple vocabularies.

Best for: Developers integrating with existing Fediverse platforms or
building applications with domain-specific data models.

## Handling Incoming Activities

Implement the server-to-server (S2S) receive side of federation. This
tutorial covers inbox endpoints, authentication via HTTP Signatures,
notification processing, and activity handlers. You will process
Follow, Like, Create, and Announce activities, updating your
application state based on federated actions.

Best for: Developers who need their applications to respond to actions
from remote servers and users.

## Publishing to the Fediverse

Implement the server-to-server (S2S) send side of federation. This
tutorial covers creating activities, managing collections like
outboxes and followers, addressing for delivery, and WebFinger
discovery. You will make your content visible to followers across the
Fediverse.

Best for: Developers who need their users' content and actions to
federate to other servers.

## Building a Generic ActivityPub Server

Build a protocol-level server that implements both Client-to-Server
(C2S) and Server-to-Server (S2S) APIs. This tutorial creates a generic
server using only the toolkit's context models, supporting OAuth
authentication for clients and any ActivityStreams object type.
Multiple clients can use the same server for different purposes.

Best for: Developers building ActivityPub infrastructure, creating
servers for multiple client applications, or implementing the full
ActivityPub specification including C2S.

## Tutorial Progression

The first four tutorials build on each other, progressively adding
federation capabilities to a journal application. The fifth tutorial
demonstrates an alternative architecture for generic servers. Work
through them in order for the best learning experience, or jump to
specific tutorials based on your needs.
