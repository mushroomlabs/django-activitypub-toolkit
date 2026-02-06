from django.urls import include, path

from activitypub.core.views import (
    ActivityPubObjectDetailView,
    HostMeta,
    NodeInfo,
    NodeInfo21,
    Webfinger,
)

urlpatterns = (
    path(".well-known/nodeinfo", NodeInfo.as_view(), name="nodeinfo"),
    path(".well-known/webfinger", Webfinger.as_view(), name="webfinger"),
    path(".well-known/host-meta", HostMeta.as_view(), name="host-meta"),
    path("nodeinfo/2.1", NodeInfo21.as_view(), name="nodeinfo21"),
    path("nodeinfo/2.1.json", NodeInfo21.as_view(), name="nodeinfo21-json"),
    path(
        "api/v3/",
        include(("activitypub.adapters.lemmy.urls.v3", "lemmy-v3"), namespace="lemmy-v3"),
    ),
    path("<path:resource>", ActivityPubObjectDetailView.as_view(), name="activitypub-resource"),
)
