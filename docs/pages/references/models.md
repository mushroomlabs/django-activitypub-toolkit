# Model Reference

## Linked Data

These are model classes that are used to map [Linked
Data](https://www.w3.org/wiki/LinkedData) resources as Django model
Objects

::: activitypub.models.LinkedDataModel

::: activitypub.models.Reference

## ActivityStreams Vocabulary

These models are to hold the "proper" data objects that according to
[ActivityStreams](https://www.w3.org/TR/activitystreams-core/):

### Core Types

::: activitypub.models.CoreType

::: activitypub.models.Link

::: activitypub.models.BaseActivityStreamsObject

::: activitypub.models.Collection

::: activitypub.models.CollectionItem

::: activitypub.models.Object

::: activitypub.models.Actor

::: activitypub.models.Activity


### Helper / Extended attributes

Model Classes that hold data from AS types that extend the basic Object/Link attributes

::: activitypub.models.LinkRelation

::: activitypub.models.QuestionExtraData

::: activitypub.models.RelationshipProperties


## Keypair Management

The integrity of the messages being exchanged between servers rely on
cryptographically signed messages. To exchange information about keys
and who owns them, the [Security
Vocabulary](https://w3c-ccg.github.io/security-vocab/) is used by ActivityPub.

::: activitypub.models.CryptographicKeyPair
