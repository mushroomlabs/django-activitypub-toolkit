---
hide:
  - toc
---

# How-To Guides

How-to guides are task-oriented instructions for solving specific
problems with Django ActivityPub Toolkit. Each guide assumes you have
already completed the [Getting
Started](../tutorials/getting_started.md) tutorial and have a basic
understanding of the toolkit's architecture.

## Installation and Setup

**[Install the Toolkit](install_toolkit.md)** - Step-by-step installation
instructions for adding Django ActivityPub Toolkit to your project.

**[Configure the Toolkit](configure_toolkit.md)** - Detailed configuration
options, settings, and customization for your federation setup.

**[Run Database Migrations](run_migrations.md)** - Execute and manage
database migrations required for the toolkit's models.

## Federation Tasks

**[Working with Reference-Based Relationships](reference_based_relationships.md)** - Use ReferenceField and RelatedContextField to work with federated data structures without requiring persistence.

**[Federate Existing Content](federate_existing_content.md)** - Add
federation capabilities to your existing Django models and content.

**[Handle Incoming Activities](handle_incoming_activities.md)** - Process
and respond to activities received from other Fediverse servers.

**[Send Activities](send_activities.md)** - Publish activities and content
to the Fediverse through your actor's outbox.

## Administrative Tasks

**[Register a Domain](register_domain.md)** - Create and configure
domain records for local or remote federation endpoints.

**[Register an Account](register_account.md)** - Set up ActivityPub
accounts and link them to actors for federation.

**[Block Spam and Moderate](block_spam.md)** - Manage spam prevention,
domain blocking, and content moderation tools.

## When to Use How-Tos vs Tutorials

How-to guides differ from tutorials in purpose and scope:

- **Tutorials** are learning-oriented. They guide you through building
  something complete to understand concepts.
- **How-tos** are task-oriented. They provide direct instructions for
  accomplishing a specific goal.

If you are new to the toolkit, start with the tutorials. Once you
understand the basics, use how-tos to solve specific problems as they
arise in your project.