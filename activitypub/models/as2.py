import logging

import rdflib
from django.db import models
from model_utils.managers import InheritanceManager
from rdflib import RDF, Namespace

from ..contexts import AS2_CONTEXT
from ..settings import app_settings
from .base import _file_location, generate_ulid
from .fields import RelatedContextField
from .linked_data import AbstractContextModel, Reference, ReferenceField
from .sec import SecV1Context

logger = logging.getLogger(__name__)

AS2 = AS2_CONTEXT.namespace
LDP = Namespace("http://www.w3.org/ns/ldp#")
PURL_RELATIONSHIP = Namespace("http://purl.org/vocab/relationship#")


class AbstractAs2ObjectContext(AbstractContextModel):
    """
    ActivityStreams 2.0 vocabulary context.
    Stores AS2-specific fields like name, type, published, actor, etc.
    """

    CONTEXT = AS2_CONTEXT
    LINKED_DATA_FIELDS = {
        "published": AS2.published,
        "updated": AS2.updated,
        "name": AS2.name,
        "content": AS2.content,
        "media_type": AS2.mediaType,
        "summary": AS2.summary,
        "start_time": AS2.startTime,
        "end_time": AS2.endTime,
        "duration": AS2.duration,
        "context": AS2.context,
        "generator": AS2.generator,
        "icon": AS2.icon,
        "image": AS2.image,
        "location": AS2.location,
        "preview": AS2.preview,
        "replies": AS2.replies,
        "likes": AS2.likes,
        "shares": AS2.shares,
        "tags": AS2.tag,
        "in_reply_to": AS2.inReplyTo,
        "attributed_to": AS2.attributedTo,
        "attachments": AS2.attachment,
        "audience": AS2.audience,
        "to": AS2.to,
        "cc": AS2.cc,
        "bto": AS2.bto,
        "bcc": AS2.bcc,
        # This one is a bit tricky. AS2.url can be both a simple URL
        # or a Link. So, both model fields map to the same attribute,
        # and serialization will overwrite the native url with the
        # link it is present.
        "url": AS2.url,
        "url_link": AS2.url,
    }

    name = models.TextField(null=True, blank=True)
    content = models.TextField(null=True, blank=True)
    summary = models.TextField(null=True, blank=True)
    published = models.DateTimeField(null=True, blank=True)
    updated = models.DateTimeField(null=True, blank=True)
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    duration = models.DurationField(null=True, blank=True)
    media_type = models.CharField(max_length=64, null=True, blank=True)

    url = models.URLField(null=True, blank=True)
    url_link = ReferenceField()

    context = ReferenceField()
    generator = ReferenceField()
    icon = ReferenceField()
    image = ReferenceField()
    location = ReferenceField()
    preview = ReferenceField()

    attributed_to = ReferenceField()
    in_reply_to = ReferenceField()
    tags = ReferenceField()
    attachments = ReferenceField()
    audience = ReferenceField()
    to = ReferenceField()
    cc = ReferenceField()
    bto = ReferenceField()
    bcc = ReferenceField()

    replies = models.ForeignKey(
        Reference,
        related_name="%(app_label)s_%(class)s_replies",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    likes = models.ForeignKey(
        Reference,
        related_name="%(app_label)s_%(class)s_likes",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    shares = models.ForeignKey(
        Reference,
        related_name="%(app_label)s_%(class)s_shares",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    @classmethod
    def should_handle_reference(cls, g: rdflib.Graph, reference: Reference):
        type = reference.get_value(g, predicate=RDF.type)
        return type is not None and str(type) in cls.Types.values

    class Meta:
        abstract = True


class LinkContext(AbstractContextModel):
    LINKED_DATA_FIELDS = {
        "type": RDF.type,
        "name": AS2.name,
        "href": AS2.href,
        "media_type": AS2.mediaType,
        "height": AS2.height,
        "width": AS2.width,
        "language": AS2.hreflang,
    }

    class Types(models.TextChoices):
        LINK = str(AS2.Link)
        MENTION = str(AS2.Mention)
        EMOJI = str(AS2.Emoji)
        HASHTAG = str(AS2.Hashtag)

    type = models.CharField(max_length=48, choices=Types.choices, default=Types.LINK)
    href = models.URLField()
    media_type = models.CharField(max_length=48, null=True, blank=True)
    name = models.TextField(null=True, blank=True)
    language = models.CharField(max_length=5, null=True, blank=True)
    height = models.PositiveIntegerField(null=True)
    width = models.PositiveIntegerField(null=True)
    preview = models.ForeignKey(
        Reference,
        related_name="link_previews",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )

    @classmethod
    def should_handle_reference(cls, g: rdflib.Graph, reference: Reference):
        has_href = reference.get_value(g, predicate=AS2.href) is not None

        if has_href:
            return True

        type = reference.get_value(g, predicate=RDF.type)
        return type is not None and str(type) in cls.Types.values


class BaseAs2ObjectContext(AbstractAs2ObjectContext):
    LINKED_DATA_FIELDS = AbstractAs2ObjectContext.LINKED_DATA_FIELDS | {
        "type": RDF.type,
        "source": AS2.source,
    }

    objects = InheritanceManager()

    @classmethod
    def should_handle_reference(cls, g: rdflib.Graph, reference: Reference):
        has_href = reference.get_value(g, predicate=AS2.href) is not None

        if has_href:
            return False

        type = reference.get_value(g, predicate=RDF.type)
        return type is not None and str(type) in cls.Types.values


class ObjectContext(BaseAs2ObjectContext):
    LINKED_DATA_FIELDS = BaseAs2ObjectContext.LINKED_DATA_FIELDS | {
        "sensitive": AS2.sensitive,
        "source": AS2.source,
    }

    # Extra context definitions for AS2 extensions not in the standard context
    EXTRA_CONTEXT = {
        "sensitive": {"@id": "as:sensitive", "@type": "xsd:boolean"},
        "Hashtag": "as:Hashtag",
        "Emoji": "as:Emoji",
    }

    class Types(models.TextChoices):
        ARTICLE = str(AS2.Article)
        AUDIO = str(AS2.Audio)
        DOCUMENT = str(AS2.Document)
        EVENT = str(AS2.Event)
        IMAGE = str(AS2.Image)
        QUESTION = str(AS2.Question)
        NOTE = str(AS2.Note)
        PAGE = str(AS2.Page)
        PLACE = str(AS2.Place)
        PROFILE = str(AS2.Profile)
        RELATIONSHIP = str(AS2.Relationship)
        TOMBSTONE = str(AS2.Tombstone)
        VIDEO = str(AS2.Video)
        HASHTAG = str(AS2.Hashtag)
        EMOJI = str(AS2.Emoji)

    type = models.CharField(max_length=128, choices=Types.choices)
    sensitive = models.BooleanField(default=False)
    source = ReferenceField()

    @classmethod
    def generate_reference(cls, domain):
        ulid = str(generate_ulid())
        if app_settings.Instance.object_view_name:
            uri = domain.reverse_view(app_settings.Instance.object_view_name, pk=ulid)
        else:
            uri = f"{domain.url}/objects/{ulid}"
        return Reference.make(uri)

    def __str__(self):
        return self.uri or f"Unreferenced object #{self.id} ({self.get_type_display()})"


class EndpointContext(AbstractContextModel):
    LINKED_DATA_FIELDS = {
        "proxy_url": AS2.proxyUrl,
        "oauth_authorization_endpoint": AS2.oauthAuthorizationEndpoint,
        "oauth_token_endpoint": AS2.oauthTokenEndpoint,
        "authorize_client_key_endpoint": AS2.provideClientKey,
        "sign_client_key_endpoint": AS2.signClientKey,
        "shared_inbox": AS2.sharedInbox,
    }

    proxy_url = models.URLField(null=True, blank=True)
    oauth_authorization_endpoint = models.URLField(null=True, blank=True)
    oauth_token_endpoint = models.URLField(null=True, blank=True)
    authorize_client_key_endpoint = models.URLField(null=True, blank=True)
    sign_client_key_endpoint = models.URLField(null=True, blank=True)
    shared_inbox = models.URLField(null=True, blank=True)

    @classmethod
    def should_handle_reference(cls, g: rdflib.Graph, reference: Reference):
        predicates = cls.LINKED_DATA_FIELDS.values()
        values = [reference.get_value(g=g, predicate=predicate) for predicate in predicates]
        return any([v is not None for v in values])


class ActorContext(BaseAs2ObjectContext):
    LINKED_DATA_FIELDS = BaseAs2ObjectContext.LINKED_DATA_FIELDS | {
        "type": RDF.type,
        "inbox": LDP.inbox | AS2.inbox,
        "outbox": LDP.outbox | AS2.outbox,
        "following": AS2.following,
        "followers": AS2.followers,
        "liked": AS2.liked,
        "preferred_username": AS2.preferredUsername,
        "manually_approves_followers": AS2.manuallyApprovesFollowers,
        "endpoints": AS2.endpoints,
        "moved_to": AS2.movedTo,
        "also_known_as": AS2.alsoKnownAs,
        "source": AS2.source,
    }

    EXTRA_CONTEXT = {
        "manuallyApprovesFollowers": {
            "@id": "as:manuallyApprovesFollowers",
            "@type": "xsd:boolean",
        },
        "movedTo": {"@id": "as:movedTo", "@type": "@id"},
        "alsoKnownAs": {"@id": "as:alsoKnownAs", "@type": "@id"},
    }

    class Types(models.TextChoices):
        PERSON = str(AS2.Person)
        GROUP = str(AS2.Group)
        SERVICE = str(AS2.Service)
        ORGANIZATION = str(AS2.Organization)
        APPLICATION = str(AS2.Application)

    type = models.CharField(max_length=64, choices=Types.choices)
    preferred_username = models.CharField(max_length=100, null=True, blank=True)
    manually_approves_followers = models.BooleanField(default=False)
    moved_to = ReferenceField()
    also_known_as = ReferenceField()
    endpoints = models.ForeignKey(
        Reference, related_name="actor_endpoints", null=True, blank=True, on_delete=models.SET_NULL
    )

    source = ReferenceField()
    inbox = models.OneToOneField(
        Reference,
        related_name="inbox_owner_actor",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    outbox = models.OneToOneField(
        Reference,
        related_name="outbox_owner_actor",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    following = models.OneToOneField(
        Reference,
        related_name="actor_follows",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    followers = models.OneToOneField(
        Reference,
        related_name="actor_followers",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    liked = models.OneToOneField(
        Reference,
        related_name="actor_liked",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    secv1 = RelatedContextField(SecV1Context)

    @property
    def followed_by(self):
        return (
            self.followers and self.followers.items.select_subclasses() or Reference.objects.none()
        )

    @property
    def follows(self):
        return (
            self.following and self.following.items.select_subclasses() or Reference.objects.none()
        )

    @property
    def inbox_url(self):
        return self.inbox and self.inbox.uri

    @property
    def outbox_url(self):
        return self.outbox and self.outbox.uri

    @property
    def followers_url(self):
        return self.followers and self.followers.uri

    @property
    def following_url(self):
        return self.following and self.following.uri

    def __str__(self):
        return self.uri or f"Unreferenced actor {self.id}"


class ActivityContext(BaseAs2ObjectContext):
    LINKED_DATA_FIELDS = BaseAs2ObjectContext.LINKED_DATA_FIELDS | {
        "type": RDF.type,
        "actor": AS2.actor,
        "object": AS2.object,
        "target": AS2.target,
        "result": AS2.result,
        "instrument": AS2.instrument,
    }

    class Types(models.TextChoices):
        ACCEPT = str(AS2.Accept)
        ADD = str(AS2.Add)
        ANNOUNCE = str(AS2.Announce)
        ARRIVE = str(AS2.Arrive)
        BLOCK = str(AS2.Block)
        CREATE = str(AS2.Create)
        DELETE = str(AS2.Delete)
        DISLIKE = str(AS2.Dislike)
        FLAG = str(AS2.Flag)
        FOLLOW = str(AS2.Follow)
        IGNORE = str(AS2.Ignore)
        INVITE = str(AS2.Invite)
        JOIN = str(AS2.Join)
        LEAVE = str(AS2.Leave)
        LIKE = str(AS2.Like)
        LISTEN = str(AS2.Listen)
        MOVE = str(AS2.Move)
        OFFER = str(AS2.Offer)
        QUESTION = str(AS2.Question)
        REJECT = str(AS2.Reject)
        READ = str(AS2.Read)
        REMOVE = str(AS2.Remove)
        TENTATIVE_REJECT = str(AS2.TentativeReject)
        TENTATIVE_ACCEPT = str(AS2.TentativeAccept)
        TRAVEL = str(AS2.Travel)
        UNDO = str(AS2.Undo)
        UPDATE = str(AS2.Update)
        VIEW = str(AS2.View)

    type = models.CharField(max_length=128, choices=Types.choices, db_index=True)

    actor = models.ForeignKey(
        Reference,
        related_name="activities_as_actor",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    object = models.ForeignKey(
        Reference,
        related_name="object_activities",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    target = models.ForeignKey(
        Reference,
        related_name="target_activities",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    result = models.ForeignKey(
        Reference,
        related_name="result_activities",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    origin = models.ForeignKey(
        Reference,
        related_name="origin_activities",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    instrument = models.ForeignKey(
        Reference,
        related_name="activities_as_target",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    result = models.ForeignKey(
        Reference,
        related_name="activities_as_result",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    instrument = models.ForeignKey(
        Reference,
        related_name="activities_as_instrument",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    @classmethod
    def generate_reference(cls, domain):
        ulid = str(generate_ulid())
        if app_settings.Instance.activity_view_name:
            uri = domain.reverse_view(app_settings.Instance.activity_view_name, pk=ulid)
        else:
            uri = f"{domain.url}/activities/{ulid}"
        return Reference.make(uri)


class QuestionContext(AbstractContextModel):
    LINKED_DATA_FIELDS = {
        "type": RDF.type,
        "closed": AS2.closed,
        "any_of": AS2.anyOf,
        "one_of": AS2.oneOf,
    }
    # Only applicable for Question Activities (or Objects if non-standard)
    closed = models.DateTimeField(null=True, blank=True)
    any_of = ReferenceField(related_name="multiple_choice_alternatives")
    one_of = ReferenceField(related_name="alternatives")

    @property
    def type(self):
        return str(AS2.Question)

    @classmethod
    def should_handle_reference(cls, g: rdflib.Graph, reference: Reference):
        type = reference.get_value(g, predicate=RDF.type)
        return type is not None and type == AS2.Question


class RelationshipProperties(models.Model):
    class Types(models.TextChoices):
        ACQUAINTANCE_OF = (
            PURL_RELATIONSHIP.acquaintanceOf,
            "subject is familiar with object, not friendship",
        )
        AMBIVALENT_OF = (
            PURL_RELATIONSHIP.ambivalentOf,
            "subject has mixed feelings or emotions for object",
        )
        ANCESTOR_OF = (PURL_RELATIONSHIP.ancestorOf, "subject is a descendant of object")
        ANTAGONIST_OF = (PURL_RELATIONSHIP.antagonistOf, "subject opposes or contends object")
        APPRENTICE_TO = (PURL_RELATIONSHIP.apprenticeTo, "object is a counselor for subject")
        CHILD_OF = (
            PURL_RELATIONSHIP.childOf,
            "subject was given birth to or nurtured and raised by object",
        )
        CLOSE_FRIEND_OF = (
            PURL_RELATIONSHIP.closeFriendOf,
            "subject and object share a close mutual friendship",
        )
        COLLABORATES_WITH = (
            PURL_RELATIONSHIP.collaboratesWith,
            "subject and object work towards a common goal",
        )
        COLLEAGUE_OF = (
            PURL_RELATIONSHIP.colleagueOf,
            "subject and object are members of the same profession",
        )
        DESCENDANT_OF = (
            PURL_RELATIONSHIP.descendantOf,
            "A person from whom this person is descended",
        )
        EMPLOYED_BY = (
            PURL_RELATIONSHIP.employedBy,
            "A person for whom this person's services have been engaged",
        )
        EMPLOYER_OF = (
            PURL_RELATIONSHIP.employerOf,
            "A person who engages the services of this person",
        )
        ENEMY_OF = (
            PURL_RELATIONSHIP.enemyOf,
            "A person towards whom this person feels hatred, or opposes the interests of",
        )
        ENGAGED_TO = (PURL_RELATIONSHIP.engagedTo, "A person to whom this person is betrothed")
        FRIEND_OF = (
            PURL_RELATIONSHIP.friendOf,
            "A person who shares mutual friendship with this person",
        )
        GRANDCHILD_OF = (
            PURL_RELATIONSHIP.grandchildOf,
            "A person who is a child of any of this person's children",
        )
        GRANDPARENT_OF = (
            PURL_RELATIONSHIP.grandparentOf,
            "A person who is the parent of any of this person's parents",
        )
        HAS_MET = (
            PURL_RELATIONSHIP.hasMet,
            "A person who has met this person whether in passing or longer",
        )
        INFLUENCED_BY = (PURL_RELATIONSHIP.influencedBy, "a person who has influenced this person")
        KNOWS_BY_REPUTATION = (
            PURL_RELATIONSHIP.knowsByReputation,
            "subject knows object for a particular action, position or field of endeavour",
        )
        KNOWS_IN_PASSING = (
            PURL_RELATIONSHIP.knowsInPassing,
            "A person whom this person has slight or superficial knowledge of",
        )
        KNOWS_OF = (
            PURL_RELATIONSHIP.knowsOf,
            "A person who has come to be known to this person through their actions or position",
        )
        LIFE_PARTNER_OF = (
            PURL_RELATIONSHIP.lifePartnerOf,
            "A person who has made a long-term commitment to this person's",
        )
        LIVES_WITH = (
            PURL_RELATIONSHIP.livesWith,
            "A person who shares a residence with this person",
        )
        LOST_CONTACT_WITH = (
            PURL_RELATIONSHIP.lostContactWith,
            "A person who was once known by this person but has subsequently become uncontactable",
        )
        MENTOR_OF = (
            PURL_RELATIONSHIP.mentorOf,
            "A person who serves as a trusted counselor or teacher to this person",
        )
        NEIGHBOR_OF = (
            PURL_RELATIONSHIP.neighborOf,
            "A person who lives in the same locality as this person",
        )
        PARENT_OF = (
            PURL_RELATIONSHIP.parentOf,
            "A person who has given birth to or nurtured and raised this person",
        )
        PARTICIPANT = (
            PURL_RELATIONSHIP.participant,
            "A person who has participates in the relationship",
        )
        PARTICIPANT_IN = (
            PURL_RELATIONSHIP.participantIn,
            "A person who is a participant in the relationship",
        )
        RELATIONSHIP = (
            PURL_RELATIONSHIP.Relationship,
            "subject has a particular type of connection or dealings with subject",
        )
        SIBLING_OF = (
            PURL_RELATIONSHIP.siblingOf,
            "A person having one or both parents in common with this person",
        )
        SPOUSE_OF = (PURL_RELATIONSHIP.spouseOf, "A person who is married to this person")
        WORKS_WITH = (
            PURL_RELATIONSHIP.worksWith,
            "A person who works for the same employer as this person",
        )
        WOULD_LIKE_TO_KNOW = (
            PURL_RELATIONSHIP.wouldLikeToKnow,
            "A person whom this person would desire to know more closely",
        )

    relationship = models.OneToOneField(
        ObjectContext, related_name="relationship_properties", on_delete=models.CASCADE
    )

    relationship_type = models.CharField(max_length=64, db_index=True, choices=Types.choices)
    subject = models.ForeignKey(
        Reference, related_name="subject_of_relationships", on_delete=models.CASCADE
    )
    relation = models.CharField(max_length=128)
    object = models.ForeignKey(
        Reference, related_name="object_of_relationships", on_delete=models.CASCADE
    )


class LinkRelation(models.Model):
    class Types(models.TextChoices):
        ALTERNATE = ("alternate", "Designates a substitute for the link's context")
        APPENDIX = ("appendix", "Refers to an appendix.")
        BOOKMARK = ("bookmark", "Refers to a bookmark or entry point.")
        CHAPTER = ("chapter", "Refers to a chapter in a collection of resources.")
        CONTENTS = ("contents", "Refers to a table of contents.")
        COPYRIGHT = ("copyright", "Copyright statement that applies to the link")
        CURRENT = ("current", "the most recent item(s) in a collection of resources")
        DESCRIBED_BY = ("describedby", "information about the link's context.")
        EDIT = ("edit", "used to edit the link's context")
        EDIT_MEDIA = ("edit-media", "can be used to edit media associated with the link")
        ENCLOSURE = ("enclosure", "Identifies a related resource that is potentially large")
        FIRST = ("first", "furthest preceding resource in a series of resources")
        GLOSSARY = ("glossary", "Refers to a glossary of terms.")
        HELP = ("help", "Refers to a resource offering help")
        HUB = ("hub", "Refers to a hub that enables registration for notification of updates")
        INDEX = ("index", "Refers to an index")
        LAST = ("last", "furthest following resource in a series")
        LATEST = ("latest-version", "latest version of the context")
        LICENSE = ("license", "Refers to a license associated with the link's context.")
        NEXT = ("next", "Refers to the next resource in a ordered series of resources.")
        NEXT_ARCHIVE = ("next-archive", "Refers to the immediately following archive resource.")
        PAYMENT = ("payment", "indicates a resource where payment is accepted.")
        PREV = ("prev", "Synonym for 'previous'")
        PREDECESSOR_VERSION = ("predecessor-version", "predecessor version in the version history")
        PREVIOUS = ("previous", "Previous resource in an ordered series of resources")
        PREV_ARCHIVE = ("prev-archive", "Refers to the immediately preceding archive resource")
        RELATED = ("related", "Identifies a related resource")
        REPLIES = ("replies", "Identifies a resource that is a reply to the context of the link")
        SECTION = ("section", "Refers to a section in a collection of resources")
        SELF = ("self", "Conveys an identifier for the link's context")
        SERVICE = ("service", "Indicates a URI that can be used to retrieve a service document")
        START = ("start", "Refers to the first resource in a collection of resources")
        STYLESHEET = ("stylesheet", "Refers to an external style sheet")
        SUBSECTION = ("subsection", "subsection in a collection of resources")
        SUCCESSOR_VERSION = ("successor-version", "successor version in the version history")
        UP = ("up", "Refers to a parent document in a hierarchy of documents")
        VERSION_HISTORY = ("version-history", "version history for the context")
        VIA = ("via", "source of the information in the link's context")
        WORKING_COPY = ("working-copy", "Points to a working copy for this resource")
        WORKING_COPY_OF = ("working-copy-of", "versioned resource originating this working copy")

    link = models.ForeignKey(LinkContext, related_name="related", on_delete=models.CASCADE)
    type = models.CharField(max_length=50, choices=Types.choices, default=Types.ALTERNATE)


class LinkedFile(models.Model):
    link = models.OneToOneField(LinkContext, on_delete=models.CASCADE)
    file = models.FileField(upload_to=_file_location)


__all__ = (
    "LinkContext",
    "BaseAs2ObjectContext",
    "ObjectContext",
    "ActorContext",
    "ActivityContext",
    "EndpointContext",
    "QuestionContext",
    "RelationshipProperties",
    "LinkRelation",
    "LinkedFile",
)
