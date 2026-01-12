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


@admin.action(description="Process selected notifications")
def process_notifications(modeladmin, request, queryset):
    successful = 0
    for notification in queryset:
        try:
            assert not notification.is_processed, f"{notification} has been processed already"
            action = (
                tasks.send_notification
                if notification.sender.is_local
                else tasks.process_incoming_notification
            )

            result = action(notification.id)
            assert result is not None, "Notification {notification} was skipped"

            ok = result.result == models.NotificationProcessResult.Types.OK
            assert ok, f"{result.get_result_display()} result for {notification.id}"
            successful += 1
        except AssertionError as exc:
            messages.warning(request, str(exc))
        except (AssertionError, Exception) as exc:
            messages.error(request, f"Error processing {notification.id}: {exc}")

    if successful:
        messages.success(request, f"Processed {successful} message(s)")


@admin.action(description="Process selected messages (Force)")
def force_process_notifications(modeladmin, request, queryset):
    successful = 0
    for notification in queryset:
        try:
            result = tasks.send_notification(notification.id)
            ok = result.result == models.NotificationProcessResult.Types.OK
            assert ok, f"{result.get_result_display()} result for {notification.id}"
            successful += 1
        except AssertionError as exc:
            messages.warning(request, str(exc))
        except (AssertionError, Exception) as exc:
            messages.error(request, f"Error processing {notification.id}: {exc}")

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
