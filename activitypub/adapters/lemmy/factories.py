import factory

from activitypub.core.factories import (
    ActorFactory,
    ReferenceFactory,
    UserFactory,
)

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

    class Meta:
        model = models.Post


class CommentFactory(factory.django.DjangoModelFactory):
    reference = factory.SubFactory(ReferenceFactory)
    post = factory.SubFactory(PostFactory)

    class Meta:
        model = models.Comment


class UserSettingsFactory(factory.django.DjangoModelFactory):
    user = factory.SubFactory(UserFactory)

    class Meta:
        model = models.UserSettings
