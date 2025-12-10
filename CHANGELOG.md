# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a
Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
