# Run Database Migrations

This guide shows you how to run the database migrations required for the Django ActivityPub Toolkit.

## Prerequisites

You must have:
- Installed the Django ActivityPub Toolkit
- Added it to your `INSTALLED_APPS`
- Configured basic federation settings

## Run Migrations

Execute the standard Django migration commands:

```bash
python manage.py migrate activitypub
```

This command creates all necessary database tables for federation functionality.

## What Gets Created

The migration creates tables for:

- **References**: URI-based pointers to resources (local and remote)
- **LinkedDataDocuments**: Cached JSON-LD documents from remote servers
- **Context models**: ActivityStreams vocabulary data storage
- **Notifications**: Incoming activity delivery tracking
- **Domains**: Server/domain management
- **Accounts**: User account to ActivityPub actor mapping
- **Collections**: Lists like inboxes, outboxes, followers
- **Signatures**: Cryptographic proof storage

## Migration Safety

The toolkit's migrations are designed to be safe:

- **Non-destructive**: Existing data is preserved
- **Reversible**: You can rollback if needed
- **Compatible**: Works with existing Django migrations

## Post-Migration Steps

After running migrations:

1. **Create domains**: Set up your local domain record
2. **Create actors**: Link user accounts to ActivityPub actors
3. **Configure URLs**: Set up federation endpoints
4. **Test installation**: Verify everything works

## Troubleshooting

### Migration Fails

If migrations fail:

- Check Django version compatibility (4.2.23+)
- Ensure database permissions allow table creation
- Verify no conflicting table names exist

### Rollback Needed

To rollback federation migrations:

```bash
python manage.py migrate activitypub zero
```

This removes all federation tables but preserves your application data.

## Next Steps

With migrations complete, you can:

- [Configure the Toolkit](configure_toolkit.md) with detailed settings
- Start building federated features in your application
- Follow the [Getting Started](../tutorials/getting_started.md) tutorial
