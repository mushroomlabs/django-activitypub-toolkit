import json
import logging
import ssl
from typing import Optional

import requests
from django.db import models, transaction
from django.db.models import Case, F, Q, Value, When
from django.db.models.functions import Concat
from model_utils.choices import Choices
from model_utils.managers import QueryManager
from model_utils.models import StatusModel, TimeStampedModel

from ..serializers import NodeInfoSerializer
from ..settings import app_settings
from ..signals import activity_done
from .as2 import ActivityContext, ActorContext, BaseAs2ObjectContext
from .base import generate_ulid
from .collections import CollectionContext, CollectionPageContext
from .linked_data import Domain, Notification, Reference

logger = logging.getLogger(__name__)


class AccountManager(models.Manager):
    def get_queryset(self) -> models.QuerySet:
        qs = super().get_queryset()
        return qs.annotate(
            _subject_name=Concat(Value("@"), "username", Value("@"), "domain__name"),
            local=F("domain__local"),
        )

    def get_by_subject_name(self, subject_name):
        username, domain = subject_name.split("@", 1)
        qs = super().get_queryset()
        return qs.filter(username=username, domain__name=domain).get()


class Actor(ActorContext):
    class Meta:
        proxy = True

    @property
    def alternative_identities(self):
        return [self.account.subject_name] if self.account else []

    @property
    def followers_inboxes(self):
        actors = Actor.objects.filter(
            reference__in_collections__collection__reference=self.followers
        )

        actors_with_inboxes = actors.annotate(
            shared_inbox=F("endpoints__activitypub_endpointcontext_context__shared_inbox")
        ).annotate(
            target_inbox=Case(
                When(shared_inbox__isnull=False, then=F("shared_inbox")),
                When(shared_inbox__isnull=True, then=F("inbox__uri")),
                default=Value(None),
            )
        )

        return Reference.objects.filter(
            uri__in=actors_with_inboxes.exclude(target_inbox=None)
            .values_list("target_inbox", flat=True)
            .distinct()
        )

    @property
    def username(self):
        try:
            return self.account.username
        except AttributeError:
            return None

    @property
    def collections(self):
        references = [
            r for r in [self.inbox, self.outbox, self.followers, self.following] if r is not None
        ]
        return CollectionContext.objects.filter(reference__in=references)

    def follow(self, item: Reference):
        following = CollectionContext.make(reference=self.following)
        following.append(item)

    def accept_follow(self, item: Reference):
        followers = CollectionContext.make(reference=self.followers)
        followers.append(item)

    def is_following(self, reference: Reference):
        return False

    def is_followed_by(self, reference: Reference):
        return False


