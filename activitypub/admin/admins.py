from django.contrib import admin

from .. import models
from . import actions, filters


@admin.register(models.ActorContext)
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


@admin.register(models.SecV1Context)
class SecV1ContextAdmin(admin.ModelAdmin):
    list_display = ("owned_by", "key_id")
    exclude = ("private_key_pem",)

    def owned_by(self, obj):
        return obj.owner.first()

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.CollectionContext)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ("uri", "name", "type", "total_items")
    list_filter = ("type",)

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.CollectionPageContext)
class CollectionPageAdmin(admin.ModelAdmin):
    list_display = ("uri", "name", "part_of")

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.CollectionItem)
class CollectionItemAdmin(admin.ModelAdmin):
    list_display = ("get_collection", "get_collection_name", "get_item", "order")
    list_select_related = ("item",)
    search_fields = ("item__uri",)

    def get_search_results(self, request, queryset, search_term):
        pages = models.CollectionPageContext.objects.filter(part_of__uri=search_term).values_list(
            "id", flat=True
        )

        queryset = queryset.order_by("order")

        if pages:
            queryset = models.CollectionItem.objects.filter(
                container_object_id__in=pages
            ).order_by("order")
            return queryset, False

        collection = models.CollectionContext.objects.filter(reference__uri=search_term).first()
        if collection:
            queryset = models.CollectionItem.objects.filter(
                container_object_id=collection.id
            ).order_by("order")
            return queryset, False

        return super().get_search_results(request, queryset, search_term)

    @admin.display(description="Collection")
    def get_collection(self, obj):
        container = obj.container

        if type(container) is models.CollectionPage:
            return container.part_of
        return container

    @admin.display(description="Collection Name")
    def get_collection_name(self, obj):
        collection = self.get_collection(obj)
        return collection.name

    @admin.display(description="Item")
    def get_item(self, obj):
        return obj.item.uri

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.ObjectContext)
class ObjectAdmin(admin.ModelAdmin):
    list_display = ("uri", "type", "name", "content")
    list_filter = ("type", "media_type")
    search_fields = ("reference__uri",)

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.LinkContext)
class LinkAdmin(admin.ModelAdmin):
    list_display = ("href", "media_type")
    list_filter = ("media_type",)

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "resource",
        "sender",
        "target",
        "get_activity_type",
        "get_processed",
        "get_verified",
    )
    list_select_related = ("sender", "target", "resource")
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
            activity = obj.message.reference.activitypub_activitycontext_context
            return activity.get_type_display()
        except models.Reference.RelatedObjectDoesNotExist:
            return None

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.FollowRequest)
class FollowRequestAdmin(admin.ModelAdmin):
    list_display = ("activity", "follower", "followed", "status")
    list_filter = ("status",)


@admin.register(models.Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "iso_639_1", "iso_639_3")
    search_fields = ("code", "name")
    list_filter = ("iso_639_1",)


@admin.register(models.ActivityPubServer)
class ActivityPubServerAdmin(admin.ModelAdmin):
    list_display = ("domain", "software_family", "version")
    list_filter = ("software_family",)
    search_fields = ("domain__name",)


__all__ = [
    "ActivityPubServerAdmin",
    "SecV1ContextAdmin",
    "DomainAdmin",
    "AccountAdmin",
    "ActorAdmin",
    "ActivityAdmin",
    "FollowRequestAdmin",
    "LanguageAdmin",
]
