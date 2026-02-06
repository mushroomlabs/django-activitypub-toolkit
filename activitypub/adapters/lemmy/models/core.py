import logging
import mimetypes
from datetime import timedelta
from typing import Optional

import mmh3
from django.conf import settings
from django.db import models
from django.utils import timezone
from model_utils.managers import InheritanceManager
from model_utils.models import TimeStampedModel
from rdflib import RDF, Graph
from taggit.managers import TaggableManager
from tree_queries.models import TreeNode

from activitypub.core.contexts import (
    AS2_CONTEXT,
    LEMMY_CONTEXT,
    MASTODON_CONTEXT,
    PEERTUBE,
    SCHEMA,
)
from activitypub.core.models import (
    AbstractContextModel,
    ActivityContext,
    ActivityPubServer,
    ActorContext,
    CollectionContext,
    Domain,
    EndpointContext,
    LinkContext,
    ObjectContext,
    Reference,
    ReferenceField,
    SecV1Context,
    SourceContentContext,
)
from activitypub.core.models import Language as BaseLanguage
from activitypub.core.models.fields import RelatedContextField

from ..choices import ListingTypes, PostListingModes, SortOrderTypes

LEMMY = LEMMY_CONTEXT.namespace
AS2 = AS2_CONTEXT.namespace
TOOT = MASTODON_CONTEXT.namespace

logger = logging.getLogger(__name__)


