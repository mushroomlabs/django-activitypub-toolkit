# Settings Reference

Django ActivityPub Toolkit is configured through Django settings. All configuration is placed under a `FEDERATION` dictionary in your Django settings.

## Instance Settings

### OPEN_REGISTRATIONS
- **Type**: `bool`
- **Default**: `True`
- **Description**: Whether new users can register accounts on this instance.

### DEFAULT_URL
- **Type**: `str`
- **Default**: `"http://example.com"`
- **Description**: Base URL for the federation instance.

### FORCE_INSECURE_HTTP
- **Type**: `bool`
- **Default**: `False`
- **Description**: Force HTTP URLs instead of HTTPS (for development only).

### SHARED_INBOX_VIEW
- **Type**: `str`
- **Default**: `None`
- **Description**: Django URL name for the shared inbox view.

### SYSTEM_ACTOR_VIEW
- **Type**: `str`
- **Default**: `None`
- **Description**: Django URL name for the system actor view.

### ACTIVITY_VIEW
- **Type**: `str`
- **Default**: `None`
- **Description**: Django URL name for activity views.

### OBJECT_VIEW
- **Type**: `str`
- **Default**: `None`
- **Description**: Django URL name for object views.

### COLLECTION_VIEW
- **Type**: `str`
- **Default**: `None`
- **Description**: Django URL name for collection views.

### COLLECTION_PAGE_VIEW
- **Type**: `str`
- **Default**: `None`
- **Description**: Django URL name for collection page views.

### ACTOR_VIEW
- **Type**: `str`
- **Default**: `None`
- **Description**: Django URL name for actor views.

### KEYPAIR_VIEW
- **Type**: `str`
- **Default**: `None`
- **Description**: Django URL name for keypair views.

### COLLECTION_PAGE_SIZE
- **Type**: `int`
- **Default**: `25`
- **Description**: Number of items per collection page.

## NodeInfo Settings

### SOFTWARE_NAME
- **Type**: `str`
- **Default**: `"django-activitypub"`
- **Description**: Name of the software for NodeInfo discovery.

### SOFTWARE_VERSION
- **Type**: `str`
- **Default**: `"0.0.1"`
- **Description**: Version of the software for NodeInfo discovery.

## Rate Limiting

### RATE_LIMIT_REMOTE_FETCH
- **Type**: `datetime.timedelta`
- **Default**: `timedelta(minutes=10)`
- **Description**: Rate limit for fetching remote objects.

## Message Processing

### MESSAGE_PROCESSORS
- **Type**: `list[str]`
- **Default**: Built-in processors
- **Description**: List of message processor classes to apply to incoming/outgoing messages.

## Linked Data Configuration

### DOCUMENT_RESOLVERS
- **Type**: `list[str]`
- **Default**: Built-in resolvers
- **Description**: List of document resolver classes for fetching remote content.

### AUTOLOADED_CONTEXT_MODELS
- **Type**: `list[str]`
- **Default**: Standard ActivityPub models
- **Description**: Context models automatically loaded during serialization.

### CUSTOM_SERIALIZERS
- **Type**: `dict[str, str]`
- **Default**: Built-in serializers
- **Description**: Custom serializer mappings for specific context models.

## Example Configuration

```python
FEDERATION = {
    # Instance configuration
    'OPEN_REGISTRATIONS': True,
    'DEFAULT_URL': 'https://mysocial.example.com',
    'COLLECTION_PAGE_SIZE': 50,

    # View names
    'ACTOR_VIEW': 'actor_detail',
    'ACTIVITY_VIEW': 'activity_detail',
    'OBJECT_VIEW': 'object_detail',
    'COLLECTION_VIEW': 'collection_detail',

    # NodeInfo
    'SOFTWARE_NAME': 'My Social App',
    'SOFTWARE_VERSION': '1.0.0',

    # Rate limiting
    'RATE_LIMIT_REMOTE_FETCH': timedelta(minutes=5),

    # Custom processors
    'MESSAGE_PROCESSORS': [
        'activitypub.message_processors.ActorDeletionMessageProcessor',
        'activitypub.message_processors.CompactJsonLdMessageProcessor',
        'myapp.processors.CustomProcessor',
    ],

    # Custom serializers
    'CUSTOM_SERIALIZERS': {
        'myapp.models.CustomContext': 'myapp.serializers.CustomSerializer',
    }
}
```