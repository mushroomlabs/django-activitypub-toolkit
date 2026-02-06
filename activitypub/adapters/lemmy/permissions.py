from rest_framework import permissions

from activitypub.core.models import Identity

from .models import Site


def _is_site_admin(user, request):
    host = request.META.get("HTTP_HOST") or request.META.get("SERVER_NAME")

    if host is None:
        return False

    if not user.is_authenticated:
        return False

    identity = Identity.objects.filter(user=user).first()

    if identity is None:
        return False

    return Site.objects.filter(
        reference__domain__name=host, admins__reference=identity.actor.reference
    ).exists()


class IsSiteAdminOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return _is_site_admin(request.user, request)


class IsSiteAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return _is_site_admin(request.user, request)


class CanManageReports(permissions.BasePermission):
    """
    Permission to manage reports. Allows site admins and community moderators.
    For now, allows any authenticated user (TODO: implement proper moderator checks).
    """

    def has_permission(self, request, view):
        return request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        # TODO: Check if user is moderator of the community or site admin
        return request.user.is_authenticated
