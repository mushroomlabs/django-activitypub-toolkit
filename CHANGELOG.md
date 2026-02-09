# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a
Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Domain-based authority validation with clear separation of concerns
- `LinkedDataDocument.sanitize_graph()` for domain filtering and blank node skolemization
- `AbstractContextModel.validate_graph()` for context-specific validation
- `DocumentValidationError` exception for invalid documents
- C2S validation: generates proper IDs for blank node objects in Create activities
- S2S validation: prevents impersonation attacks via attributedTo domain checks

### Changed
- **BREAKING**: `should_handle_reference()` signature changed to `(g, reference)` - removed `source` parameter
- **BREAKING**: Removed `Reference.trusts` ManyToManyField and `Reference.has_authority_over()` method
- Refactored validation architecture with three distinct phases:
  1. **Sanitization** (`sanitize_graph`): Domain filtering + skolemization (universal)
  2. **Validation** (`validate_graph`): Security and business logic checks (context-specific)
  3. **Type Matching** (`should_handle_reference`): Pure type/content matching (assumes validated data)
- `LinkedDataDocument.load()` now validates all documents and rejects invalid content completely
- S2S inbox accepts requests (202) but rejects invalid documents during async processing
- C2S outbox validates synchronously and returns 400 for invalid requests
- `should_handle_reference()` default implementation now returns `False` instead of `True`
- (Lemmy Adapter) New aggregate models for tracking counts and rankings:
  - `ReactionCount` for tracking upvotes/downvotes on content
  - `RankingScore` for computing Hot, Active, Controversy, and Scaled rankings
  - `UserActivity` for tracking active users over time periods
  - `FollowerCount` for tracking subscriber counts (total and local)
  - `SubmissionCount` for tracking post/comment counts per reference

### Removed
- `Reference.trusts` ManyToManyField (domain-based authority replaces trust relationships)
- `Reference.has_authority_over()` method (replaced by domain filtering in `sanitize_graph`)
- Authority/security checks from `should_handle_reference()` implementations

### Fixed
- Add missing 'next' field to projections on Collection pages

## [0.2.0] - 2026-02-06

### Added
- Integrated Lemmy Adapter API (optional) at activitypub.adapters.lemmy
- Added OAuth support (optional) on activitypub.extras.oauth
  - Identity-scoped access tokens linking OAuth tokens to specific actors
  - Custom ActivityPub OIDC claims for actor information
  - Identity selection during authorization flow
- Implemented proper authentication for actor outbox access.
- Added strict checks to prevent processing untrusted content.
- Identity system for linking Django users to ActivityPub actors
  - Support for multiple identities per user
  - Primary identity designation for default operations
  - `ActorUsernameAuthenticationBackend` for actor-based login
  - `ActorMiddleware` for automatic actor attachment to requests
  - `UserDomain` model for user-controlled domain management
- Projection system for controlling JSON-LD presentation and access control
  - `ReferenceProjection` base class with declarative Meta configuration
  - Built-in projections for actors, collections, notes, and questions
  - Support for field allowlists, denylists, and computed fields
  - Automatic context tracking and JSON-LD compaction
  - Viewer-scoped access control via `scope` parameter
  - `@use_context` decorator for registering required contexts
- Added `redirects_to` field to Reference model for URL redirections

### Changed
- activitypub package now is moved to activitypub.core namespace
- Actor collections are not exclusive, allowing more flexible collection management.
- fetch_nodeinfo is no longer automatically called after remote domain is created
- Plenty of improvements in the admin, to allow easier filtering and searching of records
- Improved reference resolution management logic.
- Updated authentication and authorization documentation to cover both local user authentication (Identity system) and remote actor authentication (HTTP Signatures).
- Rewrote standalone server tutorial to use built-in Identity system and OAuth package instead of custom models, removed custom admin interface section in favor of built-in IdentityAdmin.

### Fixed
- LinkedDataDocument.load() was not checking for domain authority before updating references


## [0.1.6] - 2025-12-14

### Added

