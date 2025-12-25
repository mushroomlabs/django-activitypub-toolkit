from rest_framework import renderers


class JsonLdRenderer(renderers.JSONRenderer):
    media_type = "application/ld+json"


class ActivityJsonRenderer(renderers.JSONRenderer):
    media_type = "application/activity+json"


class BrowsableLinkedDataRenderer(renderers.BrowsableAPIRenderer):
    media_type = "text/html"

    def get_raw_data_form(self, data, view, method, request):
        return None
