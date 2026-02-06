from django.contrib import admin

from . import forms, models


@admin.register(models.LocalSite)
class LocalSiteAdmin(admin.ModelAdmin):
    list_display = ("site__reference",)
    select_related = ("site", "site__reference")
    form = forms.LocalSiteForm

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        obj.site.as2.name = form.cleaned_data["name"]
        obj.site.as2.summary = form.cleaned_data["sidebar"]
        obj.site.as2.save()


@admin.register(models.UserSettings)
class UserSettingsAdmin(admin.ModelAdmin):
    list_display = ("get_handle", "accepted_application")
    list_filter = ("accepted_application", "admin", "email_verified")
    selected_related = ("user", "user__identities", "user__identities__actor")

    readonly_fields = (
        "user",
        "last_donation_notification",
        "theme",
        "interface_language",
    )

    @admin.display(description="Account")
    def get_handle(self, obj):
        identity = obj.user.identities.first()
        return identity and identity.actor.subject_name


@admin.register(models.Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ("reference",)
    list_filter = ("reference__domain__local",)
    select_related = ("reference", "reference__domain", "admins")
    readonly_fields = (
        "reference",
        "admins",
        "last_retry",
        "last_successful_notification_id",
        "last_successful_published_time",
        "fail_count",
    )
    autocomplete_fields = ("allowed_instances", "blocked_instances")

    def has_change_permission(self, request, obj=None):
        return obj and obj.reference.is_local


@admin.register(models.Tagline)
class TaglineAdmin(admin.ModelAdmin):
    list_display = ("local_site", "content", "created", "modified")


@admin.register(models.Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("object_id", "reference", "get_domain")
    search_fields = ("reference__uri",)
    readonly_fields = ("reference", "site")
    exclude = ("liked_posts",)

    @admin.display(description="Domain")
    def get_domain(self, obj):
        return obj.reference.domain.name if obj.reference else None

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.Community)
class CommunityAdmin(admin.ModelAdmin):
    list_display = ("reference", "get_name", "public", "hidden", "deleted", "removed")
    select_related = ("reference", "reference__domain")
    list_filter = ("visibility", "hidden", "deleted", "removed")
    search_fields = ("reference__uri",)
    readonly_fields = ("reference",)

    @admin.display(description="public", boolean=True)
    def public(self, obj):
        return obj.visibility == obj.VisibilityTypes.PUBLIC

    @admin.display(description="Name")
    def get_name(self, obj):
        return obj.as2.name

    @admin.display(description="Domain")
    def domain(self, obj):
        return obj.reference and obj.reference.domain and obj.reference.domain.name


@admin.register(models.Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("reference", "community")
    select_related = ("reference", "community")
    readonly_fields = ("reference", "community")


@admin.register(models.Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("reference", "post")
    select_related = ("reference", "post")
    readonly_fields = ("reference", "post", "content", "source")

    @admin.display(description="Content")
    def content(self, obj):
        return obj.as2.content

    @admin.display(description="Source")
    def source(self, obj):
        return obj.content


@admin.register(models.LemmyContextModel)
class LemmyContextAdmin(admin.ModelAdmin):
    list_display = ("get_reference",)
    search_fields = ("reference__uri",)
    readonly_fields = ("reference",)

    @admin.display(description="Reference")
    def get_reference(self, obj):
        return obj.reference.uri

    def has_change_permission(self, request, obj=None):
        return False
