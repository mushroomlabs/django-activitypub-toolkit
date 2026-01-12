import factory
from django.db.models.signals import post_save
from django.utils import timezone
from factory import fuzzy

from . import models


class ContextModelSubFactory(factory.SubFactory):
    def evaluate(self, instance, step, extra):
        related_obj = super().evaluate(instance, step, extra)
        return related_obj.reference if related_obj else None


@factory.django.mute_signals(post_save)
class DomainFactory(factory.django.DjangoModelFactory):
    name = factory.Sequence(lambda n: f"test-domain-{n:03d}.com")
    local = False
    scheme = "https"

    class Meta:
        model = models.Domain


@factory.django.mute_signals(post_save)
class InstanceFactory(factory.django.DjangoModelFactory):
    domain = factory.SubFactory(DomainFactory, local=True)

    class Meta:
        model = models.ActivityPubServer


@factory.django.mute_signals(post_save)
class ReferenceFactory(factory.django.DjangoModelFactory):
    uri = factory.LazyAttribute(lambda obj: f"{obj.domain.url}{obj.path}")
    domain = factory.SubFactory(DomainFactory)
    path = factory.Sequence(lambda n: f"/item-{n:03d}")

    class Meta:
        model = models.Reference
        exclude = ("path",)

    class Params:
        resolved = factory.Trait(
            status=models.Reference.STATUS.resolved, resolved_at=timezone.now()
        )


class LinkedDataDocumentFactory(factory.django.DjangoModelFactory):
    reference = factory.SubFactory(ReferenceFactory)

    class Meta:
        model = models.LinkedDataDocument


class BaseActivityStreamsObjectFactory(factory.django.DjangoModelFactory):
    reference = factory.SubFactory(ReferenceFactory)

    @factory.post_generation
    def in_reply_to(obj, create, extracted, **kwargs):
        if not create or not extracted:
            return

        obj.in_reply_to.add(*extracted)

    @factory.post_generation
    def attributed_to(obj, create, extracted, **kwargs):
        if not create or not extracted:
            return

        obj.attributed_to.add(*extracted)


class CollectionFactory(BaseActivityStreamsObjectFactory):
    name = factory.Sequence(lambda n: f"Collection {n:03d}")

    class Meta:
        model = models.CollectionContext


class ActorFactory(BaseActivityStreamsObjectFactory):
    type = models.Actor.Types.PERSON
    preferred_username = factory.Sequence(lambda n: f"test-user-{n:03}")
    reference = factory.SubFactory(
        ReferenceFactory,
        path=factory.LazyAttribute(lambda o: f"/users/{o.factory_parent.preferred_username}"),
    )
    inbox = factory.SubFactory(ReferenceFactory)
    outbox = factory.SubFactory(ReferenceFactory)
    followers = factory.SubFactory(ReferenceFactory)
    following = factory.SubFactory(ReferenceFactory)

    @factory.post_generation
    def outbox_collection(obj, create, extracted, **kwargs):
        if not create or not extracted:
            return

        models.CollectionContext.make(reference=obj.outbox)

    class Meta:
        model = models.Actor


class ActorAccountFactory(factory.django.DjangoModelFactory):
    password = "!"
    actor = factory.SubFactory(
        ActorFactory,
        reference__domain=factory.SubFactory(DomainFactory, local=True),
    )

    class Meta:
        model = models.ActorAccount


class AccountFactory(factory.django.DjangoModelFactory):
    type = models.ActorContext.Types.PERSON
    reference = factory.SubFactory(
        ReferenceFactory,
        path=factory.LazyAttribute(lambda o: f"/users/{o.factory_parent.preferred_username}"),
    )
    preferred_username = factory.Sequence(lambda n: f"test-user-{n:03}")
    inbox = factory.SubFactory(
        ReferenceFactory,
        path=factory.LazyAttribute(
            lambda o: f"/users/{o.factory_parent.preferred_username}/inbox"
        ),
        domain=factory.LazyAttribute(lambda o: o.factory_parent.reference.domain),
    )
    outbox = factory.SubFactory(
        ReferenceFactory,
        path=factory.LazyAttribute(
            lambda o: f"/users/{o.factory_parent.preferred_username}/outbox"
        ),
        domain=factory.LazyAttribute(lambda o: o.factory_parent.reference.domain),
    )
    followers = factory.SubFactory(
        ReferenceFactory,
        path=factory.LazyAttribute(
            lambda o: f"/users/{o.factory_parent.preferred_username}/followers"
        ),
        domain=factory.LazyAttribute(lambda o: o.factory_parent.reference.domain),
    )
    following = factory.SubFactory(
        ReferenceFactory,
        path=factory.LazyAttribute(
            lambda o: f"/users/{o.factory_parent.preferred_username}/following"
        ),
        domain=factory.LazyAttribute(lambda o: o.factory_parent.reference.domain),
    )

    class Meta:
        model = models.ActorContext


class ObjectFactory(BaseActivityStreamsObjectFactory):
    type = fuzzy.FuzzyChoice(choices=models.ObjectContext.Types.choices)

    class Meta:
        model = models.ObjectContext


class ActivityContextFactory(BaseActivityStreamsObjectFactory):
    type = fuzzy.FuzzyChoice(choices=models.ActivityContext.Types.choices)
    actor = ContextModelSubFactory(ActorFactory)

    class Meta:
        model = models.ActivityContext


class ActivityFactory(ActivityContextFactory):
    class Meta:
        model = models.Activity


class LinkFactory(BaseActivityStreamsObjectFactory):
    class Meta:
        model = models.LinkContext


@factory.django.mute_signals(post_save)
class NotificationFactory(factory.django.DjangoModelFactory):
    sender = factory.SubFactory(ReferenceFactory)
    target = factory.SubFactory(ReferenceFactory)
    resource = factory.SubFactory(ReferenceFactory)

    class Meta:
        model = models.Notification


class NotificationIntegrityProofFactory(factory.django.DjangoModelFactory):
    notification = factory.SubFactory(NotificationFactory)

    class Meta:
        model = models.NotificationIntegrityProof


class NotificationProofVerificationFactory(factory.django.DjangoModelFactory):
    notification = factory.LazyAttribute(lambda o: o.proof.notification)
    proof = factory.SubFactory(NotificationIntegrityProofFactory)

    class Meta:
        model = models.NotificationProofVerification


class NotificationProcessResultFactory(factory.django.DjangoModelFactory):
    notification = factory.SubFactory(NotificationFactory)
    result = models.NotificationProcessResult.Types.OK

    class Meta:
        model = models.NotificationProcessResult


class SecV1ContextFactory(factory.django.DjangoModelFactory):
    reference = factory.SubFactory(ReferenceFactory)
    public_key_pem = factory.Faker("text", max_nb_chars=200)

    class Meta:
        model = models.SecV1Context


@factory.django.mute_signals(post_save)
class FollowRequestFactory(factory.django.DjangoModelFactory):
    follower = factory.SubFactory(ReferenceFactory)
    followed = factory.SubFactory(ReferenceFactory)
    activity = factory.SubFactory(ReferenceFactory)

    class Meta:
        model = models.FollowRequest
