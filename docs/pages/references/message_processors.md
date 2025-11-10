# Message Processors Reference

Message processors are classes that intercept and modify ActivityPub messages during sending and receiving. They enable custom processing logic for federation messages.

## Base Class

::: activitypub.message_processors.MessageProcessor
    options:
      heading_level: 3

## Built-in Processors

### Actor Deletion Processor

::: activitypub.message_processors.ActorDeletionMessageProcessor
    options:
      heading_level: 3

### JSON-LD Compaction Processor

::: activitypub.message_processors.CompactJsonLdMessageProcessor
    options:
      heading_level: 3

## Configuration

Message processors are configured in Django settings under `FEDERATION['MESSAGE_PROCESSORS']`. They are applied in order for both incoming and outgoing messages.

```python
FEDERATION = {
    'MESSAGE_PROCESSORS': [
        'activitypub.message_processors.ActorDeletionMessageProcessor',
        'activitypub.message_processors.CompactJsonLdMessageProcessor',
        'myapp.processors.CustomProcessor',
    ]
}
```

## Creating Custom Processors

Create a custom message processor by subclassing `MessageProcessor`:

```python
from activitypub.message_processors import MessageProcessor

class CustomProcessor(MessageProcessor):
    def process_incoming(self, document):
        # Modify incoming messages
        if document.get('type') == 'Create':
            # Custom logic for Create activities
            pass
        return document

    def process_outgoing(self, document):
        # Modify outgoing messages
        if document.get('type') == 'Like':
            # Add custom metadata
            pass
        return document
```

Register your processor in Django settings to enable it.