class Language(BaseLanguage):
    @property
    def internal_id(self):
        return int.from_bytes(self.code.encode(), byteorder="big", signed=False)

    @classmethod
    def get_by_internal_id(cls, internal_id: int):
        byte_length = max(1, (internal_id.bit_length() + 7) // 8)
        code_bytes = internal_id.to_bytes(byte_length, byteorder="big", signed=False)
        code = code_bytes.decode("utf-8")

        return cls.objects.get(code=code)

    class Meta:
        proxy = True


class LemmyContextModel(AbstractContextModel):
    CONTEXT = LEMMY_CONTEXT
    LINKED_DATA_FIELDS = {
        "matrix_user_id": LEMMY.matrixUserId,
        "remove_data": LEMMY.removeData,
        "locked": PEERTUBE.commentsEnabled,
        "distinguished": LEMMY.distinguished,
        "posting_restricted_to_mods": LEMMY.postingRestrictedToMods,
        "moderators": LEMMY.moderators,
        "featured": TOOT.featured,
        "languages": SCHEMA.inLanguage,
    }
    matrix_user_id = models.CharField(max_length=255, null=True, blank=True)
    remove_data = models.BooleanField(null=True, blank=True)
    locked = models.BooleanField(null=True, blank=True)
    distinguished = models.BooleanField(null=True, blank=True)
    posting_restricted_to_mods = models.BooleanField(null=True, blank=True)
    moderators = ReferenceField()
    featured = ReferenceField()
    language = ReferenceField()

    def __str__(self):
        return self.reference.uri

    @classmethod
    def generate_reference(cls, domain):
        return ObjectContext.generate_reference(domain=domain)

    @classmethod
    def should_handle_reference(cls, g: Graph, reference: Reference):
        is_removal_activity = reference.get_value(g, RDF.type) in [AS2.Block, AS2.Delete]
        has_remove = reference.get_value(g, LEMMY.removeData) is not None
        lemmy_predicates = (
            LEMMY.distinguished
            | LEMMY.locked
            | LEMMY.matrixUserId
            | LEMMY.postingRestrictedToMods
            | LEMMY.moderators
        )

        has_lemmy = reference.get_value(g, lemmy_predicates) is not None
        has_language = reference.get_value(g, SCHEMA.inLanguage) is not None
        return (is_removal_activity and has_remove) or has_lemmy or has_language

    @classmethod
    def load_from_graph(cls, g: Graph, reference: Reference):
        obj = super().load_from_graph(g=g, reference=reference)

        language_codes = [
            g.value(node, SCHEMA.identifier)
            for node in list(g.objects(reference.as_rdf, SCHEMA.inLanguage))
        ]
        languages = Language.objects.filter(
            code__in=[code.toPython().lower() for code in language_codes if code is not None]
        )

        if obj is None:
            obj = cls.make(reference=reference)

        references = Reference.objects.filter(uri__in=[lang.reference.uri for lang in languages])

        obj.language.set(references)
        return obj


class LemmyObject(models.Model):
    object_id = models.PositiveBigIntegerField(editable=False)
    reference = models.ForeignKey(
        Reference, related_name="lemmy_%(class)ss", on_delete=models.CASCADE
    )

    objects = InheritanceManager()

    as2 = RelatedContextField(ObjectContext)
    lemmy = RelatedContextField(LemmyContextModel)

    @property
    def is_local(self):
        return self.reference.is_local

    def save(self, *args, **kw):
        if not self.object_id:
            self.object_id = LemmyObject.get_object_id(self.identifier)
        return super().save(*args, **kw)

    @property
    def identifier(self) -> str:
        return self.reference.uri

    @property
    def site(self):
        return Site.objects.filter(reference__domain=self.reference.domain).first()

    @property
    def language(self):
        return self.lemmy.language.first()

    @property
    def local_site(self):
        return LocalSite.objects.filter(site__reference__domain=self.reference.domain).first()

    def __str__(self):
        return self.reference.uri

    @staticmethod
    def get_object_id(identifier):
        # Lemmy's API operates on integer, and due to the js sdk we
        # are restricted to max value of a Javascript double number,
        # which is 2^53.

        # We would like to make that every lemmy object keeps its same
        # id to keep its URL path stable, regardless of server/domain using it.

        # To achieve that, we will create an 'object_id' for every
        # Lemmy object record which will be derived from its reference
        # URI. The URIs are unique and stable, so it makes sense to use them.

        # The issue of this approach is that we need to map a string
        # to a integer. We could use larger hash functions to reduce
        # the chance of collisions, but due to JS lower limit we will
        # have to do a module operation anyway. The range of 2^53
        # means that there is the chance of collision is ~1 in 95
        # million. We will live with this risk for now.

        hash_128 = mmh3.hash128(str(identifier).encode())
        return hash_128 % 2**53

    @classmethod
    def make(cls, reference, **attrs):
        obj, _ = cls.objects.get_or_create(reference=reference, defaults=attrs)
        return obj

    @classmethod
    def resolve(cls, reference: Reference):
        logger.info(f"{cls.__name__} has not implemented the resolve method yet.")
        return

    class Meta:
        unique_together = ("reference", "object_id")


class Community(LemmyObject):
    class VisibilityTypes(models.TextChoices):
        PUBLIC = "Public"
        LOCAL = "LocalOnly"

    _base_object = models.OneToOneField(
        LemmyObject, parent_link=True, related_name="community_data", on_delete=models.CASCADE
    )

    removed = models.BooleanField(default=False)
    deleted = models.BooleanField(default=False)
    hidden = models.BooleanField(default=False)
    visibility = models.CharField(
        max_length=40, choices=VisibilityTypes, default=VisibilityTypes.PUBLIC
    )

    as2 = RelatedContextField(ActorContext)

    @property
    def site(self):
        return Site.objects.filter(reference__domain=self.reference.domain).first()

    @property
    def description(self):
        source_ref = self.as2.source.first()
        source = source_ref and source_ref.get_by_context(SourceContentContext)
        return source and source.content

    @property
    def discussion_languages(self):
        return Language.objects.filter(reference__in=self.lemmy.languages.all())

    @classmethod
    def resolve(cls, reference: Reference):
        as2_object = reference.get_by_context(ActorContext)
        if as2_object is None:
            return

        if as2_object.type != ActorContext.Types.GROUP:
            return

        community, _ = cls.objects.get_or_create(reference=reference)
        return community

    class Meta:
        verbose_name_plural = "Communities"


class CustomEmoji(LemmyObject):
    _base_object = models.OneToOneField(
        LemmyObject, parent_link=True, related_name="emoji_data", on_delete=models.CASCADE
    )

    category = models.CharField(max_length=80, null=True, blank=True)
    keywords = TaggableManager()
    emoji = RelatedContextField(ObjectContext)


class Post(LemmyObject):
    _base_object = models.OneToOneField(
        LemmyObject, parent_link=True, related_name="post_data", on_delete=models.CASCADE
    )
    community = models.ForeignKey(LemmyObject, related_name="posts", on_delete=models.CASCADE)
    removed = models.BooleanField(default=False)
    deleted = models.BooleanField(default=False)
    featured_community = models.BooleanField(default=False)
    featured_local = models.BooleanField(default=False)

    @property
    def identifier(self) -> str:
        return f"{self.reference.uri}-{self.community.reference.uri}"

    @property
    def creator(self):
        actor_ref = self.as2.attributed_to.first()
        return actor_ref and Person.objects.filter(reference=actor_ref).first()

    @property
    def content(self):
        source_ref = self.as2.source.first()
        source = source_ref and source_ref.get_by_context(SourceContentContext)
        return source and source.content

    @property
    def attachment(self):
        ref = self.as2.attachments.first()
        if ref:
            return ref.get_by_context(ObjectContext) or ref.get_by_context(LinkContext)
        return None

    @property
    def thumbnail(self):
        ref = self.as2.image.first()
        if ref:
            return ref.get_by_context(ObjectContext) or ref.get_by_context(LinkContext)
        return None

    @property
    def link_url(self):
        links = LinkContext.objects.filter(
            type=LinkContext.Types.LINK, reference__in=self.as2.attachments.all()
        )
        return links.values_list("href", flat=True).first()

    @link_url.setter
    def link_url(self, value):
        LinkContext.objects.filter(
            type=LinkContext.Types.LINK, reference__in=self.as2.attachments.all()
        ).delete()
        if value is not None:
            link_reference = Reference.make(Reference.generate_skolem())
            LinkContext.objects.create(reference=link_reference, href=value)
            self.as2.attachments.add(link_reference)

    @property
    def image_url(self):
        images = ObjectContext.objects.filter(
            type=ObjectContext.Types.IMAGE, reference__in=self.as2.attachments.all()
        )
        return images.values_list("url", flat=True).first()

    @image_url.setter
    def image_url(self, value):
        ObjectContext.objects.filter(
            type=ObjectContext.Types.IMAGE, reference__in=self.as2.attachments.all()
        ).delete()
        if value is not None:
            image_reference = Reference.make(Reference.generate_skolem())
            ObjectContext.objects.create(reference=image_reference, url=value)
            self.as2.attachments.add(image_reference)

    @property
    def url(self):
        return self.link_url or self.image_url

    @url.setter
    def url(self, value):
        mime_type, _ = mimetypes.guess_type(value)
        if "image" in mime_type:
            self.image_url = value
            self.link_url = None
        else:
            self.image_url = None
            self.link_url = value

    @classmethod
    def resolve(cls, reference: Reference):
        as2 = reference.get_by_context(ObjectContext)

        if as2 is None:
            return

        if as2.in_reply_to.exists():
            # Posts never have a reply to someone.
            return

        if as2.type not in [ObjectContext.Types.PAGE, ObjectContext.Types.NOTE]:
            # Lemmy only understands posts if they are page or note
            return

        # So, it is a post, let's resolve the related objects...
        for ref in as2.attributed_to.all():
            ref.resolve()
        for ref in as2.audience.all():
            ref.resolve()

        communities = Community.objects.filter(reference__in=as2.audience.all())
        for community in communities:
            cls.objects.get_or_create(reference=reference, community=community)


class Comment(LemmyObject, TreeNode):
    _base_object = models.OneToOneField(
        LemmyObject, parent_link=True, related_name="comment_data", on_delete=models.CASCADE
    )

    post = models.ForeignKey(LemmyObject, related_name="comments", on_delete=models.CASCADE)
    removed = models.BooleanField(default=False)
    deleted = models.BooleanField(default=False)

    @property
    def identifier(self) -> str:
        return f"{self.reference.uri}-{self.post.reference.uri}"

    @property
    def creator(self):
        actor_ref = self.as2.attributed_to.first()
        return actor_ref and Person.objects.filter(reference=actor_ref).first()

    @property
    def content(self):
        source_ref = self.as2.source.first()
        source = source_ref and source_ref.get_by_context(SourceContentContext)
        return source and source.content

    @classmethod
    def resolve(cls, reference: Reference):
        as2 = reference.get_by_context(ObjectContext)

        if as2 is None:
            return

        if not as2.in_reply_to.exists():
            # Comments always have a reply to someone.
            return

        if as2.type != ObjectContext.Types.NOTE:
            # Lemmy only understands note comments
            return

        # So, it is a comment, let's resolve the related objects...
        for ref in as2.attributed_to.all():
            ref.resolve()
        for ref in as2.audience.all():
            ref.resolve()

        communities = Community.objects.filter(reference__in=as2.audience.all())
        for community in communities:
            Comment.build_tree(as2_object=as2, community=community)

    @staticmethod
    def build_tree(
        as2_object: ObjectContext, community: Community
    ) -> tuple[Optional[Post], Optional["Comment"]]:
        """
        Given a comment object, finds out its parent through the object 'in_reply_to'
        """

        parent_reference = as2_object.in_reply_to.first()

        if parent_reference is None:
            logger.warning(f"{as2_object.reference} does not look like a comment")
            return (None, None)

        post = Post.objects.filter(reference=parent_reference, community=community.id).first()

        if post is not None:
            # No parent comment
            comment = Comment.make(reference=as2_object.reference, post=post, parent=None)
            return (comment.post, comment)

        parent_comment = Comment.objects.filter(
            reference=parent_reference, post__post_data__community=community
        ).first()

        if parent_comment is not None:
            comment = Comment.make(
                reference=as2_object.reference, post=parent_comment.post, parent=parent_comment
            )
            return (comment.post, comment)

        # If we got this far, it means that we have the reference for
        # the parent, but it's not in the database yet. Let's try to build it first,
        # then we create the  .
        parent_reference.resolve()
        parent_object = parent_reference.get_by_context(ObjectContext)
        if parent_object is not None:
            post, parent_comment = Comment.build_tree(parent_object, community)
            if post is not None:
                comment = Comment.make(
                    reference=as2_object.reference, post=post, parent=parent_comment
                )
                return (post, comment)
        return (None, None)


class PrivateMessage(LemmyObject):
    _base_object = models.OneToOneField(
        LemmyObject,
        parent_link=True,
        related_name="private_message_data",
        on_delete=models.CASCADE,
    )

    sender = models.ForeignKey(Reference, related_name="+", on_delete=models.CASCADE)
    recipient = models.ForeignKey(Reference, related_name="+", on_delete=models.CASCADE)
    removed = models.BooleanField(default=False)
    deleted = models.BooleanField(default=False)
    read = models.BooleanField(default=False)


class Person(LemmyObject):
    _base_object = models.OneToOneField(
        LemmyObject, parent_link=True, related_name="person_data", on_delete=models.CASCADE
    )

    liked_posts = models.ManyToManyField(Post, related_name="liked_by")
    liked_comments = models.ManyToManyField(Comment, related_name="liked_by")
    blocked_instances = models.ManyToManyField(Domain)
    blocked_communities = models.ManyToManyField(Community, related_name="blocked_by")
    moderates = models.ManyToManyField(Community, related_name="moderated_by")
    subscribed_communities = models.ManyToManyField(Community, related_name="subscribers")

    as2 = RelatedContextField(ActorContext)

    def is_subscribed(self, community: Community):
        return self.subscribed_communities.filter(reference=community.reference).exists()

    @property
    def removed(self):
        return False

    @property
    def deleted(self):
        return False

    @property
    def source(self):
        source_ref = self.as2 and self.as2.source.first()
        return source_ref and source_ref.get_by_context(ObjectContext)

    @property
    def last_refreshed_at(self):
        return self.reference.resolved_at

    @property
    def bot_account(self) -> bool:
        return self.as2.type != ActorContext.Types.PERSON

    @property
    def is_admin(self) -> bool:
        return self.site.admins.filter(id=self.id).exists()

    def __str__(self):
        return self.reference.uri

    @classmethod
    def resolve(cls, reference: Reference):
        as2 = reference.get_by_context(ActorContext)

        if as2 is None:
            return

        if as2.type not in [ActorContext.Types.PERSON, ActorContext.Types.SERVICE]:
            # counter intuitive: the table is called person, but bot
            # accounts also should get an entry here and they use the service type
            return

        cls.objects.get_or_create(reference=reference)
        return


class Report(LemmyObject):
    """Reference points to the as:Flag"""

    resolved_by = models.ForeignKey(
        Reference, related_name="+", null=True, blank=True, on_delete=models.SET_NULL
    )
    resolved_on = models.DateTimeField(null=True, blank=True)

    @property
    def resolved(self):
        return self.resolved_by is not None

    as2 = RelatedContextField(ActivityContext)


# Site
class Site(LemmyObject):
    _base_object = models.OneToOneField(
        LemmyObject, parent_link=True, related_name="site_data", on_delete=models.CASCADE
    )

    allowed_instances = models.ManyToManyField(
        Domain, related_name="allowed_lemmy_instances", blank=True
    )
    blocked_instances = models.ManyToManyField(
        Domain, related_name="blocked_lemmy_instances", blank=True
    )
    admins = models.ManyToManyField(Person, related_name="site_admins", blank=True)

    # Federation state tracking
    last_successful_notification_id = models.UUIDField(null=True, blank=True)
    last_successful_published_time = models.DateTimeField(null=True, blank=True)
    fail_count = models.PositiveIntegerField(default=0)
    last_retry = models.DateTimeField(null=True, blank=True)

    as2 = RelatedContextField(ActorContext)
    secv1 = RelatedContextField(SecV1Context)

    @property
    def instance(self):
        return ActivityPubServer.objects.filter(domain=self.reference.domain).first()

    @property
    def site(self):
        return self

    @property
    def inbox_url(self):
        return self.as2.inbox and self.as2.inbox.uri

    @property
    def sidebar(self):
        source_ref = self.as2.source.first()
        source = source_ref and source_ref.get_by_context(ObjectContext)
        return source and source.content

    @property
    def published(self):
        """When we first encountered this instance"""
        return self.reference.created

    @property
    def updated(self):
        """Last time we saw activity from this instance"""
        return self.reference.modified

    @property
    def software(self):
        """Software name from nodeinfo"""
        return self.instance and self.instance.software

    @property
    def version(self):
        """Software version from nodeinfo"""
        return self.instance and self.instance.version

    @property
    def next_retry(self):
        """Calculate next retry time using exponential backoff"""
        if not self.last_retry or self.fail_count == 0:
            return None
        backoff_seconds = 60 * (2 ** min(self.fail_count - 1, 10))
        return self.last_retry + timedelta(seconds=backoff_seconds)

    @classmethod
    def resolve(cls, reference: Reference):
        as2 = reference.get_by_context(ActorContext)

        if as2 is None:
            return

        if as2.type != ActorContext.Types.APPLICATION:
            return

        cls.objects.get_or_create(reference=reference)
        return


class LocalSite(models.Model):
    class RegistrationModes(models.TextChoices):
        CLOSED = "Closed"
        REQUIRE_APPLICATION = "RequireApplication"
        OPEN = "Open"

    class Themes(models.TextChoices):
        BROWSER = ("browser", "Browser Default")
        BROWSER_COMPACT = ("browser_compact", "Browser Default Compact")

    class CaptchaDifficulty(models.TextChoices):
        LOW = "low"
        MEDIUM = "medium"
        HIGH = "high"

    site = models.OneToOneField(Site, related_name="local_site", on_delete=models.CASCADE)
    enable_downvotes = models.BooleanField(default=True)
    enable_nsfw = models.BooleanField(default=False)
    community_creation_admin_only = models.BooleanField(default=True)
    require_email_verification = models.BooleanField(default=False)
    application_question = models.TextField(blank=True, null=True)
    private_instance = models.BooleanField(default=False)
    default_theme = models.CharField(max_length=30, choices=Themes, default=Themes.BROWSER)
    default_post_listing_type = models.CharField(
        max_length=16, choices=ListingTypes, default=ListingTypes.ALL
    )
    legal_information = models.TextField(blank=True, null=True)
    hide_modlog_mod_names = models.BooleanField(default=False)
    application_email_admins = models.BooleanField(default=False)
    slur_filter_regex = models.TextField(blank=True, null=True)
    actor_name_max_length = models.PositiveSmallIntegerField(default=40)
    federation_enabled = models.BooleanField(default=False)
    captcha_enabled = models.BooleanField(default=False)
    captcha_difficulty = models.CharField(
        max_length=10, choices=CaptchaDifficulty, default=CaptchaDifficulty.LOW
    )
    updated = models.DateTimeField(auto_now=True)
    registration_mode = models.CharField(
        max_length=32, choices=RegistrationModes, default=RegistrationModes.REQUIRE_APPLICATION
    )
    reports_email_admins = models.BooleanField(default=False)
    federation_signed_fetch = models.BooleanField(default=False)
    default_post_listing_mode = models.CharField(max_length=16, default=PostListingModes.CARD)
    default_sort_type = models.CharField(
        max_length=16, choices=SortOrderTypes.choices, default=SortOrderTypes.ACTIVE
    )
    custom_emojis = models.ManyToManyField(CustomEmoji, blank=True)
    discussion_languages = models.ManyToManyField(Language, blank=True)

    @property
    def installed_languages(self):
        return Language.objects.all()

    def __str__(self):
        return self.site.reference.uri

    @classmethod
    def setup(cls, instance_uri: str):
        domain = Domain.make(instance_uri, local=True)
        reference = Reference.make(uri=instance_uri)

        now = timezone.now()

        actor = ActorContext.make(
            reference=reference, type=ActorContext.Types.APPLICATION, published=now, updated=now
        )

        if reference.get_by_context(SecV1Context) is None:
            SecV1Context.generate_keypair(owner_reference=reference)

        endpoints_ref = actor.endpoints or Reference.objects.create(
            uri=Reference.generate_skolem(), domain=domain
        )
        endpoints, endpoints_created = EndpointContext.objects.get_or_create(
            reference=endpoints_ref
        )

        if endpoints_created or endpoints.shared_inbox is None:
            shared_inbox_ref = CollectionContext.generate_reference(domain=domain)
            CollectionContext.make(reference=shared_inbox_ref)
            endpoints.shared_inbox = shared_inbox_ref.uri
            endpoints.save()

        if actor.inbox is None:
            inbox_ref = CollectionContext.generate_reference(domain)
            CollectionContext.make(reference=inbox_ref)
            actor.inbox = inbox_ref

        if actor.outbox is None:
            outbox_ref = CollectionContext.generate_reference(domain)
            CollectionContext.make(reference=outbox_ref)
            actor.outbox = outbox_ref

        actor.save()
        instance, _ = ActivityPubServer.objects.get_or_create(domain=domain)
        site, _ = Site.objects.get_or_create(reference=reference)
        site.actor = actor
        site.save()

        local_site, _ = cls.objects.get_or_create(site=site)
        rate_limits, _ = LocalSiteRateLimit.objects.get_or_create(local_site=local_site)
        return local_site


class LocalSiteRateLimit(models.Model):
    local_site = models.OneToOneField(
        LocalSite, related_name="rate_limits", on_delete=models.CASCADE, primary_key=True
    )
    message = models.PositiveSmallIntegerField(default=999)
    message_per_second = models.PositiveSmallIntegerField(default=60)
    post = models.PositiveSmallIntegerField(default=999)
    post_per_second = models.PositiveSmallIntegerField(default=600)
    register = models.PositiveSmallIntegerField(default=999)
    register_per_second = models.PositiveSmallIntegerField(default=60)
    image = models.PositiveSmallIntegerField(default=999)
    image_per_second = models.PositiveSmallIntegerField(default=3600)
    comment = models.PositiveSmallIntegerField(default=999)
    comment_per_second = models.PositiveSmallIntegerField(default=600)
    search = models.PositiveSmallIntegerField(default=999)
    search_per_second = models.PositiveSmallIntegerField(default=600)
    published = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    import_user_settings = models.PositiveSmallIntegerField(default=99)
    import_user_settings_per_second = models.PositiveSmallIntegerField(default=3600)


class LocalSiteBlockedUrl(models.Model):
    local_site = models.ForeignKey(
        LocalSite, related_name="blocked_urls", on_delete=models.CASCADE
    )
    url = models.URLField(unique=True)


class Tagline(TimeStampedModel):
    local_site = models.ForeignKey(LocalSite, related_name="taglines", on_delete=models.CASCADE)
    content = models.TextField()

    def __str__(self):
        return self.content


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, related_name="lemmy_profile", on_delete=models.CASCADE
    )

    hidden_posts = models.ManyToManyField(Post, related_name="hidden_by")
    read_posts = models.ManyToManyField(Post, related_name="read_by")
    saved_posts = models.ManyToManyField(Post, related_name="saved_by")

    hidden_comments = models.ManyToManyField(Comment, related_name="hidden_by")
    read_comments = models.ManyToManyField(Comment, related_name="read_by")
    saved_comments = models.ManyToManyField(Comment, related_name="saved_by")

    @property
    def identity(self):
        return self.user.identities.filter(is_primary=True).first()

    @property
    def actor(self):
        return self.identity and self.identity.actor

    @property
    def person(self):
        return self.actor and Person.objects.filter(reference=self.actor.reference).first()

    @property
    def site(self):
        return self.person and self.person.site

    def __str__(self):
        return self.user.username


