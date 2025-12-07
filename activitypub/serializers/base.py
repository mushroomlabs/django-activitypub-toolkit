from rest_framework import serializers

from activitypub.models import Domain


class BaseSerializer(serializers.BaseSerializer):
    def get_domain(self):
        request = self.context.get("request")
        host = request.META.get("HTTP_HOST")
        scheme = Domain.SchemeTypes.HTTP if not request.is_secure() else Domain.SchemeTypes.HTTPS
        return Domain.objects.filter(scheme=scheme, name=host, local=True).first()


__all__ = ("BaseSerializer",)
