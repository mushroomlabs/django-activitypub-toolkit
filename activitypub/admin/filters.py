from django.contrib import admin

from .. import models


class DomainFilter(admin.SimpleListFilter):
    title = "Local"

    parameter_name = "local"

    def lookups(self, request, model_admin):
        return {("yes", "Yes"), ("no", "No")}

    def queryset(self, request, queryset):
        selection = self.value()

        if selection is None:
            return queryset

        filter_qs = queryset.filter if selection == "yes" else queryset.exclude
        return filter_qs(domain__local=True)


class MessageDirectionFilter(admin.SimpleListFilter):
    title = "Direction"

    parameter_name = "local"

    def lookups(self, request, model_admin):
        return {("incoming", "Incoming"), ("outgoing", "Outgoing")}

    def queryset(self, request, queryset):
        selection = self.value()

        if selection is None:
            return queryset

        filter_qs = queryset.filter if selection == "incoming" else queryset.exclude
        return filter_qs(target__domain__local=True)


class MessageVerifiedFilter(admin.SimpleListFilter):
    title = "Verified"

    parameter_name = "verified"

    def lookups(self, request, model_admin):
        return {("yes", "Yes"), ("no", "No")}

    def queryset(self, request, queryset):
        selection = self.value()

        if selection is None:
            return queryset

        filter_qs = queryset.filter if selection == "yes" else queryset.exclude
        return filter_qs(verified=True)


class ActivityTypeFilter(admin.SimpleListFilter):
    title = "Activity Type"

    parameter_name = "activity_type"

    def lookups(self, request, model_admin):
        return models.ActivityContext.Types.choices

    def queryset(self, request, queryset):
        selection = self.value()

        if selection is None:
            return queryset

        references = models.ActivityContext.objects.filter(type=selection).values("reference")

        return queryset.filter(resource__in=references)


class HasUserFilter(admin.SimpleListFilter):
    """Filter applications by whether they have an associated user."""

    title = "registration type"
    parameter_name = "has_user"

    def lookups(self, request, model_admin):
        return (
            ("yes", "Registered by user"),
            ("no", "Anonymous registration"),
        )

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.exclude(user__isnull=True)
        if self.value() == "no":
            return queryset.filter(user__isnull=True)
        return queryset


class ResolvableReferenceFilter(admin.SimpleListFilter):
    title = "dereferenceable"
    parameter_name = "dereferenceable"

    def lookups(self, request, model_admin):
        return (
            ("yes", "Yes"),
            ("no", "No"),
        )

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(dereferenceable=True)
        if self.value() == "no":
            return queryset.filter(dereferenceable=False)
        return queryset
