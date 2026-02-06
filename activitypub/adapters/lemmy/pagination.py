from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class LemmyResultPagination(PageNumberPagination):
    def paginate_queryset(self, queryset, request, view=None):
        try:
            return super().paginate_queryset(queryset, request, view)
        except NotFound:
            # Lemmy returns empty list instead of 404 for out-of-range pages.
            return []

    RESULTS_PARAM_NAME = "results"
    page_size = 50
    page_query_param = "page"
    page_size_query_param = "limit"
    cursor_query_param = "next_page"
    ordering = ("-reference_id",)

    def get_paginated_response(self, data):
        paginated_data = {self.RESULTS_PARAM_NAME: data}
        return Response(paginated_data)


class PostPagination(LemmyResultPagination):
    RESULTS_PARAM_NAME = "posts"


class CommunityPagination(LemmyResultPagination):
    RESULTS_PARAM_NAME = "communities"


class CommentPagination(LemmyResultPagination):
    RESULTS_PARAM_NAME = "comments"
