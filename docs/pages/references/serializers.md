---
title: Serializers Reference
---

Serializers handle conversion of server metadata to standard formats for discovery protocols.

## NodeInfo Serializer

The NodeInfoSerializer provides server metadata following the NodeInfo protocol specification. This enables other servers and applications to discover information about your instance.

```python
from activitypub.serializers import NodeInfoSerializer

serializer = NodeInfoSerializer(instance=server_instance)
nodeinfo_data = serializer.data
```

The NodeInfo protocol defines a standard format for exposing instance metadata including:

- Software name and version
- Protocols supported
- Usage statistics (users, posts, comments)
- Registration status
- Content policies

Remote servers and monitoring services use NodeInfo to discover and catalog Fediverse instances.

### NodeInfo Endpoints

The toolkit automatically provides NodeInfo discovery endpoints:

- `/.well-known/nodeinfo` - Discovery endpoint listing available NodeInfo versions
- `/nodeinfo/2.0` - NodeInfo 2.0 format
- `/nodeinfo/2.1` - NodeInfo 2.1 format (if supported)

Configure NodeInfo in your settings:

```python
FEDERATION = {
    'SOFTWARE_NAME': 'MyApp',
    'SOFTWARE_VERSION': '1.0.0',
    'OPEN_REGISTRATIONS': True,
    # Additional metadata...
}
```

The serializer automatically aggregates usage statistics from your database and formats them according to the NodeInfo specification.
