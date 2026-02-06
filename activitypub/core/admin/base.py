from django.contrib import admin

from activitypub.core.models.fields import ReferenceField


class ContextModelAdmin(admin.ModelAdmin):
    """
    Base admin class that handles models with ReferenceField.

    Django's admin tries to select_related on all foreign key fields,
    but ReferenceField uses a custom through table that links via
    reference FKs instead of model PKs, so select_related doesn't work.
    """

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        # Get the list of fields that admin would normally select_related on
        # and filter out ReferenceField instances
        select_related_fields = []
        for field in self.model._meta.get_fields():
            if isinstance(field, ReferenceField):
                continue
            if hasattr(field, "get_path_info") and field.get_path_info():
                select_related_fields.append(field.name)

        # Only select_related on non-ReferenceField relations
        if select_related_fields:
            qs = qs.select_related(*select_related_fields)

        return qs
