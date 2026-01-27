from django.contrib import admin

from .. import models
from ..models.collections import BaseCollectionContext
from . import actions, filters
from .base import ContextModelAdmin


@admin.register(models.Reference)
class ReferenceAdmin(admin.ModelAdmin):
    list_display = ("uri", "status", "local", "dereferenceable")
    list_filter = ("status", "domain__local", filters.ResolvableReferenceFilter)
    select_related = ("domain",)
    search_fields = ("uri", "domain__name")

    @admin.display(description="Dereferenceable", boolean=True)
    def dereferenceable(self, obj):
        return obj.is_dereferenceable

    @admin.display(description="local", boolean=True)
    def local(self, obj):
        return obj.domain and obj.domain.local

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.LinkedDataDocument)
class LinkedDataDocumentAdmin(admin.ModelAdmin):
    list_display = ("reference", "resolvable")
    list_filter = ("resolvable",)
    search_fields = ("reference__uri",)

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.ActorContext)
class ActorAdmin(admin.ModelAdmin):
    list_display = ("uri", "type", "subject_name")
    list_filter = ("type",)
    list_select_related = ("identity", "identity__user", "reference", "reference__domain")
    search_fields = ("preferred_username", "reference__domain__name")
    actions = (actions.fetch_actor,)

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.Identity)
class IdentityAdmin(admin.ModelAdmin):
    list_display = ("user", "actor", "handle", "is_primary")
    list_filter = ("is_primary",)
    list_select_related = ("actor", "actor__reference__domain")
    search_fields = ("actor__preferred_username", "actor__reference__domain__name")

    @admin.display(description="Subject Name")
    def handle(self, obj):
        return obj.actor.subject_name

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("host", "port", "local", "blocked")
    list_filter = ("local", "blocked", "scheme", "port")
    search_fields = ("name",)

    @admin.display(description="Host")
    def host(self, obj):
        return obj.url

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.Activity)
class ActivityAdmin(ContextModelAdmin):
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
class SecV1ContextAdmin(ContextModelAdmin):
    list_display = ("reference", "owned_by", "key_id")
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
    list_display = ("uri", "name")

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
        return (
            BaseCollectionContext.objects.filter(id=obj.collection_id).select_subclasses().first()
        )

    @admin.display(description="Collection Name")
    def get_collection_name(self, obj):
        collection = self.get_collection(obj)
        return collection.name

    @admin.display(description="Item")
    def get_item(self, obj):
        return obj.item.uri

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.BaseAs2ObjectContext)
class BaseAs2ObjectAdmin(admin.ModelAdmin):
    list_display = ("uri", "name", "content")
    list_filter = ("media_type",)
    search_fields = ("reference__uri",)

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.ObjectContext)
class ObjectAdmin(admin.ModelAdmin):
    list_display = ("uri", "type", "name", "content")
    list_filter = ("type", "media_type")
    search_fields = ("reference__uri",)

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.SourceContentContext)
class SourceContentAdmin(admin.ModelAdmin):
    list_display = ("uri", "content")
    search_fields = ("content",)

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.LinkContext)
class LinkAdmin(admin.ModelAdmin):
    list_display = ("reference", "type", "href", "name")
    list_filter = ("type",)
    select_related = ("reference",)

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "get_resource",
        "get_sender",
        "get_target",
        "get_activity_type",
        "get_processed",
        "get_dropped",
        "get_verified",
    )
    list_select_related = ("sender", "target", "resource")
    list_filter = (
        filters.NotificationDirectionFilter,
        filters.NotificationVerifiedFilter,
        filters.NotificationProcessedFilter,
        filters.NotificationDroppedFilter,
        filters.ActivityTypeFilter,
    )
    search_fields = ("resource__uri",)
    actions = (
        actions.verify_message_integrity,
        actions.process_notifications,
        actions.force_process_notifications,
    )

    @admin.display(description="Resource")
    def get_resource(self, obj):
        return obj.resource

    @admin.display(description="Sender")
    def get_sender(self, obj):
        return obj.sender

    @admin.display(description="Target")
    def get_target(self, obj):
        return obj.target

    @admin.display(boolean=True, description="Processed?")
    def get_processed(self, obj):
        return obj.is_processed

    @admin.display(boolean=True, description="Dropped?")
    def get_dropped(self, obj):
        return obj.is_dropped

    @admin.display(boolean=True, description="Verified Integrity Proof?")
    def get_verified(self, obj):
        return obj.verified

    @admin.display(description="Activity Type")
    def get_activity_type(self, obj):
        activity = obj.resource.get_by_context(models.ActivityContext)
        return activity and activity.get_type_display()

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.FollowRequest)
class FollowRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "follower", "followed", "status")
    list_filter = ("status",)
    autocomplete_fields = ("follower", "followed", "activity")

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "iso_639_1", "iso_639_3")
    search_fields = ("code", "name")
    list_filter = ("iso_639_3",)


