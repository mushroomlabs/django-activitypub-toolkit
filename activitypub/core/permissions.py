from rest_framework import permissions

from .models import ActorContext, Reference


class IsOutboxOwnerOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj: Reference):
        if request.method in permissions.SAFE_METHODS:
            return True

        if not request.user.is_authenticated:
            return False

        actors = ActorContext.objects.filter(identity__user=request.user)
        return actors.filter(outbox=obj).exists()
