from django.contrib import admin

from .. import models
from ..schemas import AS2
from . import actions, filters


@admin.register(models.BaseActivityStreamsObject)
class BaseActivityStreamsObjectAdmin(admin.ModelAdmin):
    list_display = ("id", "uri", "activitypub_type")

    def has_change_permission(self, request, obj=None):
        return False

    def activitypub_type(self, obj):
        return AS2[obj.__class__.__name__]

    def get_queryset(self, *args, **kw):
        qs = super().get_queryset(*args, **kw)
        return qs.select_subclasses()


@admin.register(models.Reference)
class ReferenceAdmin(admin.ModelAdmin):
    list_display = ("uri", "domain", "status")
    list_filter = ("status",)
    list_select_related = ("domain",)
    search_fields = ("uri",)
    actions = (actions.resolve_references,)

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.Actor)
class ActorAdmin(admin.ModelAdmin):
    list_display = ("uri", "type", "inbox_url", "outbox_url", "following_url", "followers_url")
    list_filter = ("type",)
    list_select_related = ("account", "account__domain")
    search_fields = ("account__username", "account__domain__name")
    actions = (actions.fetch_actor,)

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("actor", "username", "domain")
    list_select_related = ("actor", "domain")
    list_filter = (filters.AccountDomainFilter,)
    search_fields = ("username", "domain__name")

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("name", "local", "blocked")
    list_filter = ("local", "blocked")

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ("uri", "actor", "object", "target", "type")
    list_filter = ("type",)
    actions = (actions.do_activities,)
    search_fields = ("reference__uri",)

    def actor(self, obj):
        return obj.actor

    def object(self, obj):
        return obj.object

    def target(self, obj):
        return obj.target

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.CryptographicKeyPair)
class CryptographicKeyPairAdmin(admin.ModelAdmin):
    list_display = ("actor", "key_id")
    list_select_related = ("actor",)

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ("uri", "name", "is_ordered", "total_items")

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.CollectionPage)
class CollectionPageAdmin(admin.ModelAdmin):
    list_display = ("uri", "name", "part_of")

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.Object)
class ObjectAdmin(admin.ModelAdmin):
    list_display = ("uri", "type", "name", "content")
    list_filter = ("type", "media_type")
    search_fields = ("reference__uri",)

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.Link)
class LinkAdmin(admin.ModelAdmin):
    list_display = ("href", "media_type")
    list_filter = ("media_type",)

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = (
        "activity",
        "sender",
        "recipient",
        "get_activity_type",
        "get_processed",
        "get_verified",
    )
    list_select_related = (
        "sender",
        "activity",
        "recipient",
        "activity__item__as_activity",
    )
    list_filter = (
        filters.MessageDirectionFilter,
        filters.MessageVerifiedFilter,
        filters.ActivityTypeFilter,
    )

    actions = (
        actions.verify_message_integrity,
        actions.process_messages,
        actions.force_process_messages,
    )

    @admin.display(boolean=True, description="Processed?")
    def get_processed(self, obj):
        return obj.processed

    @admin.display(boolean=True, description="Verified Integrity Proof?")
    def get_verified(self, obj):
        return obj.verified

    @admin.display(description="Activity Type")
    def get_activity_type(self, obj):
        try:
            activity = obj.activity.item.as_activity
            return activity.get_type_display()
        except models.Reference.item.RelatedObjectDoesNotExist:
            return None

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.FollowRequest)
class FollowRequestAdmin(admin.ModelAdmin):
    list_display = ("activity", "follower", "followed", "status")
    list_filter = ("status",)


__all__ = [
    "MessageAdmin",
    "LinkAdmin",
    "ObjectAdmin",
    "CollectionAdmin",
    "CryptographicKeyPairAdmin",
    "DomainAdmin",
    "ReferenceAdmin",
    "AccountAdmin",
    "ActorAdmin",
    "ActivityAdmin",
    "BaseActivityStreamsObjectAdmin",
    "FollowRequestAdmin",
]
