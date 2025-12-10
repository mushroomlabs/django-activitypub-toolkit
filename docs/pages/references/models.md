# Model Reference

Django ActivityPub Toolkit uses several categories of models to represent ActivityPub data structures, federation state, and application-specific entities.

## Core Federation Models

These models manage the fundamental entities for ActivityPub federation.

### Domains and References

::: activitypub.models.Domain
    options:
      heading_level: 4

::: activitypub.models.Reference
    options:
      heading_level: 4

::: activitypub.models.LinkedDataDocument
    options:
      heading_level: 4

### Field Types

::: activitypub.models.ReferenceField
    options:
      heading_level: 4

::: activitypub.models.RelatedContextField
    options:
      heading_level: 4

### Accounts and Actors

::: activitypub.models.Account
    options:
      heading_level: 4

::: activitypub.models.ActivityPubServer
    options:
      heading_level: 4

## ActivityStreams Context Models

These models store ActivityStreams 2.0 vocabulary data attached to references.

### Core Types

::: activitypub.models.LinkContext
    options:
      heading_level: 4

::: activitypub.models.as2.AbstractAs2ObjectContext
    options:
      heading_level: 4

::: activitypub.models.ActorContext
    options:
      heading_level: 4

::: activitypub.models.ActivityContext
    options:
      heading_level: 4

::: activitypub.models.QuestionContext
    options:
      heading_level: 4

### Collections

::: activitypub.models.CollectionContext
    options:
      heading_level: 4

::: activitypub.models.CollectionPageContext
    options:
      heading_level: 4

::: activitypub.models.CollectionItem
    options:
      heading_level: 4

### Extended Properties

::: activitypub.models.EndpointContext
    options:
      heading_level: 4

::: activitypub.models.LinkRelation
    options:
      heading_level: 4

::: activitypub.models.RelationshipProperties
    options:
      heading_level: 4

::: activitypub.models.LinkedFile
    options:
      heading_level: 4

### Reference Relationships

::: activitypub.models.fields.ReferenceRelationship
    options:
      heading_level: 4

::: activitypub.models.fields.ContextProxy
    options:
      heading_level: 4

## Social Features

::: activitypub.models.FollowRequest
    options:
      heading_level: 4
