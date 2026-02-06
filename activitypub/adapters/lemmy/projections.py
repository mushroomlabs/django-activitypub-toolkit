from activitypub.adapters.lemmy.models.core import Comment, Community, Language, LemmyObject, Post
from activitypub.core.contexts import AS2, SCHEMA
from activitypub.core.models import ActivityContext
from activitypub.projections import (
    ActivityProjection,
    ActorProjection,
    LanguageProjection,
    ObjectProjection,
    ReferenceProjection,
    default_projection_selector,
)


class LemmyObjectProjectionMixin(ReferenceProjection):
    def get_languages(self):
        obj = LemmyObject.objects.filter(reference=self.reference).first()

        if obj is None:
            return None

        projections = [
            LanguageProjection(reference=lang.reference, parent=self)
            for lang in Language.objects.filter(reference__in=obj.lemmy.language.all())
        ]
        return [p.get_compacted() for p in projections]

    class Meta:
        extra = {"get_languages": SCHEMA.inLanguage}


class LemmyContentProjection(ObjectProjection, LemmyObjectProjectionMixin):
    pass


class CommunityProjection(ActorProjection, LemmyObjectProjectionMixin):
    pass


class LemmyActivityProjection(ActivityProjection):
    class Meta:
        overrides = {AS2.object: LemmyContentProjection}


def lemmy_projection_selector(reference):
    content_activities = [ActivityContext.Types.CREATE, ActivityContext.Types.UPDATE]

    if ActivityContext.objects.filter(reference=reference, type__in=content_activities).exists():
        return LemmyActivityProjection

    if ActivityContext.objects.filter(reference=reference).exists():
        return ReferenceProjection

    if Community.objects.filter(reference=reference).exists():
        return CommunityProjection

    if Post.objects.filter(reference=reference).exists():
        return LemmyContentProjection

    if Comment.objects.filter(reference=reference).exists():
        return LemmyContentProjection

    return default_projection_selector(reference)