class Activity(ActivityContext):
    class Meta:
        verbose_name_plural = "Activities"
        proxy = True

    def _do_nothing(self):
        pass

    def _do_follow(self):
        FollowRequest.objects.update_or_create(
            activity=self, defaults={"status": FollowRequest.STATUS.pending}
        )

    def _undo_follow(self):
        follower_ref = self.actor
        followed_ref = self.object

        follower = follower_ref and follower_ref.get_by_context(ActorContext)
        followed = followed_ref and followed_ref.get_by_context(ActorContext)

        if follower_ref is not None and follower is not None:
            collection = follower.following and follower.following.get_by_context(
                CollectionContext
            )
            if collection is not None:
                collection.remove(item=followed_ref)

        if followed_ref is not None and followed is not None:
            collection = followed.followers and followed.followers.get_by_context(
                CollectionContext
            )
            if collection is not None:
                collection.remove(item=follower_ref)

        FollowRequest.objects.filter(activity=self).delete()

    def _do_add(self):
        # NOTE: no validation at this level whether actor can or can
        # not add to collection beyond checking whether the actor is
        # on the collecions's as:attributedTo fields, and even that
        # could be falsified.

        actor_ref = self.actor
        collection_ref = self.target
        collection = collection_ref and collection_ref.get_by_context(CollectionContext)

        try:
            assert collection is not None, "No target collection found"
            assert actor_ref is not None, "No actor found"

            assert collection.attributed_to.filter(uri=actor_ref.uri).exists(), "Not authorized"
            collection.append(item=self.object)
        except AssertionError as exc:
            logger.warning(str(exc))

    def _do_remove(self):
        # NOTE: no validation at this level whether actor can or can
        # not add to collection beyond checking whether the actor is
        # on the collecions's as:attributedTo fields, and even that
        # could be falsified.

        actor_ref = self.actor
        collection_ref = self.target
        collection = collection_ref and collection_ref.get_by_context(CollectionContext)

        try:
            assert collection_ref is not None, "No target collection found"
            assert actor_ref is not None, "No actor found"
            can_edit = collection.attributed_to.filter(uri=actor_ref.uri).exists()
            is_own_collection_q = (
                Q(inbox=collection_ref)
                | Q(outbox=collection_ref)
                | Q(followers=collection_ref)
                | Q(following=collection_ref)
            )

            is_own_collection = (
                Actor.objects.filter(reference=actor_ref).filter(is_own_collection_q).exists()
            )
            assert can_edit or is_own_collection, "Not authorized"
            collection.remove(item=self.object)
        except AssertionError as exc:
            logger.warning(str(exc))

    def _do_announce(self):
        if self.object is None:
            return

        object = self.object.get_by_context(BaseAs2ObjectContext)
        if object.shares is None:
            object.shares = CollectionContext.generate_reference(self.object.domain)
            object.save()
        shares_collection = CollectionContext.make(
            object.shares, name=f"Shares for {self.object.uri}"
        )
        shares_collection.append(self.reference)

    def _undo_announce(self):
        object = self.object and self.object.get_by_context(BaseAs2ObjectContext)

        if object is not None and object.shares is not None:
            collection = object.shares.get_by_context(CollectionContext)
            collection.remove(item=self.reference)

    def _do_like(self):
        if self.object is None:
            return

        actor = self.actor and self.actor.get_by_context(Actor)
        object = self.object.get_by_context(BaseAs2ObjectContext)

        if actor is not None and actor.liked is not None:
            collection = CollectionContext.make(reference=actor.liked)
            collection.append(self.object)

        if object.likes is not None:
            collection = CollectionContext.make(reference=object.likes)
            collection.append(self.reference)

    def _undo_like(self):
        actor = self.actor and self.actor.get_by_context(Actor)
        object = self.object and self.object.get_by_context(BaseAs2ObjectContext)

        if object is None:
            return

        if actor is not None and actor.liked is not None:
            collection = actor.liked.get_by_context(CollectionContext)
            collection.remove(item=object.reference)

        if object.reference.is_local and object.likes is not None:
            collection = object.likes.get_by_context(CollectionContext)
            collection.remove(item=self.reference)

    def _do_accept(self):
        accepted_activity = self.object.get_by_context(Activity)

        if accepted_activity.type == self.Types.FOLLOW:
            request = FollowRequest.objects.filter(activity=accepted_activity).first()
            if request is not None:
                request.accept()

    def _do_reject(self):
        rejected_activity = self.object.get_by_context(Activity)

        if rejected_activity.type == self.Types.FOLLOW:
            request = FollowRequest.objects.filter(activity=rejected_activity).first()
            if request is not None:
                request.reject()

    def _do_undo(self):
        to_undo = self.object and Activity.objects.filter(reference=self.object).first()

        if to_undo is None:
            return

        if to_undo:
            to_undo.undo()

    def _undo_undo(self):
        logger.info("Trying to undo an Undo activity. Should it be possible?")
        return

    def do(self):
        if not self.actor:
            logger.warning("Can not do anything with activity that has no actor")
            return

        action = {
            self.Types.ACCEPT: self._do_accept,
            self.Types.ANNOUNCE: self._do_announce,
            self.Types.FOLLOW: self._do_follow,
            self.Types.LIKE: self._do_like,
            self.Types.UNDO: self._do_undo,
            self.Types.REJECT: self._do_reject,
            self.Types.ADD: self._do_add,
            self.Types.REMOVE: self._do_remove,
        }.get(self.type, self._do_nothing)

        action()

        activity_done.send_robust(activity=self, sender=self.__class__)

    def undo(self):
        action = {
            self.Types.ANNOUNCE: self._undo_announce,
            self.Types.FOLLOW: self._undo_follow,
            self.Types.LIKE: self._undo_like,
        }.get(self.type, self._do_nothing)

        action()


# Non-ActivityPub models

# The models defined below are not specific to ActivityPub, but can
# help us in supporting business logic.


