from django.contrib import admin, messages

from .. import models, tasks


@admin.action(description="Fetch selected actors")
def fetch_actor(modeladmin, request, queryset):
    for actor in queryset:
        try:
            tasks.resolve_reference(actor.uri, force=True)
            messages.success(request, f"Actor {actor.uri} has been updated")
        except Exception as exc:
            messages.error(request, f"Failed to fetch {actor.uri}: {exc}")


@admin.action(description="Resolve selected references")
def resolve_references(modeladmin, request, queryset):
    successful = 0
    selected = queryset.count()
    for reference in queryset:
        try:
            reference.resolve(force=True)
            if reference.status == reference.STATUS.resolved:
                successful += 1
        except Exception as exc:
            messages.error(request, f"Failed to resolve {reference.uri}: {exc}")

    messages.success(request, f"Resolved {successful} out of {selected} selected references")


@admin.action(description="Process selected messages")
def process_messages(modeladmin, request, queryset):
    successful = 0
    for message in queryset:
        try:
            assert not message.is_processed, f"Message {message.id} is already processed"
            result = message.process()
            ok = result.result == models.MessageProcessResult.Types.OK
            assert ok, f"{result.get_result_display()} result for {message.id}"
            successful += 1
        except AssertionError as exc:
            messages.warning(request, str(exc))
        except (AssertionError, Exception) as exc:
            messages.error(request, f"Error processing {message.id}: {exc}")

    if successful:
        messages.success(request, f"Processed {successful} message(s)")


@admin.action(description="Process selected messages (Force)")
def force_process_messages(modeladmin, request, queryset):
    successful = 0
    for message in queryset:
        try:
            result = message.process(force=True)
            ok = result.result == models.MessageProcessResult.Types.OK
            assert ok, f"{result.get_result_display()} result for {message.id}"
            successful += 1
        except AssertionError as exc:
            messages.warning(request, str(exc))
        except (AssertionError, Exception) as exc:
            messages.error(request, f"Error processing {message.id}: {exc}")

    if successful:
        messages.success(request, f"Processed {successful} message(s)")


@admin.action(description="Authenticate selected messages")
def authenticate_incoming_activity_message(modeladmin, request, queryset):
    for message in queryset.filter(authenticated=True):
        messages.info(request, f"Skipping {message} because is already authenticated")

    for message in queryset.filter(authenticated=False):
        try:
            message.authenticate(fetch_missing_keys=True)
        except Exception as exc:
            messages.error(request, f"Error authenticating {message.id}: {exc}")


@admin.action(description="Execute activities")
def do_activities(modeladmin, request, queryset):
    for activity in queryset:
        try:
            activity.do()
        except Exception as exc:
            messages.error(request, f"Error running {activity.id}: {exc}")


@admin.action(description="Verify Integrity of selected messages")
def verify_message_integrity(modeladmin, request, queryset):
    successful = 0
    for message in queryset:
        try:
            for proof in message.proofs.select_subclasses():
                proof.verify(fetch_missing_keys=True)
        except AssertionError as exc:
            messages.warning(request, str(exc))
        except (AssertionError, Exception) as exc:
            messages.error(request, f"Error processing {message.id}: {exc}")
        successful += 1

    if successful:
        messages.success(request, f"Verified {successful} message(s)")
