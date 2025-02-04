import factory
from django.db.models.signals import post_save
from factory import fuzzy

from . import models


@factory.django.mute_signals(post_save)
class DomainFactory(factory.django.DjangoModelFactory):
    name = factory.Sequence(lambda n: f"test-domain-{n:03d}.com")
    local = False

    class Meta:
        model = models.Domain


class ReferenceFactory(factory.django.DjangoModelFactory):
    uri = factory.LazyAttribute(lambda obj: f"{obj.domain.scheme}{obj.domain.name}{obj.path}")
    domain = factory.SubFactory(DomainFactory)
    path = factory.Sequence(lambda n: f"/item-{n:03d}")

    class Meta:
        model = models.Reference
        exclude = ("path",)


class BaseActivityStreamsObjectFactory(factory.django.DjangoModelFactory):
    id = factory.LazyFunction(models.generate_ulid)
    reference = factory.SubFactory(ReferenceFactory)

    @factory.post_generation
    def in_reply_to(self, create, extracted, **kwargs):
        if not create or not extracted:
            return

        self.in_reply_to.add(*extracted)

    @factory.post_generation
    def attributed_to(self, create, extracted, **kwargs):
        if not create or not extracted:
            return

        self.attributed_to.add(*extracted)


class CollectionFactory(BaseActivityStreamsObjectFactory):
    name = factory.Sequence(lambda n: f"Collection {n:03d}")
    reference = factory.SubFactory(ReferenceFactory)

    class Meta:
        model = models.Collection


class ActorFactory(BaseActivityStreamsObjectFactory):
    type = models.Actor.Types.PERSON
    reference = factory.SubFactory(ReferenceFactory)
    inbox = factory.SubFactory(CollectionFactory)
    followers = factory.SubFactory(CollectionFactory)
    following = factory.SubFactory(CollectionFactory)

    class Meta:
        model = models.Actor


class AccountFactory(factory.django.DjangoModelFactory):
    actor = factory.SubFactory(
        ActorFactory,
        preferred_username=factory.SelfAttribute("..username"),
        reference__path=factory.LazyAttribute(
            lambda o: f"/users/{o.factory_parent.preferred_username}"
        ),
        reference__domain=factory.LazyAttribute(lambda o: o.factory_parent.factory_parent.domain),
        inbox__reference__path=factory.LazyAttribute(
            lambda o: f"/users/{o.factory_parent.factory_parent.preferred_username}/inbox"
        ),
        inbox__reference__domain=factory.LazyAttribute(
            lambda o: o.factory_parent.factory_parent.factory_parent.domain
        ),
        followers__reference__path=factory.LazyAttribute(
            lambda o: f"/users/{o.factory_parent.factory_parent.preferred_username}/followers"
        ),
        followers__reference__domain=factory.LazyAttribute(
            lambda o: o.factory_parent.factory_parent.factory_parent.domain
        ),
        following__reference__path=factory.LazyAttribute(
            lambda o: f"/users/{o.factory_parent.factory_parent.preferred_username}/following"
        ),
        following__reference__domain=factory.LazyAttribute(
            lambda o: o.factory_parent.factory_parent.factory_parent.domain
        ),
    )

    username = factory.Sequence(lambda n: f"test-user-{n:03}")
    domain = factory.SubFactory(DomainFactory, local=True)

    class Meta:
        model = models.Account


class ObjectFactory(BaseActivityStreamsObjectFactory):
    type = fuzzy.FuzzyChoice(choices=models.Object.Types.choices)

    class Meta:
        model = models.Object


class ActivityFactory(BaseActivityStreamsObjectFactory):
    type = fuzzy.FuzzyChoice(choices=models.Activity.Types.choices)
    reference = factory.SubFactory(ReferenceFactory)
    actor = factory.SubFactory(ActorFactory)

    class Meta:
        model = models.Activity


class LinkFactory(BaseActivityStreamsObjectFactory):
    reference = None

    class Meta:
        model = models.Link


@factory.django.mute_signals(post_save)
class MessageFactory(factory.django.DjangoModelFactory):
    sender = factory.SubFactory(ReferenceFactory)
    recipient = factory.SubFactory(ReferenceFactory)
    activity = factory.SubFactory(ReferenceFactory)

    class Meta:
        model = models.Message
