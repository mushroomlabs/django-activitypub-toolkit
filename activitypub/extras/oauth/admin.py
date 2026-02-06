from django.contrib import admin

from activitypub.core.admin.filters import AuthenticatedFilter


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
        AuthenticatedFilter,
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


class OAuthAuthorizationCodeAdmin(admin.ModelAdmin):
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
    "OAuthClientApplicationAdmin",
    "OAuthAccessTokenAdmin",
    "OAuthRefreshTokenAdmin",
    "OidcIdentityTokenAdmin",
]
