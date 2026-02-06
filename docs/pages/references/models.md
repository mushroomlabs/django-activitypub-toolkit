# Model Reference

Django ActivityPub Toolkit uses several categories of models to represent ActivityPub data structures, federation state, and application-specific entities.

## Core Federation Models

These models manage the fundamental entities for ActivityPub federation.

### Domains and References

::: activitypub.core.models.Domain
    options:
      heading_level: 4

::: activitypub.core.models.Reference
    options:
      heading_level: 4

::: activitypub.core.models.LinkedDataDocument
    options:
      heading_level: 4

::: activitypub.core.models.ActivityPubServer
    options:
      heading_level: 4

### Field Types

::: activitypub.core.models.ReferenceField
    options:
      heading_level: 4

::: activitypub.core.models.RelatedContextField
    options:
      heading_level: 4

### Identity and User Domain

::: activitypub.core.models.Identity
    options:
      heading_level: 4

::: activitypub.core.models.UserDomain
    options:
      heading_level: 4

## ActivityStreams Context Models

These models store ActivityStreams 2.0 vocabulary data attached to references.

### Core Types

::: activitypub.core.models.LinkContext
    options:
      heading_level: 4

::: activitypub.core.models.as2.AbstractAs2ObjectContext
    options:
      heading_level: 4

::: activitypub.core.models.ActorContext
    options:
      heading_level: 4

::: activitypub.core.models.ActivityContext
    options:
      heading_level: 4

::: activitypub.core.models.QuestionContext
    options:
      heading_level: 4

### Collections

::: activitypub.core.models.CollectionContext
    options:
      heading_level: 4

::: activitypub.core.models.CollectionPageContext
    options:
      heading_level: 4

::: activitypub.core.models.CollectionItem
    options:
      heading_level: 4

### Extended Properties

::: activitypub.core.models.EndpointContext
    options:
      heading_level: 4

::: activitypub.core.models.LinkRelation
    options:
      heading_level: 4

::: activitypub.core.models.RelationshipProperties
    options:
      heading_level: 4

::: activitypub.core.models.LinkedFile
    options:
      heading_level: 4

### Reference Relationships

::: activitypub.core.models.fields.ReferenceRelationship
    options:
      heading_level: 4

::: activitypub.core.models.fields.ContextProxy
    options:
      heading_level: 4

## Social Features

::: activitypub.core.models.FollowRequest
    options:
      heading_level: 4