class ActivityPubServer(models.Model):
    class Software(models.TextChoices):
        MASTODON = "Mastodon"
        FEDIBIRD = "Fedibird"
        HOMETOWN = "Hometown"
        BIRDSITELIVE = "BirdsiteLive"
        TAKAHE = "Takahe"
        PLEROMA = "Pleroma"
        AKKOMA = "Akkoma"
        BONFIRE = "Bonfire"
        MITRA = "Mitra"
        MISSKEY = "Misskey"
        CALCKEY = "CalcKey"
        FIREFISH = "Firefish"
        GOTOSOCIAL = "Gotosocial"
        FUNKWHALE = "Funkwhale"
        PIXELFED = "Pixelfed"
        PEERTUBE = "Peertube"
        LEMMY = "Lemmy"
        KBIN = "Kbin"
        WRITE_FREELY = "Write Freely"
        PLUME = "Plume"
        BOOKWYRM = "Bookwyrm"
        WORDPRESS = "Wordpress"
        MICRODOTBLOG = "Microdotblog"
        MOBILIZON = "Mobilizon"
        GANCIO = "Gancio"
        SOCIALHOME = "Socialhome"
        DIASPORA = "Diaspora"
        HUBZILLA = "Hubzilla"
        FRIENDICA = "Friendica"
        GNU_SOCIAL = "GNU Social"
        FORGEJO = "Forgejo"
        ACTIVITY_RELAY = "Activity Relay"
        OTHER = "Other"

        @classmethod
        def get_family(cls, software_name):
            return {
                "mastodon": cls.MASTODON,
                "hometown": cls.MASTODON,
                "fedibird": cls.MASTODON,
                "birdsitelive": cls.BIRDSITELIVE,
                "bonfire": cls.BONFIRE,
                "takahe": cls.TAKAHE,
                "firefish": cls.FIREFISH,
                "calckey": cls.FIREFISH,
                "misskey": cls.MISSKEY,
                "mitra": cls.MITRA,
                "gotosocial": cls.GOTOSOCIAL,
                "lemmy": cls.LEMMY,
                "kbin": cls.KBIN,
                "writefreely": cls.WRITE_FREELY,
                "plume": cls.PLUME,
                "microdotblog": cls.MICRODOTBLOG,
                "wordpress": cls.WORDPRESS,
                "bookwyrm": cls.BOOKWYRM,
                "funkwhale": cls.FUNKWHALE,
                "peertube": cls.PEERTUBE,
                "pixelfed": cls.PIXELFED,
                "mobilizon": cls.MOBILIZON,
                "gancio": cls.GANCIO,
                "hubzilla": cls.HUBZILLA,
                "socialhome": cls.SOCIALHOME,
                "diaspora": cls.DIASPORA,
                "friendica": cls.FRIENDICA,
                "gnu social": cls.GNU_SOCIAL,
                "forgejo": cls.FORGEJO,
                "activity-relay": cls.ACTIVITY_RELAY,
            }.get(software_name.lower(), cls.OTHER)

    domain = models.OneToOneField(Domain, related_name="instance", on_delete=models.CASCADE)
    nodeinfo = models.JSONField(null=True, blank=True)
    software_family = models.CharField(
        max_length=50, choices=Software.choices, default=Software.OTHER
    )
    software = models.CharField(max_length=60, null=True, db_index=True)
    version = models.CharField(max_length=60, null=True, blank=True)
    actor = models.OneToOneField(
        Actor, null=True, blank=True, on_delete=models.SET_NULL, related_name="domain_actor"
    )

    @property
    def full_software_identifier(self):
        return f"{self.software or ''} {self.version or ''}".strip()

    @property
    def is_mastodon_compatible(self):
        return self.software_family in [
            self.Software.MASTODON,
            self.Software.HOMETOWN,
            self.Software.PLEROMA,
            self.Software.AKKOMA,
            self.Software.TAKAHE,
            self.Software.MITRA,
            self.Software.GOTOSOCIAL,
            self.Software.PIXELFED,
        ]

    def get_nodeinfo(self):
        try:
            NODEINFO_URLS = [
                "http://nodeinfo.diaspora.software/ns/schema/2.0",
                "http://nodeinfo.diaspora.software/ns/schema/2.1",
            ]

            metadata_response = requests.get(f"{self.domain.url}/.well-known/nodeinfo")
            metadata_response.raise_for_status()
            metadata = metadata_response.json()

            for link in metadata.get("links", []):
                if link.get("rel") in NODEINFO_URLS:
                    nodeinfo20_url = link.get("href")
                    node_response = requests.get(nodeinfo20_url)
                    node_response.raise_for_status()
                    node_data = node_response.json()
                    serializer = NodeInfoSerializer(data=node_data)
                    assert serializer.is_valid(), "Could not parse node info data"
                    software = serializer.data["software"]
                    self.nodeinfo = node_data
                    self.software_family = self.Software.get_family(software["name"])
                    self.software = software["name"]
                    self.version = software["version"]
                    self.save()
                    break
        except (
            requests.HTTPError,
            ssl.SSLCertVerificationError,
            ssl.SSLError,
            json.JSONDecodeError,
        ):
            logger.warning(f"Failed to get nodeinfo from {self.domain}")

    def build_collection_page(self, collection, **kw):
        current_page = collection.first and collection.first.get_by_context(CollectionPageContext)

        while (current_page and current_page.next) is not None:
            current_page = current_page.next.get_by_context(CollectionPageContext)

        ulid = str(generate_ulid())
        if app_settings.Instance.collection_page_view_name:
            uri = self.reverse_view(app_settings.Instance.collection_page_view_name, pk=ulid)
        else:
            uri = f"{self.domain.url}/pages/{ulid}"
        reference = Reference.make(uri)

        page_types = CollectionPageContext.Types

        page = CollectionPageContext.objects.create(
            reference=reference,
            part_of=collection.reference,
            previous=current_page and current_page.reference,
            type=page_types.ORDERED if collection.is_ordered else page_types.UNORDERED,
            **kw,
        )

        if current_page is None:
            collection.first = page.reference
        else:
            current_page.next = page.reference
            current_page.save()

        collection.last = page.reference
        collection.save()

        return page

    def __str__(self):
        return self.domain.url