@admin.register(models.ActivityPubServer)
class ActivityPubServerAdmin(admin.ModelAdmin):
    list_display = ("domain", "software_family", "version")
    list_filter = ("software_family",)
    search_fields = ("domain__name",)

    def has_change_permission(self, request, obj=None):
        return obj and obj.domain.local


# OAuth Admin classes - registered via Django OAuth Toolkit settings machinery
class OAuthClientApplicationAdmin(admin.ModelAdmin):
    """Admin for OAuth Client Applications with RFC 7591 metadata."""

    list_display = (
        "client_id",
        "name",
        "get_registered_by",
        "client_type",
        "authorization_grant_type",
        "created",
    )
    list_filter = (
        "client_type",
        "authorization_grant_type",
        "skip_authorization",
        filters.AuthenticatedFilter,
    )
    search_fields = ("name", "client_id", "client_uri", "user__username")
    raw_id_fields = ("user",)
    readonly_fields = ("client_id", "client_secret", "created", "updated")

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("name", "user", "client_type", "authorization_grant_type")},
        ),
        (
            "OAuth Configuration",
            {
                "fields": (
                    "client_id",
                    "client_secret",
                    "redirect_uris",
                    "post_logout_redirect_uris",
                    "algorithm",
                )
            },
        ),
        (
            "RFC 7591 Metadata",
            {
                "fields": (
                    "client_uri",
                    "logo_uri",
                    "policy_uri",
                    "tos_uri",
                    "software_id",
                    "software_version",
                )
            },
        ),
        ("Settings", {"fields": ("skip_authorization", "created", "updated")}),
    )

    @admin.display(description="Registered By")
    def get_registered_by(self, obj):
        return obj.user and obj.user.username


class OAuthAccessTokenAdmin(admin.ModelAdmin):
    list_display = ("truncated_token", "user", "get_identity", "application", "expires", "created")
    list_select_related = ("application", "user", "identity", "identity__actor")
    list_filter = ("application", "created", "expires")
    search_fields = ("token", "user__username", "identity__actor__preferred_username")
    readonly_fields = ("token", "created", "updated", "token_checksum")

    @admin.display(description="Token")
    def truncated_token(self, obj):
        return f"{obj.token[:10]}...{obj.token[-10:]}" if obj.token else ""

    @admin.display(description="Identity")
    def get_identity(self, obj):
        return obj.identity and obj.identity.actor.subject_name

    def has_change_permission(self, request, obj=None):
        return False


class OAuthRefreshTokenAdmin(admin.ModelAdmin):
    list_display = ("truncated_token", "user", "get_identity", "application", "created", "revoked")
    list_select_related = ("application", "user", "identity", "identity__actor")
    list_filter = ("application", "revoked", "created")
    search_fields = ("token", "user__username", "identity__actor__preferred_username")

    @admin.display(description="Token")
    def truncated_token(self, obj):
        return f"{obj.token[:10]}...{obj.token[-10:]}" if obj.token else ""

    @admin.display(description="Identity")
    def get_identity(self, obj):
        return obj.identity and obj.identity.actor.subject_name

    def has_change_permission(self, request, obj=None):
        return False


class OidcIdentityTokenAdmin(admin.ModelAdmin):
    list_display = ("id", "get_identity_username", "get_user", "jti", "expires")
    list_filter = ("created", "expires")
    list_select_related = ("identity", "identity__actor", "user", "application")
    search_fields = ("identity__actor__preferred_username", "jti", "user__username")

    @admin.display(description="Identity")
    def get_identity_username(self, obj):
        return obj.identity and obj.identity.actor.subject_name

    @admin.display(description="User")
    def get_user(self, obj):
        return obj.user and obj.user.username

    def has_change_permission(self, request, obj=None):
        return False


__all__ = [
    "ActivityPubServerAdmin",
    "SecV1ContextAdmin",
    "DomainAdmin",
    "ActorAdmin",
    "ActivityAdmin",
    "FollowRequestAdmin",
    "LanguageAdmin",
    "OAuthClientApplicationAdmin",
    "OAuthAccessTokenAdmin",
    "OAuthRefreshTokenAdmin",
    "OidcIdentityTokenAdmin",
]
