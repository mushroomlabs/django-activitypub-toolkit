from django.urls import path

from activitypub.views import (
    ActivityPubObjectDetailView,
    ActorDetailView,
    HostMeta,
    NodeInfo,
    NodeInfo2,
    Webfinger,
)

urlpatterns = (
    path(".well-known/nodeinfo", NodeInfo.as_view(), name="nodeinfo"),
    path(".well-known/webfinger", Webfinger.as_view(), name="webfinger"),
    path(".well-known/host-meta", HostMeta.as_view(), name="host-meta"),
    path("nodeinfo/2.0", NodeInfo2.as_view(), name="nodeinfo20"),
    path("nodeinfo/2.0.json", NodeInfo2.as_view(), name="nodeinfo20-json"),
    path("@<str:subject_name>", ActorDetailView.as_view(), name="actor-detail-by-subject-name"),
    path("<path:resource>", ActivityPubObjectDetailView.as_view(), name="activitypub-resource"),
)
