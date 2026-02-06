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


class NotificationDirectionFilter(admin.SimpleListFilter):
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


class NotificationVerifiedFilter(admin.SimpleListFilter):
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


class NotificationProcessedFilter(admin.SimpleListFilter):
    title = "Processed"

    parameter_name = "processed"

    def lookups(self, request, model_admin):
        return {("yes", "Yes"), ("no", "No")}

    def queryset(self, request, queryset):
        selection = self.value()

        if selection is None:
            return queryset

        filter_qs = queryset.filter if selection == "yes" else queryset.exclude
        return filter_qs(processed=True)


class NotificationDroppedFilter(admin.SimpleListFilter):
    title = "Dropped"

    parameter_name = "dropped"

    def lookups(self, request, model_admin):
        return {("yes", "Yes"), ("no", "No")}

    def queryset(self, request, queryset):
        selection = self.value()

        if selection is None:
            return queryset

        filter_qs = queryset.filter if selection == "yes" else queryset.exclude
        return filter_qs(dropped=True)


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


class AuthenticatedFilter(admin.SimpleListFilter):
    title = "authenticated"
    parameter_name = "authenticated"

    def lookups(self, request, model_admin):
        return (("yes", "Yes"), ("no", "No"))

    def queryset(self, request, queryset):
        selection = self.value()

        if selection is None:
            return queryset

        filter_qs = queryset.filter if selection == "yes" else queryset.exclude
        return filter_qs(user__isnull=False)


class ResolvableReferenceFilter(admin.SimpleListFilter):
    title = "dereferenceable"
    parameter_name = "dereferenceable"

    def lookups(self, request, model_admin):
        return (("yes", "Yes"), ("no", "No"))

    def queryset(self, request, queryset):
        selection = self.value()

        if selection is None:
            return queryset

        filter_qs = queryset.filter if selection == "yes" else queryset.exclude
        return filter_qs(dereferenceable=True)
