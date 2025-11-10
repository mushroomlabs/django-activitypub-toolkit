# Configure the Toolkit

This guide shows you how to configure the Django ActivityPub Toolkit for your specific needs.

## Basic Configuration

After installation, add federation settings to your Django `settings.py`:

```python
FEDERATION = {
    'DEFAULT_URL': 'https://yourdomain.com',
    'SOFTWARE_NAME': 'YourAppName',
    'SOFTWARE_VERSION': '1.0.0',
}
```

### Required Settings

- **`DEFAULT_URL`**: Your server's base URL (must include protocol)
- **`SOFTWARE_NAME`**: Name of your application
- **`SOFTWARE_VERSION`**: Version of your application

## View Configuration

Configure URL patterns for federation endpoints:

```python
FEDERATION = {
    # ... basic settings ...
    'ACTOR_VIEW': 'myapp:user-actor',
    'OBJECT_VIEW': 'myapp:post-detail',
    'COLLECTION_VIEW': 'myapp:user-outbox',
}
```

These settings tell the toolkit which Django URL names to use when generating URIs for:
- `ACTOR_VIEW`: Actor profiles
- `OBJECT_VIEW`: Content objects (posts, articles, etc.)
- `COLLECTION_VIEW`: Collections (outboxes, followers, etc.)

## Context Model Configuration

Specify which context models to load automatically:

```python
FEDERATION = {
    # ... other settings ...
    'AUTOLOADED_CONTEXT_MODELS': [
        'activitypub.models.ObjectContext',
        'activitypub.models.ActorContext',
        'activitypub.models.ActivityContext',
        'myapp.models.CustomContext',  # Your custom models
    ],
}
```

The toolkit includes standard ActivityStreams models by default. Add your custom context models for specialized vocabularies.

## Collection and Pagination

Control collection behavior:

```python
FEDERATION = {
    # ... other settings ...
    'COLLECTION_PAGE_SIZE': 25,  # Items per page
}
```

This affects how many items appear in paginated collection responses.

## Rate Limiting

Configure remote resource fetching:

```python
FEDERATION = {
    # ... other settings ...
    'RATE_LIMIT_REMOTE_FETCH': 600,  # Seconds between refetches
}
```

This prevents excessive requests to remote servers for the same resource.

## Document Resolvers

Customize how remote documents are fetched:

```python
FEDERATION = {
    # ... other settings ...
    'DOCUMENT_RESOLVERS': [
        'activitypub.resolvers.ConstantDocumentResolver',  # For testing
        'activitypub.resolvers.HttpDocumentResolver',      # Default HTTP fetcher
        'myapp.resolvers.CustomResolver',                  # Your custom resolver
    ],
}
```

Resolvers are tried in order until one successfully fetches a document.

## Message Processors

Add middleware for incoming and outgoing activities:

```python
FEDERATION = {
    # ... other settings ...
    'MESSAGE_PROCESSORS': [
        'activitypub.message_processors.ActorDeletionMessageProcessor',
        'activitypub.message_processors.CompactJsonLdMessageProcessor',
        'myapp.processors.SpamFilterProcessor',
    ],
}
```

Processors can modify, validate, or reject messages.

## Custom Serializers

Map context models to custom serializers:

```python
FEDERATION = {
    # ... other settings ...
    'CUSTOM_SERIALIZERS': {
        'activitypub.models.CollectionContext': 'myapp.serializers.CustomCollectionSerializer',
        'myapp.models.CustomContext': 'myapp.serializers.CustomContextSerializer',
    },
}
```

Use this for specialized JSON-LD serialization requirements.

## Development vs Production

### Development Settings

```python
FEDERATION = {
    'DEFAULT_URL': 'http://localhost:8000',
    'SOFTWARE_NAME': 'MyApp (Dev)',
    'SOFTWARE_VERSION': 'dev',
    'FORCE_INSECURE_HTTP': True,  # Allow HTTP for local development
}
```

### Production Settings

```python
FEDERATION = {
    'DEFAULT_URL': 'https://myapp.com',
    'SOFTWARE_NAME': 'MyApp',
    'SOFTWARE_VERSION': '1.2.3',
    'FORCE_INSECURE_HTTP': False,  # Always False in production
}
```

## Testing Configuration

For testing, you might want to disable remote fetching:

```python
FEDERATION = {
    # ... settings ...
    'DOCUMENT_RESOLVERS': [
        'activitypub.resolvers.ConstantDocumentResolver',  # Only use test fixtures
    ],
}
```

## Configuration Validation

The toolkit validates your configuration on startup. Common errors:

- Missing `DEFAULT_URL`
- Invalid URL format for `DEFAULT_URL`
- Non-existent view names in view settings
- Invalid Python paths in model/resolver lists

Check your Django logs for configuration errors during startup.

## Next Steps

With configuration complete, you can:
- [Install the Toolkit](install_toolkit.md) if not done
- Run migrations to create database tables
- Start building your federated application

See the [Integration with Existing Projects](../tutorials/integration_with_existing_project.md) tutorial for a complete example.