- Admin interfaces for Reference, LinkedDataDocument, and BaseAs2ObjectContext models
- `document_loaded` signal for tracking document processing
- `webfinger_lookup` task for resolving ActivityPub actors via WebFinger
- `as_rdf` property to Reference model for RDF operations

### Changed

- Optimized context loading by moving CONTEXTS_BY_URL creation to avoid global state
- Updated SCHEMA namespace from HTTPS to HTTP
- Refactored ActorContext model by removing secv1 field
- Improved ReferenceField and ReferenceRelationship models with cleaner code
- Enhanced LinkedDataDocument loading with better filtering and signal emission
- Updated admin configurations with improved list displays and filters
- Fixed SecV1Context to use correct `private_key_pem` field name
- Improved HttpDocumentResolver signing key retrieval
- Cleaned up test cases by removing RelatedContextField tests

### Fixed

- Better error handling in Reference.make() method for invalid domains
- Improved reference field handling in graph loading

## [0.1.4] - 2025-12-08


### Added

- `ReferenceField`: New field type for managing many-to-many
  relationships based on ActivityPub references without data
  persistence, enabling relationship management on unsaved model
  instances
- `RelatedContextField`: New field type for lazy navigation between
  context models using `ContextProxy`
- `ReferenceRelationship`: Base model for all ReferenceField through
  tables with proper reference-based foreign keys
- Comprehensive documentation for reference-based relationships in
  topics guide
- How-to guide for working with `ReferenceField` and
  `RelatedContextField`
- API reference documentation for new field types and related classes
- Support for configurable test fixture paths


### Changed

- Migrated all reference-based relationships to use `ReferenceField`
  instead of traditional many-to-many fields
- Updated `activitypub/models/fields.py` with complete implementation
  of reference-based field system
- Regenerated initial migration (`0001_initial.py`) to include 39
  through models for concrete classes
- Enhanced reference context architecture documentation with
  federation-first design principles
- Reorganized documentation structure to better separate conceptual
  topics from practical guides

### Fixed

- Through models now correctly use `source_reference_id →
  target_reference_id` structure instead of direct model foreign keys
- Through models no longer created for abstract base classes
- Signal handlers (`m2m_changed`) now properly triggered for
  `ReferenceField` operations
- Django migrations now correctly track dynamically created through
  models

## [0.1.3] - 2025-12-08

### Added

- Context definitions and serializer/framing refactor
- Serializer fields for adapting data from context models
- Language model with enum containing top 25 languages
- Test fixture for PieFed integration

### Changed

- Updated documentation for context-based architecture

### Fixed

- `SecV1Context.generate_keypair` implementation

## [0.1.2] - 2024-12-01

### Changed

- Updated documentation
- Updated README

## [0.1.1] - 2024-11-28

### Fixed

- Missing subpackages in distribution

### Changed

- Cleaned up CI/CD workflows

## [0.1.0] - 2024-11-27

### Added

- Support for `as:source` property
- Support for Lemmy schema extensions
- Comprehensive documentation updates
- Tutorial for integrating with existing Django projects
- Celery app configuration for tests
- PeerTube fixture file for integration testing
- CollectionPage model
- Shares and likes collections
- Follow request handling with proper approval workflow
- Support for `inReplyTo` field
- Items to shares/likes collections for non-remote actors
- CollectionMixin.remove(item) method
- Replies/shares/likes collection for every local object
- Ruff linting support

### Changed

- Migrated from poetry to uv for dependency management
- Removed PostgreSQL as hard dependency
- Updated Django to latest version
- Improved rendering of `as:url` field
- Improved deserialization of tags as sent by Mastodon
- Switched back to URI fragment representation for keys
- Removed special casing for representation of collections and
  collection pages

### Fixed

- Improved ActivityPub API compliance
- Various fixes for federation compatibility

### Removed

- Admin interface for BaseObject
- poetry.lock file
- PostgreSQL dependency

## [0.0.2] - 2024-10-15

### Added

- Initial working implementation
- Basic ActivityPub server-to-server support
- HTTP signature verification
- WebFinger discovery
- Django REST Framework integration

### Changed

- Core architecture improvements