class UserSettings(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, related_name="lemmy_settings", on_delete=models.CASCADE
    )
    show_nsfw = models.BooleanField(default=False)
    theme = models.TextField()
    default_sort_type = models.CharField(
        max_length=30, choices=SortOrderTypes.choices, default=SortOrderTypes.ACTIVE
    )
    default_listing_type = models.CharField(
        max_length=30, choices=ListingTypes.choices, default=ListingTypes.LOCAL
    )
    interface_language = models.CharField(max_length=20, default="browser")
    show_avatars = models.BooleanField(default=True)
    send_notifications_to_email = models.BooleanField(default=False)
    show_scores = models.BooleanField(default=True)
    show_bot_accounts = models.BooleanField(default=True)
    show_read_posts = models.BooleanField(default=True)
    email_verified = models.BooleanField(default=False)
    accepted_application = models.BooleanField(default=False)
    totp_2fa_secret = models.TextField(blank=True, null=True)
    open_links_in_new_tab = models.BooleanField(default=False)
    blur_nsfw = models.BooleanField(default=True)
    auto_expand = models.BooleanField(default=False)
    infinite_scroll_enabled = models.BooleanField(default=False)
    admin = models.BooleanField(default=False)
    post_listing_mode = models.CharField(
        max_length=30, choices=PostListingModes.choices, default=PostListingModes.LIST
    )
    totp_2fa_enabled = models.BooleanField(default=False)
    enable_keyboard_navigation = models.BooleanField(default=True)
    enable_animated_images = models.BooleanField(default=True)
    collapse_bot_comments = models.BooleanField(default=False)
    last_donation_notification = models.DateTimeField(null=True)
    show_vote_score = models.BooleanField(default=True)
    show_upvotes = models.BooleanField(default=True)
    show_downvotes = models.BooleanField(default=True)
    show_upvote_percentage = models.BooleanField(default=False)
    languages = models.ManyToManyField(Language)

    def __str__(self):
        return self.user.username

    class Meta:
        verbose_name_plural = "User Settings"


class UserNotification(models.Model):
    class Types(models.TextChoices):
        MENTION = ("mention", "Mention")
        REPLY = ("response", "Reply to Post or Comment")
        PRIVATE_MESSAGE = ("message", "Direct Message")
        REPORT = ("report", "Content Report")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="notifications", on_delete=models.CASCADE
    )
    reference = models.ForeignKey(Reference, related_name="+", on_delete=models.CASCADE)
    read = models.BooleanField(default=False)

    class Meta:
        unique_together = ("user", "reference")


__all__ = (
    "CustomEmoji",
    "Comment",
    "Community",
    "Language",
    "LemmyContextModel",
    "Post",
    "PrivateMessage",
    "Person",
    "Report",
    "Site",
    "LocalSite",
    "LocalSiteRateLimit",
    "LocalSiteBlockedUrl",
    "Tagline",
    "UserProfile",
    "UserNotification",
    "UserSettings",
)
