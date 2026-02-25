# Views

The toolkit provides a set of API views for serving ActivityPub resources. These views handle JSON-LD serialization, HTTP signature authentication, and proper ActivityPub compliance.

## Core Views

### LinkedDataModelView

Base class for ActivityPub views that serve JSON-LD resources.

**Features:**
- Automatic JSON-LD serialization
- Multi-format rendering (Activity+JSON, LD+JSON)
- Request content negotiation
- Projection-based document building

**Location:** `activitypub.core.views.linked_data.LinkedDataModelView`

### RemoteReferenceProxyView

Authenticated proxy access for fetching remote ActivityPub resources. Useful for C2S implementations that cannot sign HTTP requests.

**Authentication:** Django authentication (session, token, or OAuth) instead of HTTP signatures.

**URL Pattern:** `remote/<path:resource>`

**Behavior:**
- Only returns remote resources (returns 404 for local resources)
- Only serves data from stored LinkedDataDocuments
- No transient HTTP resolution

**Use Case:** Browser-based C2S clients fetching remote ActivityPub data.

**Example:**
```python
# URL: GET /remote/https%3A%2F%2Fremote.example%2Fusers%2Fbob
# Returns full JSON-LD document from stored LinkedDataDocument
```

**Location:** `activitypub.core.views.linked_data.RemoteReferenceProxyView`

**Inherits from:** `LinkedDataModelView`

### ActivityPubObjectDetailView

Catch-all view for serving ActivityPub resources. Matches any path and attempts to resolve it as an ActivityPub object.

**Behavior:**
- Matches any path as a local resource
- Returns JSON-LD when Accept header includes ActivityPub types
- Returns 404 for non-existent resources

**Location:** `activitypub.core.views.activitystreams.ActivityPubObjectDetailView`

**Inherits from:** `LinkedDataModelView`

## Discovery Views

### HostMeta

Serves the `.well-known/host-meta` document for WebFinger discovery.

**URL:** `.well-known/host-meta`

**Location:** `activitypub.core.views.discovery.HostMeta`

### NodeInfo

Serves the `.well-known/nodeinfo` document pointing to NodeInfo endpoints.

**URL:** `.well-known/nodeinfo`

**Location:** `activitypub.core.views.discovery.NodeInfo`

### NodeInfo20

Serves the NodeInfo 2.0 schema document with server metadata.

**URLs:** `nodeinfo/2.0`, `nodeinfo/2.0.json`

**Location:** `activitypub.core.views.discovery.NodeInfo20`

### Webfinger

Serves WebFinger discovery for actor identifiers.

**URL:** `.well-known/webfinger`

**Location:** `activitypub.core.views.discovery.Webfinger`
