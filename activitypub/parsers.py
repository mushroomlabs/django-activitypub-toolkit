from rest_framework.parsers import JSONParser


class JsonLdParser(JSONParser):
    media_type = "application/ld+json"


class ActivityStreamsJsonParser(JSONParser):
    media_type = "application/activity+json"
