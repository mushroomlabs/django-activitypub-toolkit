import factory
from django.utils import timezone

from activitypub.core.factories import (
    ActorFactory,
    ObjectFactory,
    ReferenceFactory,
    UserFactory,
)
from activitypub.core.models import ObjectContext

from . import models


class SiteFactory(factory.django.DjangoModelFactory):
    reference = factory.SubFactory(ReferenceFactory)

    @factory.post_generation
    def actor(obj, create, extracted, **kw):
        ActorFactory(reference=obj.reference, **kw)

    class Meta:
        model = models.Site


class CommunityFactory(factory.django.DjangoModelFactory):
    reference = factory.SubFactory(ReferenceFactory)

    class Meta:
        model = models.Community


class PersonFactory(factory.django.DjangoModelFactory):
    reference = factory.SubFactory(ReferenceFactory)

    class Meta:
        model = models.Person


class PostFactory(factory.django.DjangoModelFactory):
    reference = factory.SubFactory(ReferenceFactory)
    community = factory.SubFactory(CommunityFactory)

    @factory.post_generation
    def object_context(obj, create, extracted, **kw):
        if create and not ObjectContext.objects.filter(reference=obj.reference).exists():
            ObjectFactory(
                reference=obj.reference,
                type=ObjectContext.Types.PAGE,
                published=timezone.now(),
            )

    class Meta:
        model = models.Post


class CommentFactory(factory.django.DjangoModelFactory):
    reference = factory.SubFactory(ReferenceFactory)
    post = factory.SubFactory(PostFactory)

    @factory.post_generation
    def object_context(obj, create, extracted, **kw):
        if create and not ObjectContext.objects.filter(reference=obj.reference).exists():
            ObjectFactory(
                reference=obj.reference,
                type=ObjectContext.Types.NOTE,
                published=timezone.now(),
            )

    class Meta:
        model = models.Comment


class UserSettingsFactory(factory.django.DjangoModelFactory):
    user = factory.SubFactory(UserFactory)

    class Meta:
        model = models.UserSettings
