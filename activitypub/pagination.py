from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.utils.urls import replace_query_param

from .models import Collection
from .settings import app_settings


class CollectionPagination(PageNumberPagination):
    page_size = app_settings.Instance.collection_page_size

    def __init__(self, collection: Collection, *args, **kw):
        super().__init__(*args, **kw)
        self.collection = collection

    def get_paginated_response(self, data):
        page_type = "OrderedCollectionPage" if self.collection.is_ordered else "CollectionPage"
        item_key = "orderedItems" if self.collection.is_ordered else "items"
        return Response(
            {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"{self.collection.uri}?page={self.page.number}",
                "type": page_type,
                "totalItems": self.page.paginator.count,
                "partOf": self.collection.uri,
                item_key: [collection_item.uri for collection_item in data if collection_item],
                "next": self.get_next_link(),
                "prev": self.get_previous_link(),
            }
        )

    def get_previous_link(self):
        if not self.page.has_previous():
            return None

        url = self.request.build_absolute_uri()
        page_number = self.page.previous_page_number()
        return replace_query_param(url, self.page_query_param, page_number)
