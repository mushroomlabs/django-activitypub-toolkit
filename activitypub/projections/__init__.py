from activitypub.models import (
    ActivityContext,
    ActorContext,
    CollectionContext,
    CollectionPageContext,
    ObjectContext,
    QuestionContext,
)

from .base import *  # noqa
from .base import (
    ActivityProjection,
    ActorProjection,
    CollectionPageProjection,
    CollectionProjection,
    CollectionWithFirstPageProjection,
    NoteProjection,
    PageProjection,
    QuestionProjection,
    ReferenceProjection,
)
from .core import *  # noqa


# There is a configuration setting to indicate what callable should be
# used to select a projection for a reference. This method is provided
# as a default choice.
def default_projection_selector(reference):
    if ActorContext.objects.filter(outbox=reference).exists():
        # It's an outbox, return paginated project
        return CollectionWithFirstPageProjection

    if reference.get_by_context(ActorContext):
        return ActorProjection

    if reference.get_by_context(ActivityContext):
        return ActivityProjection

    if reference.get_by_context(QuestionContext):
        return QuestionProjection

    if reference.get_by_context(CollectionPageContext):
        return CollectionPageProjection

    # Check for CollectionContext
    if reference.get_by_context(CollectionContext):
        collection = reference.get_by_context(CollectionContext)
        # Use CollectionWithFirstPageProjection if collection has pages
        if collection.pages.exists():
            return CollectionWithFirstPageProjection
        else:
            return CollectionProjection

    as2_object = reference.get_by_context(ObjectContext)
    if as2_object is not None:
        match as2_object.type:
            case ObjectContext.Types.PAGE:
                return PageProjection
            case ObjectContext.Types.NOTE:
                return NoteProjection

    # Default
    return ReferenceProjection
