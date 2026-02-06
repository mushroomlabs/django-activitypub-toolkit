from django.urls import path

from activitypub.core.views import (
    ActivityPubObjectDetailView,
    HostMeta,
    NodeInfo,
    NodeInfo20,
    Webfinger,
)

urlpatterns = (
    path(".well-known/nodeinfo", NodeInfo.as_view(), name="nodeinfo"),
    path(".well-known/webfinger", Webfinger.as_view(), name="webfinger"),
    path(".well-known/host-meta", HostMeta.as_view(), name="host-meta"),
    path("nodeinfo/2.0", NodeInfo20.as_view(), name="nodeinfo20"),
    path("nodeinfo/2.0.json", NodeInfo20.as_view(), name="nodeinfo20-json"),
    path("<path:resource>", ActivityPubObjectDetailView.as_view(), name="activitypub-resource"),
)
