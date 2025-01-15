from rest_framework import permissions

from .models import Domain


class UnblockedDomainOrActorPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        actor = getattr(request, "actor", None)
        if actor is None:
            return True

        return not Domain.objects.filter(accounts__actor=actor, blocked=True).exists()


class SignedRequestPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        return hasattr(request, "signature")


class SignedDocumentPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        return "signature" in request.data