class Account(models.Model):
    actor = models.OneToOneField(Actor, related_name="account", on_delete=models.CASCADE)
    domain = models.ForeignKey(Domain, related_name="accounts", on_delete=models.CASCADE)
    username = models.CharField(max_length=200, db_index=True)

    objects = AccountManager()
    local = QueryManager(domain__local=True)

    @property
    def subject_name(self):
        return getattr(self, "_subject_name", f"@{self.username}@{self.domain.netloc}")

    def __str__(self):
        return self.subject_name

    class Meta:
        unique_together = ("domain", "username")


class FollowRequest(StatusModel, TimeStampedModel):
    STATUS = Choices("pending", "accepted", "rejected")
    activity = models.OneToOneField(
        Activity, related_name="follow_request", on_delete=models.CASCADE
    )

    @property
    def follower(self):
        return self.activity.actor

    @property
    def followed(self):
        return self.activity.object

    @transaction.atomic()
    def accept(self):
        if self.status == self.STATUS.accepted:
            return

        self.status = self.STATUS.accepted
        self.save()

        follower_ref = self.activity.actor
        followed_ref = self.activity.object

        # If any of the references is nullable, there is nothing we can add to any collection
        if follower_ref is None or followed_ref is None:
            return

        # TODO: should we resolve references too, or just having references is enough?
        follower: Optional[Actor] = follower_ref and follower_ref.get_by_context(Actor)
        followed: Optional[Actor] = followed_ref and followed_ref.get_by_context(Actor)

        # If followed is not on follower's following collection, add to it
        if follower is not None and follower.following is not None:
            following_collection = CollectionContext.make(reference=follower.following)
            if not following_collection.contains(followed_ref):
                following_collection.append(item=followed_ref)

        # If follower is not on followed's followers collection, add to it
        if followed is not None and followed.followers is not None:
            follower_collection = CollectionContext.make(reference=followed.followers)
            if not follower_collection.contains(follower_ref):
                follower_collection.append(item=follower_ref)

            logger.info(f"{followed} accepts follow from {follower}")

            # Generate and send the accept activity
            accept_reference = ActivityContext.generate_reference(followed_ref.domain)

            accept = Activity.make(
                accept_reference,
                actor=followed_ref,
                type=Activity.Types.ACCEPT,
                object=self.activity.reference,
            )

            Notification.objects.create(
                resource=accept.reference, sender=followed.reference, target=follower.inbox
            )

    @transaction.atomic()
    def rejected(self):
        if self.status == self.STATUS.rejected:
            return

        self.status = self.STATUS.rejected
        self.save()

        follower: Optional[Actor] = self.activity.actor and self.activity.actor.get_by_context(
            Actor
        )
        followed: Optional[Actor] = self.activity.object and self.activity.object.get_by_context(
            Actor
        )

        if followed is None or follower is None:
            return

        if followed.is_local and not follower.is_local:
            logger.info(f"{followed} rejects follow from {follower}")

            reject_reference = ActivityContext.generate_reference(followed.reference.domain)
            reject = Activity.make(
                reference=reject_reference,
                actor=followed.reference,
                type=Activity.Types.REJECT,
                object=self.activity.reference,
            )
            Notification.objects.create(
                resource=reject.reference, sender=followed.reference, target=follower.inbox
            )


__all__ = (
    "Account",
    "Actor",
    "Activity",
    "ActivityPubServer",
    "FollowRequest",
)
