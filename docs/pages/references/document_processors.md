# Document Processors Reference

Document processors are classes that intercept and modify ActivityPub
notifications during sending and receiving. They enable custom
processing logic for federation notifications.

## Base Class

::: activitypub.core.processors.DocumentProcessor
    options:
      heading_level: 3

## Built-in Processors

### Actor Deletion Processor

::: activitypub.core.processors.ActorDeletionDocumentProcessor
    options:
      heading_level: 3

### JSON-LD Compaction Processor

::: activitypub.core.processors.CompactJsonLdDocumentProcessor
    options:
      heading_level: 3

## Configuration

Document processors are configured in Django settings under
`FEDERATION['DOCUMENT_PROCESSORS']`. They are applied in order for
both incoming and outgoing notifications.

```python
FEDERATION = {
    'DOCUMENT_PROCESSORS': [
        'activitypub.core.processors.ActorDeletionDocumentProcessor',
        'activitypub.core.processors.CompactJsonLdDocumentProcessor',
        'myapp.processors.CustomProcessor',
    ]
}
```

## Creating Custom Processors

Create a custom document processor by subclassing `DocumentProcessor`:

```python
from activitypub.core.processors import DocumentProcessor

class CustomProcessor(DocumentProcessor):
    def process_incoming(self, document):
        # Modify incoming documents
        if document.get('type') == 'Create':
            # Custom logic for Create activities
            pass
        return document

    def process_outgoing(self, document):
        # Modify outgoing documents
        if document.get('type') == 'Like':
            # Add custom metadata
            pass
        return document
```

Register your processor in Django settings to enable it.
