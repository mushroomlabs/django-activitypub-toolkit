from rest_framework import renderers


class JsonLdRenderer(renderers.JSONRenderer):
    media_type = "application/ld+json"


class ActivityJsonRenderer(renderers.JSONRenderer):
    media_type = "application/activity+json"
