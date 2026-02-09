import datetime
import uuid
from collections import OrderedDict

from box import Box
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Max, Q
from django.db.models.functions import Now
from django.utils import timezone
from markdown import markdown
from rest_framework import serializers

from activitypub.core.authentication_backends import ActorUsernameAuthenticationBackend
from activitypub.core.contexts import AS2
from activitypub.core.exceptions import InvalidDomainError
from activitypub.core.models import (
    ActivityContext,
    ActivityPubServer,
    ActorContext,
    CollectionContext,
    Domain,
    EndpointContext,
    Identity,
    LinkContext,
    ObjectContext,
    Reference,
    RelatedContextField,
    SecV1Context,
    SourceContentContext,
)

from . import models
from .choices import PostFeatureType, SearchType, SubscriptionStatus

User = get_user_model()


class IdentityField(serializers.IntegerField):
    pass


class LanguageField(serializers.RelatedField):
    queryset = models.Language.objects.all()

    def to_representation(self, instance):
        language = models.Language.objects.filter(reference=instance).first()
        return language and language.internal_id

    def to_internal_value(self, data):
        try:
            return models.Language.get_by_internal_id(internal_id=data)
        except models.Language.DoesNotExist:
            raise serializers.ValidationError(f"Could not find language with id {data}")


class RelatedLemmyObjectField(serializers.RelatedField):
    def to_representation(self, instance):
        return instance.object_id

    def to_internal_value(self, data):
        queryset = self.get_queryset()
        try:
            return queryset.get(object_id=data)
        except ObjectDoesNotExist:
            self.fail("required")


class LemmySerializer(serializers.Serializer):
    def get_domain(self):
        request = self.context.get("request")
        host = request.META.get("HTTP_HOST")
        scheme = Domain.SchemeTypes.HTTP if not request.is_secure() else Domain.SchemeTypes.HTTPS
        return Domain.objects.filter(scheme=scheme, name=host, local=True).first()

    def get_actor(self):
        try:
            request = self.context.get("request")
            if not request.user.is_authenticated:
                raise AssertionError
            identity = Identity.objects.select_related("actor").get(user=request.user)
            return identity.actor
        except (Identity.DoesNotExist, Identity.MultipleObjectsReturned, AssertionError):
            return None

    def get_person(self):
        actor = self.get_actor()
        return actor and models.Person.objects.filter(reference=actor.reference).first()

    def to_representation(self, instance):
        result = super().to_representation(instance)
        return OrderedDict([(key, result[key]) for key in result if result[key] is not None])


class LemmyModelSerializer(LemmySerializer, serializers.ModelSerializer):
    id = IdentityField(source="object_id", read_only=True)
    instance_id = IdentityField(source="site.object_id", read_only=True)

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)

        # Save all RelatedContextField proxies
        for field_name in dir(instance):
            field = getattr(type(instance), field_name, None)
            if isinstance(field, RelatedContextField):
                proxy = getattr(instance, field_name)
                if hasattr(proxy, "save"):
                    proxy.save()

        return instance


class SiteSerializer(LemmyModelSerializer):
    name = serializers.CharField(source="as2.name")
    icon = serializers.URLField(source="as2.icon.url", read_only=True)
    banner = serializers.URLField(source="as2.image.url", read_only=True)
    sidebar = serializers.CharField(read_only=True)
    description = serializers.CharField(source="as2.summary", read_only=True)
    actor_id = serializers.CharField(source="as2.uri")
    inbox_url = serializers.URLField()
    public_key = serializers.CharField(source="secv1.public_key_pem")
    published = serializers.DateTimeField(source="as2.published")
    updated = serializers.DateTimeField(source="as2.updated")
    last_refreshed_at = serializers.DateTimeField(
        source="reference.status_changed", read_only=True
    )
    content_warning = serializers.BooleanField(source="as2.sensitive", read_only=True)

    class Meta:
        model = models.Site
        fields = (
            "id",
            "name",
            "sidebar",
            "published",
            "updated",
            "icon",
            "banner",
            "description",
            "actor_id",
            "last_refreshed_at",
            "inbox_url",
            "public_key",
            "instance_id",
            "content_warning",
        )
        read_only_fields = (
            "published",
            "updated",
            "actor_id",
            "last_refreshed_at",
            "inbox_url",
            "public_key",
        )


class LocalSiteSerializer(serializers.ModelSerializer):
    site_setup = serializers.BooleanField(default=True, read_only=True)
    published = serializers.DateTimeField(source="site.as2.published", read_only=True)
    updated = serializers.DateTimeField(source="site.as2.updated", read_only=True)

    class Meta:
        model = models.LocalSite
        fields = (
            "id",
            "site_id",
            "site_setup",
            "enable_downvotes",
            "enable_nsfw",
            "community_creation_admin_only",
            "require_email_verification",
            "application_question",
            "private_instance",
            "default_theme",
            "default_post_listing_type",
            "legal_information",
            "hide_modlog_mod_names",
            "application_email_admins",
            "slur_filter_regex",
            "actor_name_max_length",
            "federation_enabled",
            "captcha_enabled",
            "captcha_difficulty",
            "published",
            "updated",
            "registration_mode",
            "reports_email_admins",
            "federation_signed_fetch",
            "default_post_listing_mode",
            "default_sort_type",
        )

        read_only_fields = ("updated", "published", "site_setup")


class LocalSiteRateLimitSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.LocalSiteRateLimit
        fields = (
            "local_site_id",
            "message",
            "message_per_second",
            "post",
            "post_per_second",
            "register",
            "register_per_second",
            "image",
            "image_per_second",
            "comment",
            "comment_per_second",
            "search",
            "search_per_second",
            "published",
            "updated",
            "import_user_settings",
            "import_user_settings_per_second",
        )

        read_only_fields = ("published", "updated")


class SiteAggregatesSerializer(serializers.Serializer):
    site_id = IdentityField(source="object_id", read_only=True)
    users = serializers.SerializerMethodField()
    posts = serializers.SerializerMethodField()
    comments = serializers.SerializerMethodField()
    communities = serializers.SerializerMethodField()
    users_active_day = serializers.SerializerMethodField()
    users_active_week = serializers.SerializerMethodField()
    users_active_month = serializers.SerializerMethodField()
    users_active_half_year = serializers.SerializerMethodField()

    def get_users(self, obj):
        return ActorContext.objects.filter(
            reference__domain=obj.reference.domain,
            type__in=[ActorContext.Types.PERSON, ActorContext.Types.SERVICE],
        ).count()

    def get_communities(self, obj):
        return ActorContext.objects.filter(
            reference__domain=obj.reference.domain,
            type=ActorContext.Types.GROUP,
        ).count()

    def get_posts(self, obj):
        try:
            return obj.reference.submission_count.posts
        except models.SubmissionCount.DoesNotExist:
            return 0

    def get_comments(self, obj):
        try:
            return obj.reference.submission_count.comments
        except models.SubmissionCount.DoesNotExist:
            return 0

    def _get_user_activity(self, obj):
        try:
            return obj.reference.user_activity_report
        except models.UserActivity.DoesNotExist:
            return None

    def get_users_active_day(self, obj):
        activity = self._get_user_activity(obj)
        return activity.active_day if activity else 0

    def get_users_active_week(self, obj):
        activity = self._get_user_activity(obj)
        return activity.active_week if activity else 0

    def get_users_active_month(self, obj):
        activity = self._get_user_activity(obj)
        return activity.active_month if activity else 0

    def get_users_active_half_year(self, obj):
        activity = self._get_user_activity(obj)
        return activity.active_half_year if activity else 0


class SiteViewSerializer(LemmyModelSerializer):
    site = SiteSerializer(source="*")
    local_site = LocalSiteSerializer(read_only=True)
    counts = SiteAggregatesSerializer(source="*", read_only=True)

    class Meta:
        model = models.Site
        fields = ("site", "local_site", "counts")


class PersonSerializer(LemmyModelSerializer):
    name = serializers.CharField(source="as2.preferred_username", read_only=True)
    display_name = serializers.CharField(source="as2.name", read_only=True)
    avatar = serializers.URLField(source="as2.icon.url", read_only=True)
    published = serializers.DateTimeField(source="as2.published", read_only=True)
    updated = serializers.DateTimeField(source="as2.updated", read_only=True)
    actor_id = serializers.CharField(source="reference.uri", read_only=True)
    bio = serializers.CharField(source="source.content", read_only=True)
    banner = serializers.URLField(source="as2.image.url", read_only=True)
    banned = serializers.SerializerMethodField()
    ban_expires = serializers.SerializerMethodField()
    local = serializers.BooleanField(source="reference.is_local", read_only=True)
    matrix_user_id = serializers.CharField(source="lemmy.matrix_user_id", read_only=True)

    def get_banned(self, obj):
        """Check if person is banned - defaults to checking site-wide ban"""
        site = obj.site
        if not site:
            return False

        permanent_ban = Q(end_time=None)
        not_expired = Q(end_time__gt=Now())

        banned = permanent_ban | not_expired

        site_bans = ActivityContext.objects.filter(object=obj.reference, target=site.reference)
        return site_bans.filter(banned).exists()

    def get_ban_expires(self, obj) -> datetime.datetime | None:
        """Get ban expiration if banned"""
        site = obj.site
        if not site:
            return None
        return (
            ActivityContext.objects.filter(object=obj.reference, target=site.reference)
            .aggregate(expires=Max("end_time"))
            .get("expires")
        )

    class Meta:
        model = models.Person
        fields = (
            "id",
            "name",
            "display_name",
            "avatar",
            "banned",
            "published",
            "updated",
            "actor_id",
            "bio",
            "local",
            "banner",
            "deleted",
            "matrix_user_id",
            "bot_account",
            "ban_expires",
            "instance_id",
        )


class PersonAggregatesSerializer(serializers.Serializer):
    person_id = IdentityField(source="object_id", read_only=True)
    post_count = serializers.SerializerMethodField()
    comment_count = serializers.SerializerMethodField()

    def get_post_count(self, obj):
        try:
            return obj.reference.submission_count.posts
        except models.SubmissionCount.DoesNotExist:
            return 0

    def get_comment_count(self, obj):
        try:
            return obj.reference.submission_count.comments
        except models.SubmissionCount.DoesNotExist:
            return 0


class AdminSerializer(serializers.ModelSerializer):
    person = PersonSerializer(source="*")
    counts = PersonAggregatesSerializer(source="*")
    is_admin = serializers.BooleanField(default=False, read_only=True)


class LanguageSerializer(serializers.ModelSerializer):
    id = IdentityField(source="internal_id")

    class Meta:
        model = models.Language
        fields = ("id", "code", "name")


class CustomEmojiSerializer(serializers.ModelSerializer):
    local_site_id = IdentityField(source="local_site.object_id", allow_null=True)

    class Meta:
        model = models.CustomEmoji
        fields = (
            "id",
            "local_site_id",
            "shortcode",
            "image_url",
            "alt_text",
            "category",
            "published",
            "updated",
        )


class LocalSiteBlockedUrlSerializer(serializers.ModelSerializer):
    published = serializers.DateTimeField(source="local_site.published", read_only=True)
    updated = serializers.DateTimeField(source="local_site.updated", read_only=True)

    class Meta:
        model = models.LocalSiteBlockedUrl
        fields = (
            "id",
            "url",
            "published",
            "updated",
        )


class TaglineSerializer(serializers.ModelSerializer):
    published = serializers.DateTimeField(source="created")
    updated = serializers.DateTimeField(source="modified")

    class Meta:
        model = models.Tagline
        fields = ("id", "local_site_id", "content", "published", "updated")


class CustomEmojiViewSerializer(serializers.ModelSerializer):
    custom_emoji = CustomEmojiSerializer(source="*")
    keywords = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = models.CustomEmoji
        fields = ("custom_emoji", "keywords")


class LocalSiteViewSerializer(LemmyModelSerializer):
    site_view = SiteViewSerializer(source="site")
    local_site = LocalSiteSerializer(source="*")
    local_site_rate_limit = LocalSiteRateLimitSerializer(source="rate_limits")
    admins = AdminSerializer(source="site.admins", many=True)
    version = serializers.CharField(source="site.instance.version")
    all_languages = LanguageSerializer(many=True, source="installed_languages")
    discussion_languages = LanguageSerializer(many=True)
    taglines = TaglineSerializer(many=True)
    custom_emojis = CustomEmojiViewSerializer(many=True)
    blocked_urls = LocalSiteBlockedUrlSerializer(many=True)

    def get_discussion_languages(self, obj):
        return [lang.internal_id for lang in obj.installed_languages.all()]

    class Meta:
        model = models.LocalSite
        fields = (
            "site_view",
            "local_site",
            "local_site_rate_limit",
            "admins",
            "version",
            "all_languages",
            "discussion_languages",
            "taglines",
            "custom_emojis",
            "blocked_urls",
        )


class UserRegistrationSerializer(LemmySerializer):
    username = serializers.CharField(write_only=True)
    password = serializers.CharField(write_only=True)
    password_verify = serializers.CharField(write_only=True)
    show_nsfw = serializers.BooleanField(required=False, allow_null=True, write_only=True)
    email = serializers.EmailField(required=False, allow_null=True, write_only=True)
    captcha_uuid = serializers.CharField(required=False, allow_null=True, write_only=True)
    captcha_answer = serializers.CharField(required=False, allow_null=True, write_only=True)
    honeypot = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, write_only=True
    )
    answer = serializers.CharField(required=False, allow_null=True, write_only=True)
    jwt = serializers.CharField(read_only=True)
    registration_created = serializers.BooleanField(read_only=True)
    verify_email_sent = serializers.BooleanField(read_only=True)

    def validate(self, data):
        if data["password"] != data["password_verify"]:
            raise serializers.ValidationError({"password": "Passwords do not match"})

        domain = self.get_domain()

        if domain is None:
            raise serializers.ValidationError({"error": "Site is not setup"})

        username = data["username"]

        if ActorContext.objects.filter(
            preferred_username=username, reference__domain=domain
        ).exists():
            raise serializers.ValidationError({"username": "Username is already taken"})

        return data

    @transaction.atomic()
    def create(self, validated_data):
        username = validated_data["username"]
        password = validated_data["password"]

        domain = self.get_domain()
        if not domain:
            raise serializers.ValidationError("No local domain configured")

        now = timezone.now()
        user_ref = models.LemmyContextModel.generate_reference(domain=domain)

        inbox_ref = CollectionContext.generate_reference(domain=domain)
        outbox_ref = CollectionContext.generate_reference(domain=domain)
        following_ref = CollectionContext.generate_reference(domain=domain)
        followers_ref = CollectionContext.generate_reference(domain=domain)

        actor = ActorContext.make(
            reference=user_ref,
            type=ActorContext.Types.PERSON,
            preferred_username=username,
            inbox=inbox_ref,
            outbox=outbox_ref,
            following=following_ref,
            followers=followers_ref,
            published=now,
            updated=now,
        )

        CollectionContext.make(reference=inbox_ref)
        CollectionContext.make(reference=outbox_ref)
        CollectionContext.make(reference=following_ref)
        CollectionContext.make(reference=followers_ref)
        internal_username = uuid.uuid4()
        user = User.objects.create_user(username=internal_username, password=password)
        identity = Identity.objects.create(user=user, actor=actor)
        models.Person.objects.create(reference=user_ref)
        SecV1Context.generate_keypair(owner_reference=user_ref)

        login_token = models.LoginToken.make(
            identity,
            ip=self.context["request"].META.get("REMOTE_ADDR"),
            user_agent=self.context["request"].META.get("HTTP_USER_AGENT"),
        )

        return {"jwt": login_token.token, "registration_created": True, "verify_email_sent": False}


class LoginSerializer(LemmySerializer):
    username_or_email = serializers.CharField()
    password = serializers.CharField(write_only=True)
    totp_2fa_token = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, write_only=True
    )
    jwt = serializers.CharField(read_only=True)
    registration_created = serializers.BooleanField(read_only=True)
    verify_email_sent = serializers.BooleanField(read_only=True)

    def validate(self, data):
        username_or_email = data["username_or_email"]
        password = data["password"]

        user = None
        domain = self.get_domain()

        backend = ActorUsernameAuthenticationBackend()
        user = backend.authenticate(username=username_or_email, password=password, domain=domain)

        if user is None:
            raise serializers.ValidationError("Invalid username/email or password")

        if not user.is_active:
            raise serializers.ValidationError("User account is disabled")

        try:
            identity = Identity.objects.select_related("actor").get(user=user)
        except Identity.DoesNotExist:
            raise serializers.ValidationError("User identity not found")

        login_token = models.LoginToken.make(
            identity=identity,
            ip=self.context["request"].META.get("REMOTE_ADDR"),
            user_agent=self.context["request"].META.get("HTTP_USER_AGENT"),
        )

        data["jwt"] = login_token.token
        data["registration_created"] = False
        data["verify_email_sent"] = False

        return data


class CommunitySerializer(LemmyModelSerializer):
    name = serializers.CharField(source="community_data.as2.preferred_username", read_only=True)
    title = serializers.CharField(source="community_data.as2.name", read_only=True)
    description = serializers.CharField(source="community_data.description", read_only=True)
    icon = serializers.URLField(source="community_data.as2.icon.url", read_only=True)
    banner = serializers.URLField(source="community_data.as2.image.url", read_only=True)
    actor_id = serializers.CharField(source="reference.uri", read_only=True)
    local = serializers.BooleanField(source="reference.is_local", read_only=True)
    published = serializers.DateTimeField(source="community_data.as2.published", read_only=True)
    updated = serializers.DateTimeField(source="community_data.as2.updated", read_only=True)
    nsfw = serializers.BooleanField(source="community_data.as2.sensitive")
    posting_restricted_to_mods = serializers.BooleanField(
        source="community_data.lemmy.posting_restricted_to_mods"
    )

    class Meta:
        model = models.Community
        fields = (
            "id",
            "name",
            "title",
            "description",
            "removed",
            "published",
            "updated",
            "deleted",
            "nsfw",
            "actor_id",
            "local",
            "icon",
            "banner",
            "hidden",
            "posting_restricted_to_mods",
            "instance_id",
            "visibility",
        )
        read_only_fields = fields


class CreateCommunitySerializer(LemmyModelSerializer):
    name = serializers.CharField(required=True)
    title = serializers.CharField(required=True)
    description = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    icon = serializers.URLField(required=False, allow_null=True)
    banner = serializers.URLField(required=False, allow_null=True)
    nsfw = serializers.BooleanField(required=False, default=False)
    posting_restricted_to_mods = serializers.BooleanField(required=False, default=False)
    visibility = serializers.ChoiceField(
        choices=models.Community.VisibilityTypes.choices,
        default=models.Community.VisibilityTypes.PUBLIC,
    )
    discussion_languages = serializers.ListField(child=IdentityField(), required=False)

    class Meta:
        model = models.Community
        fields = (
            "name",
            "title",
            "description",
            "icon",
            "banner",
            "nsfw",
            "posting_restricted_to_mods",
            "visibility",
            "discussion_languages",
        )

    def validate(self, data):
        domain = self.get_domain()
        if not domain:
            raise serializers.ValidationError("No local domain configured")

        if ActorContext.objects.filter(
            reference__domain=domain, preferred_username=data["name"]
        ).exists():
            raise serializers.ValidationError(f"{data['name']} is taken")

        data["domain"] = domain
        return data

    def create(self, validated_data):
        box = Box(validated_data, default_box=True, default_box_attr=None)
        domain = box.domain
        now = timezone.now()
        community_ref = ActorContext.generate_reference(domain=domain)
        instance, _ = ActivityPubServer.objects.get_or_create(domain=domain)

        inbox_ref = CollectionContext.generate_reference(domain=domain)
        outbox_ref = CollectionContext.generate_reference(domain=domain)
        following_ref = CollectionContext.generate_reference(domain=domain)
        followers_ref = CollectionContext.generate_reference(domain=domain)

        CollectionContext.make(reference=followers_ref, type=CollectionContext.Types.UNORDERED)
        CollectionContext.make(reference=following_ref, type=CollectionContext.Types.UNORDERED)
        CollectionContext.make(reference=inbox_ref, type=CollectionContext.Types.ORDERED)
        CollectionContext.make(reference=outbox_ref, type=CollectionContext.Types.ORDERED)

        # Create endpoints
        if instance.actor.inbox is not None:
            endpoint_ref = Reference.make(Reference.generate_skolem())
            EndpointContext.objects.create(
                reference=endpoint_ref,
                shared_inbox=instance.actor.inbox.uri,
            )
        else:
            endpoint_ref = None

        actor = ActorContext.make(
            reference=community_ref,
            type=ActorContext.Types.GROUP,
            preferred_username=box.name,
            name=box.title,
            sensitive=box.nsfw,
            published=now,
            updated=now,
            followers=followers_ref,
            following=following_ref,
            inbox=inbox_ref,
            outbox=outbox_ref,
            endpoints=endpoint_ref,
        )
        # Attach optional media
        if box.icon:
            icon_ref = Reference.make(uri=box.icon)
            actor.icon.add(icon_ref)
        if box.banner:
            banner_ref = Reference.make(uri=box.banner)
            actor.image.add(banner_ref)

        # Generate key
        SecV1Context.generate_keypair(owner_reference=community_ref)

        # Create the community record
        community = models.Community.objects.create(
            reference=community_ref, visibility=box.visibility
        )
        # Lemmy specific fields
        moderators_ref = CollectionContext.generate_reference(domain=domain)
        featured_ref = CollectionContext.generate_reference(domain=domain)

        CollectionContext.make(reference=featured_ref, type=CollectionContext.Types.UNORDERED)
        CollectionContext.make(reference=moderators_ref, type=CollectionContext.Types.UNORDERED)

        lemmy_ctx = models.LemmyContextModel.make(
            reference=community_ref,
            posting_restricted_to_mods=box.posting_restricted_to_mods,
            featured=featured_ref,
            moderators=moderators_ref,
        )

        # Discussion languages handling
        if box.discussion_languages:
            for lang_id in box.discussion_languages:
                try:
                    language = models.Language.get_by_internal_id(internal_id=lang_id)
                    lemmy_ctx.language.add(language.reference)
                except Exception:
                    continue
        return community


class CommunityAggregatesSerializer(serializers.Serializer):
    community_id = IdentityField(source="object_id", read_only=True)
    subscribers = serializers.SerializerMethodField()
    subscribers_local = serializers.SerializerMethodField()
    posts = serializers.SerializerMethodField()
    comments = serializers.SerializerMethodField()
    published = serializers.DateTimeField(source="as2.published", read_only=True)
    users_active_day = serializers.SerializerMethodField()
    users_active_week = serializers.SerializerMethodField()
    users_active_month = serializers.SerializerMethodField()
    users_active_half_year = serializers.SerializerMethodField()
    hot_rank = serializers.SerializerMethodField()

    def _get_follower_count(self, obj):
        try:
            return obj.reference.follower_count
        except models.FollowerCount.DoesNotExist:
            return None

    def get_subscribers(self, obj):
        follower_count = self._get_follower_count(obj)
        return follower_count.total if follower_count else 0

    def get_subscribers_local(self, obj):
        follower_count = self._get_follower_count(obj)
        return follower_count.local if follower_count else 0

    def get_posts(self, obj):
        try:
            return obj.reference.submission_count.posts
        except models.SubmissionCount.DoesNotExist:
            return 0

    def get_comments(self, obj):
        try:
            return obj.reference.submission_count.comments
        except models.SubmissionCount.DoesNotExist:
            return 0

    def _get_user_activity(self, obj):
        try:
            return obj.reference.user_activity_report
        except models.UserActivity.DoesNotExist:
            return None

    def get_users_active_day(self, obj):
        activity = self._get_user_activity(obj)
        return activity.active_day if activity else 0

    def get_users_active_week(self, obj):
        activity = self._get_user_activity(obj)
        return activity.active_week if activity else 0

    def get_users_active_month(self, obj):
        activity = self._get_user_activity(obj)
        return activity.active_month if activity else 0

    def get_users_active_half_year(self, obj):
        activity = self._get_user_activity(obj)
        return activity.active_half_year if activity else 0

    def get_hot_rank(self, obj):
        ranking = obj.reference.rankings.filter(
            type=models.RankingScore.Types.HOT
        ).first()
        return ranking.score if ranking else 0.0


class CommunityViewSerializer(serializers.Serializer):
    """
    Combined view of community with aggregates and user context
    """

    community = CommunitySerializer(source="*")
    counts = CommunityAggregatesSerializer(source="*", read_only=True)
    subscribed = serializers.SerializerMethodField()
    blocked = serializers.BooleanField(default=False, read_only=True)

    def get_subscribed(self, obj):
        view = self.context.get("view")

        person = view.get_person()

        if person is None:
            return SubscriptionStatus.UNSUBSCRIBED

        return (
            SubscriptionStatus.SUBSCRIBED
            if person.is_subscribed(obj)
            else SubscriptionStatus.UNSUBSCRIBED
        )


class PersonViewSerializer(serializers.ModelSerializer):
    """
    Combined view of person with aggregates
    """

    person = PersonSerializer(source="*")
    counts = PersonAggregatesSerializer(source="*", read_only=True)
    is_admin = serializers.BooleanField(read_only=True)

    class Meta:
        model = models.Person
        fields = ("person", "counts", "is_admin")


class PostSerializer(LemmyModelSerializer):
    name = serializers.CharField(source="as2.name")
    url = serializers.URLField(source="post_data.url")
    locked = serializers.BooleanField(source="post_data.lemmy.locked")
    nsfw = serializers.BooleanField(source="as2.sensitive")

    body = serializers.CharField(source="post_data.content")
    creator_id = IdentityField(source="creator.object_id", read_only=True)
    community_id = RelatedLemmyObjectField(
        source="post_data.community", queryset=models.Community.objects.all()
    )
    published = serializers.DateTimeField(source="as2.published", read_only=True)
    updated = serializers.DateTimeField(source="as2.updated", read_only=True)

    embed_title = serializers.CharField(source="as2.name", read_only=True)
    embed_description = serializers.CharField(source="attachment.summary", read_only=True)
    thumbnail_url = serializers.URLField(source="thumbnail.url", read_only=True)

    ap_id = serializers.CharField(source="reference_id", read_only=True)
    local = serializers.BooleanField(source="reference.is_local", read_only=True)
    language_id = LanguageField(source="language")

    class Meta:
        model = models.Post
        fields = (
            "id",
            "name",
            "url",
            "body",
            "creator_id",
            "community_id",
            "removed",
            "locked",
            "published",
            "updated",
            "deleted",
            "nsfw",
            "embed_title",
            "embed_description",
            "thumbnail_url",
            "ap_id",
            "local",
            "language_id",
            "featured_community",
            "featured_local",
        )
        read_only_fields = fields


class PostAggregatesSerializer(serializers.Serializer):
    post_id = IdentityField(source="object_id", read_only=True)
    comments = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()
    upvotes = serializers.SerializerMethodField()
    downvotes = serializers.SerializerMethodField()
    published = serializers.DateTimeField(source="as2.published", read_only=True)
    newest_comment_time = serializers.SerializerMethodField()
    featured_community = serializers.BooleanField(read_only=True)
    featured_local = serializers.BooleanField(read_only=True)
    hot_rank = serializers.SerializerMethodField()
    hot_rank_active = serializers.SerializerMethodField()
    controversy_rank = serializers.SerializerMethodField()
    scaled_rank = serializers.SerializerMethodField()

    def _get_reaction_count(self, obj):
        try:
            return obj.reference.reaction_count
        except models.ReactionCount.DoesNotExist:
            return None

    def get_score(self, obj):
        reaction = self._get_reaction_count(obj)
        return reaction.score if reaction else 0

    def get_upvotes(self, obj):
        reaction = self._get_reaction_count(obj)
        return reaction.upvotes if reaction else 0

    def get_downvotes(self, obj):
        reaction = self._get_reaction_count(obj)
        return reaction.downvotes if reaction else 0

    def get_comments(self, obj):
        try:
            return obj.reference.reply_count.replies
        except models.ReplyCount.DoesNotExist:
            return 0

    def get_newest_comment_time(self, obj):
        try:
            return obj.reference.reply_count.latest_reply
        except models.ReplyCount.DoesNotExist:
            return None

    def _get_ranking(self, obj, ranking_type):
        ranking = obj.reference.rankings.filter(type=ranking_type).first()
        return ranking.score if ranking else 0.0

    def get_hot_rank(self, obj):
        return self._get_ranking(obj, models.RankingScore.Types.HOT)

    def get_hot_rank_active(self, obj):
        return self._get_ranking(obj, models.RankingScore.Types.ACTIVE)

    def get_controversy_rank(self, obj):
        return self._get_ranking(obj, models.RankingScore.Types.CONTROVERSY)

    def get_scaled_rank(self, obj):
        return self._get_ranking(obj, models.RankingScore.Types.SCALED)


class PostViewSerializer(serializers.Serializer):
    """
    Combined view of post with creator, community, and aggregates
    """

    post = PostSerializer(source="*")
    creator = PersonSerializer(read_only=True)
    community = CommunitySerializer(read_only=True)
    counts = PostAggregatesSerializer(source="*", read_only=True)
    subscribed = serializers.CharField(default="NotSubscribed", read_only=True)
    saved = serializers.BooleanField(default=False, read_only=True)
    read = serializers.BooleanField(default=False, read_only=True)
    creator_banned_from_community = serializers.BooleanField(default=False, read_only=True)
    my_vote = serializers.IntegerField(allow_null=True, default=None, read_only=True)
    unread_comments = serializers.IntegerField(default=0, read_only=True)


class CommentSerializer(LemmyModelSerializer):
    """
    Direct representation of Comment model, integrating with
    information from as2 and lemmy contexts
    """

    creator_id = IdentityField(source="creator.object_id", read_only=True)
    post_id = RelatedLemmyObjectField(source="post", queryset=models.Post.objects.all())
    language_id = LanguageField(source="language")

    # Context fields - these read/write to ObjectContext
    content = serializers.CharField(read_only=True)
    published = serializers.DateTimeField(source="as2.published", read_only=True)
    updated = serializers.DateTimeField(source="as2.updated", read_only=True)

    # Regular reference and property fields
    ap_id = serializers.CharField(source="reference.uri", read_only=True)
    local = serializers.BooleanField(source="reference.is_local", read_only=True)
    path = serializers.SerializerMethodField()
    distinguished = serializers.BooleanField(
        source="comment_data.lemmy.distinguished", read_only=True
    )

    def get_path(self, obj):
        """Build comment path by traversing parent chain.

        Format: 0.ancestor_id...parent_id.comment_id
        The path represents the tree structure for comment threading.
        """
        path_parts = [str(obj.object_id)]
        current = obj

        # Traverse up the parent chain via in_reply_to
        while current.as2:
            parent_ref = current.as2.in_reply_to.first()
            if not parent_ref:
                break
            parent = models.Comment.objects.filter(reference=parent_ref).first()
            if not parent:
                break
            path_parts.insert(0, str(parent.object_id))
            current = parent

        # Prepend "0" as root marker
        return "0." + ".".join(path_parts)

    class Meta:
        model = models.Comment
        fields = (
            "id",
            "creator_id",
            "post_id",
            "content",
            "removed",
            "published",
            "updated",
            "deleted",
            "ap_id",
            "local",
            "path",
            "distinguished",
            "language_id",
        )
        read_only_fields = fields


class CommentAggregatesSerializer(serializers.Serializer):
    comment_id = IdentityField(source="object_id", read_only=True)
    score = serializers.SerializerMethodField()
    upvotes = serializers.SerializerMethodField()
    downvotes = serializers.SerializerMethodField()
    published = serializers.DateTimeField(source="as2.published", read_only=True)
    child_count = serializers.SerializerMethodField()
    hot_rank = serializers.SerializerMethodField()
    controversy_rank = serializers.SerializerMethodField()

    def _get_reaction_count(self, obj):
        try:
            return obj.reference.reaction_count
        except models.ReactionCount.DoesNotExist:
            return None

    def get_score(self, obj):
        reaction = self._get_reaction_count(obj)
        return reaction.score if reaction else 0

    def get_upvotes(self, obj):
        reaction = self._get_reaction_count(obj)
        return reaction.upvotes if reaction else 0

    def get_downvotes(self, obj):
        reaction = self._get_reaction_count(obj)
        return reaction.downvotes if reaction else 0

    def get_child_count(self, obj):
        try:
            return obj.reference.reply_count.replies
        except models.ReplyCount.DoesNotExist:
            return 0

    def _get_ranking(self, obj, ranking_type):
        ranking = obj.reference.rankings.filter(type=ranking_type).first()
        return ranking.score if ranking else 0.0

    def get_hot_rank(self, obj):
        return self._get_ranking(obj, models.RankingScore.Types.HOT)

    def get_controversy_rank(self, obj):
        return self._get_ranking(obj, models.RankingScore.Types.CONTROVERSY)


class CommentViewSerializer(serializers.Serializer):
    """
    Combined view of comment with creator, post, community, and aggregates
    """

    comment = CommentSerializer(source="*")
    creator = PersonSerializer(read_only=True)
    post = PostSerializer(read_only=True)
    community = CommunitySerializer(source="post.post_data.community", read_only=True)
    counts = CommentAggregatesSerializer(source="*", read_only=True)
    subscribed = serializers.CharField(default="NotSubscribed", read_only=True)
    saved = serializers.BooleanField(default=False, read_only=True)
    creator_banned_from_community = serializers.BooleanField(default=False, read_only=True)
    my_vote = serializers.IntegerField(allow_null=True, default=None, read_only=True)


class ResolveObjectSerializer(serializers.Serializer):
    q = serializers.CharField(write_only=True)
    person = PersonViewSerializer(allow_null=False, required=False, read_only=True)
    community = CommunityViewSerializer(allow_null=False, required=False, read_only=True)
    post = PostViewSerializer(allow_null=False, required=False, read_only=True)
    comment = CommentViewSerializer(allow_null=False, required=False, read_only=True)

    def validate(self, data):
        query = data.get("q", "").strip()

        if not query:
            raise serializers.ValidationError({"q": "Query parameter is required"})

        # Check if it's a subject_name (@user@domain or !community@domain)
        is_subject_name = query.startswith("@") or query.startswith("!")

        if not is_subject_name:
            # It's a URL - look up Reference
            try:
                reference = Reference.make(uri=query)
            except InvalidDomainError:
                raise serializers.ValidationError("Can not resolve reference: invalid domain")

        else:
            # Subject name - look up via Actor model
            username, domain_name = query.rsplit("@", 1)
            username = username[1:]
            actor = ActorContext.objects.filter(
                preferred_username=username, reference__domain__name=domain_name
            ).first()
            reference = actor and actor.reference

            if reference is None:
                raise serializers.ValidationError("Can not find reference")

        reference_q = Q(reference=reference)

        lookups = {
            "post": models.Post.objects.filter(reference_q),
            "comment": models.Comment.objects.filter(reference_q),
            "person": models.Person.objects.filter(reference_q),
            "community": models.Community.objects.filter(reference_q),
        }

        for key, qs in lookups.items():
            obj = qs.first()
            if obj is not None:
                data[key] = obj
                return data

        raise serializers.ValidationError("Could not resolve object")


class CreatePostSerializer(LemmyModelSerializer):
    name = serializers.CharField(source="as2.name", required=True)
    community_id = RelatedLemmyObjectField(
        source="community", queryset=models.Community.objects.all()
    )
    url = serializers.URLField(source="post_data.url", required=False, allow_null=True)

    body = serializers.CharField(source="as2.source.content", required=False)
    nsfw = serializers.BooleanField(source="as2.sensitive", required=False, default=False)
    language_id = LanguageField(source="language", required=False, allow_null=True)
    honeypot = serializers.CharField(
        required=False, write_only=True, allow_null=True, allow_blank=True
    )
    alt_text = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    custom_thumbnail = serializers.URLField(required=False, allow_null=True, allow_blank=True)

    class Meta:
        model = models.Post
        fields = (
            "name",
            "community_id",
            "url",
            "body",
            "nsfw",
            "language_id",
            "honeypot",
            "alt_text",
            "custom_thumbnail",
        )

    def validate_honeypot(self, value):
        """Honeypot should be empty - if filled, it's likely spam"""
        if bool(value):
            raise serializers.ValidationError("Invalid request")
        return value

    def validate(self, data):
        domain = self.get_domain()
        if not domain:
            raise serializers.ValidationError("No local domain configured")

        actor = self.get_actor()
        if not actor:
            raise serializers.ValidationError("No actor identified for this user")

        data.update({"domain": domain, "creator": actor})

        return data

    def create(self, validated_data):
        """Create a new post with ActivityPub integration"""

        box = Box(validated_data, default_box=True, default_box_attr=None)

        community = box.community
        now = timezone.now()
        post_ref = models.LemmyContextModel.generate_reference(domain=box.domain)

        post_url = box.post_data and box.post_data.url

        obj_context = ObjectContext.make(
            reference=post_ref,
            type=ObjectContext.Types.PAGE,
            name=box.as2.name,
            published=now,
            updated=now,
            url=post_url,
            sensitive=box.as2.sensitive,
        )

        obj_context.to.add(box.community.reference)
        obj_context.to.add(Reference.make(uri=str(AS2.Public)))
        obj_context.attributed_to.add(box.creator.reference)

        if post_url is not None:
            link_reference = Reference.make(Reference.generate_skolem())
            LinkContext.objects.create(reference=link_reference, href=post_url)
            obj_context.attachments.add(link_reference)

        body = box.as2 and box.as2.source and box.as2.source.content

        if body:
            source_ref = Reference.objects.create(
                uri=str(Reference.generate_skolem()), domain=box.domain
            )
            SourceContentContext.make(
                reference=source_ref,
                content=body,
                media_type="text/markdown",
            )
            obj_context.source.add(source_ref)
            obj_context.content = markdown(body)
            obj_context.media_type = "text/html"

        lemmy_ctx = models.LemmyContextModel.make(reference=post_ref)

        if box.language:
            lemmy_ctx.language.add(box.language.reference)

        return models.Post.objects.create(reference=post_ref, community=community)


class CreateCommentSerializer(LemmySerializer):
    """
    Serializer for creating a new comment.

    Required fields:
    - content: The comment content
    - post_id: ID of the post to comment on

    Optional fields:
    - parent_id: ID of parent comment (for replies)
    - language_id: Language of the comment
    """

    content = serializers.CharField(required=True)
    post_id = RelatedLemmyObjectField(source="post", queryset=models.Post.objects.all())
    parent_id = RelatedLemmyObjectField(
        source="parent", queryset=models.Comment.objects.all(), required=False
    )
    language_id = LanguageField(source="language", required=False)

    def validate(self, data):
        domain = self.get_domain()

        if not domain:
            raise serializers.ValidationError("No local domain configured")

        actor = self.get_actor()
        if not actor:
            raise serializers.ValidationError("No actor defined for authenticated user")

        data.update({"domain": domain, "creator": actor})
        return data

    def create(self, validated_data):
        box = Box(validated_data, default_box=True, default_box_attr=None)

        now = timezone.now()
        comment_ref = models.LemmyContextModel.generate_reference(domain=box.domain)
        comment_note = ObjectContext.make(
            reference=comment_ref, type=ObjectContext.Types.NOTE, published=now, updated=now
        )
        comment_note.attributed_to.add(box.creator.reference)

        source_ref = Reference.objects.create(uri=Reference.generate_skolem(), domain=box.domain)
        SourceContentContext.make(
            reference=source_ref, content=box.content, media_type="text/markdown"
        )

        comment_note.source.add(source_ref)
        lemmy_ctx = models.LemmyContextModel.make(reference=comment_ref)

        if box.language is not None:
            lemmy_ctx.language.add(box.language.reference)

        return models.Comment.objects.create(reference=comment_ref, post=box.post)


class PostResponseSerializer(serializers.Serializer):
    """Response serializer for post creation"""

    post_view = PostViewSerializer(read_only=True)


class CommentResponseSerializer(serializers.Serializer):
    """Response serializer for comment creation"""

    comment_view = CommentViewSerializer(read_only=True)
    recipient_ids = serializers.ListField(child=IdentityField(), default=list)


class DeleteCommentSerializer(serializers.Serializer):
    comment_id = RelatedLemmyObjectField(source="comment", queryset=models.Comment.objects.all())
    deleted = serializers.BooleanField()


class RemoveCommentSerializer(serializers.Serializer):
    comment_id = RelatedLemmyObjectField(source="comment", queryset=models.Comment.objects.all())
    removed = serializers.BooleanField()
    reason = serializers.CharField(required=False, allow_blank=True)


class CommentLikeSerializer(serializers.Serializer):
    comment_id = RelatedLemmyObjectField(source="comment", queryset=models.Comment.objects.all())
    score = serializers.IntegerField(min_value=-1, max_value=1)


class SaveCommentSerializer(serializers.Serializer):
    comment_id = RelatedLemmyObjectField(source="comment", queryset=models.Comment.objects.all())
    save = serializers.BooleanField()


class ListCommentsSerializer(serializers.Serializer):
    type_ = serializers.CharField(required=False, allow_null=True)
    sort = serializers.CharField(required=False, allow_null=True)
    max_depth = serializers.IntegerField(required=False, allow_null=True)
    page = serializers.IntegerField(required=False, default=1)
    limit = serializers.IntegerField(required=False, default=10)
    community_id = IdentityField(required=False, allow_null=True)
    post_id = IdentityField(required=False, allow_null=True)
    parent_id = IdentityField(required=False, allow_null=True)
    saved_only = serializers.BooleanField(required=False, default=False)


class ListCommentsResponseSerializer(serializers.Serializer):
    comments = CommentViewSerializer(many=True, read_only=True)


class PostLikeSerializer(serializers.Serializer):
    """Serializer for liking/voting on a post"""

    post_id = RelatedLemmyObjectField(source="post", queryset=models.Post.objects.all())
    score = serializers.IntegerField(min_value=-1, max_value=1)


class SavePostSerializer(serializers.Serializer):
    """Serializer for saving/unsaving a post"""

    post_id = RelatedLemmyObjectField(source="post", queryset=models.Post.objects.all())
    save = serializers.BooleanField()


class DeletePostSerializer(serializers.Serializer):
    """Serializer for deleting a post"""

    post_id = RelatedLemmyObjectField(source="post", queryset=models.Post.objects.all())
    deleted = serializers.BooleanField()


class LockPostSerializer(serializers.Serializer):
    """Serializer for locking/unlocking a post"""

    post_id = RelatedLemmyObjectField(source="post", queryset=models.Post.objects.all())
    locked = serializers.BooleanField()


class FeaturePostSerializer(serializers.Serializer):
    """Serializer for featuring a post"""

    post_id = RelatedLemmyObjectField(source="post", queryset=models.Post.objects.all())
    featured = serializers.BooleanField()
    feature_type = serializers.ChoiceField(choices=PostFeatureType.choices)


class MarkPostAsReadSerializer(serializers.Serializer):
    """Serializer for marking posts as read"""

    post_ids = serializers.ListField(child=IdentityField())
    read = serializers.BooleanField()


class RemovePostSerializer(serializers.Serializer):
    """Serializer for moderator post removal"""

    post_id = RelatedLemmyObjectField(source="post", queryset=models.Post.objects.all())
    removed = serializers.BooleanField()
    reason = serializers.CharField(required=False, allow_blank=True)


class HidePostSerializer(serializers.Serializer):
    """Serializer for hiding posts"""

    post_ids = serializers.ListField(child=IdentityField())
    hide = serializers.BooleanField()


class GetPostsResponseSerializer(LemmySerializer):
    """Response serializer for post list"""

    posts = PostViewSerializer(many=True, read_only=True)
    next_page = serializers.CharField(required=False, allow_null=True)


# Report serializers
class CreatePostReportSerializer(serializers.Serializer):
    post_id = IdentityField()
    reason = serializers.CharField()


class ResolvePostReportSerializer(serializers.Serializer):
    report_id = IdentityField()
    resolved = serializers.BooleanField()


class ListPostReportsSerializer(serializers.Serializer):
    page = serializers.IntegerField(required=False, default=1)
    limit = serializers.IntegerField(required=False, default=10)
    unresolved_only = serializers.BooleanField(required=False, default=False)
    community_id = IdentityField(required=False)
    post_id = IdentityField(required=False)


class PostReportSerializer(serializers.Serializer):
    id = IdentityField()
    creator_id = IdentityField()
    post_id = IdentityField()
    original_post_name = serializers.CharField()
    original_post_url = serializers.CharField()
    original_post_body = serializers.CharField()
    reason = serializers.CharField()
    resolved = serializers.BooleanField()
    resolver_id = IdentityField(allow_null=True)
    published = serializers.DateTimeField()
    updated = serializers.DateTimeField(allow_null=True)

    def to_representation(self, instance):
        # Get reporter from actor

        flag_activity = instance.reference.get_by_context(ActivityContext)
        reporter_ref = flag_activity.actor
        reporter = models.Person.objects.filter(reference=reporter_ref).first()

        # Get reported post from object
        post_ref = flag_activity.object
        post = models.Post.objects.filter(reference=post_ref).first()

        # Get resolver if any
        resolver = (
            instance.resolved_by
            and models.Person.objects.filter(reference=instance.resolved_by).first()
        )

        return {
            "id": instance.object_id,
            "creator_id": reporter.object_id if reporter else None,
            "post_id": post.object_id if post else None,
            "original_post_name": post.as2.name if post and post.as2 else "",
            "original_post_url": getattr(post.as2.url, "href", None)
            if post and post.as2 and post.as2.url
            else None,
            "original_post_body": post.content or "",
            "reason": flag_activity.content or "",
            "resolved": instance.resolved_by is not None,
            "resolver_id": resolver.object_id if resolver else None,
            "published": flag_activity.published.isoformat() if flag_activity.published else None,
            "updated": None,  # Reports don't have updates in our model
        }


class PostReportViewSerializer(serializers.Serializer):
    post_report = PostReportSerializer()
    post = PostSerializer()
    community = CommunitySerializer()
    creator = PersonSerializer()  # Reporter
    post_creator = PersonSerializer()  # Post author
    creator_banned_from_community = serializers.BooleanField()
    creator_is_moderator = serializers.BooleanField()
    creator_is_admin = serializers.BooleanField()
    subscribed = serializers.BooleanField()
    saved = serializers.BooleanField()
    read = serializers.BooleanField()
    hidden = serializers.BooleanField()
    creator_blocked = serializers.BooleanField()
    my_vote = serializers.IntegerField(allow_null=True)
    unread_comments = serializers.IntegerField()
    counts = PostAggregatesSerializer()
    resolver = PersonSerializer(required=False, allow_null=True)


class PostReportResponseSerializer(serializers.Serializer):
    post_report_view = PostReportViewSerializer()


class ListPostReportsResponseSerializer(serializers.Serializer):
    post_reports = serializers.ListField(child=PostReportViewSerializer())


# Comment report serializers
class CreateCommentReportSerializer(serializers.Serializer):
    comment_id = IdentityField()
    reason = serializers.CharField()


class ResolveCommentReportSerializer(serializers.Serializer):
    report_id = IdentityField()
    resolved = serializers.BooleanField()


class ListCommentReportsSerializer(serializers.Serializer):
    page = serializers.IntegerField(required=False, default=1)
    limit = serializers.IntegerField(required=False, default=10)
    unresolved_only = serializers.BooleanField(required=False, default=False)
    community_id = IdentityField(required=False)
    post_id = IdentityField(required=False)
    comment_id = IdentityField(required=False)


class CommentReportSerializer(serializers.Serializer):
    id = IdentityField()
    creator_id = IdentityField()
    comment_id = IdentityField()
    original_comment_text = serializers.CharField()
    reason = serializers.CharField()
    resolved = serializers.BooleanField()
    resolver_id = IdentityField(allow_null=True)
    published = serializers.DateTimeField()
    updated = serializers.DateTimeField(allow_null=True)

    def to_representation(self, instance):
        flag_activity = instance.reference.get_by_context(ActivityContext)

        reporter_ref = flag_activity.actor
        reporter = models.Person.objects.filter(reference=reporter_ref).first()

        comment_ref = flag_activity.object
        comment = models.Comment.objects.filter(reference=comment_ref).first()

        resolver = (
            instance.resolved_by
            and models.Person.objects.filter(reference=instance.resolved_by).first()
        )

        return {
            "id": instance.object_id,
            "creator_id": reporter.object_id if reporter else None,
            "comment_id": comment.object_id if comment else None,
            "original_comment_text": comment.content or "" if comment else "",
            "reason": flag_activity.content or "",
            "resolved": instance.resolved,
            "resolver_id": resolver.object_id if resolver else None,
            "published": flag_activity.published.isoformat() if flag_activity.published else None,
            "updated": None,
        }


class CommentReportViewSerializer(serializers.Serializer):
    comment_report = CommentReportSerializer()
    comment = CommentSerializer()
    post = PostSerializer()
    community = CommunitySerializer()
    creator = PersonSerializer()
    comment_creator = PersonSerializer()
    counts = CommentAggregatesSerializer()
    creator_banned_from_community = serializers.BooleanField()
    creator_is_moderator = serializers.BooleanField()
    creator_is_admin = serializers.BooleanField()
    creator_blocked = serializers.BooleanField()
    subscribed = serializers.CharField()
    saved = serializers.BooleanField()
    my_vote = serializers.IntegerField(allow_null=True)
    resolver = PersonSerializer(required=False, allow_null=True)


class CommentReportResponseSerializer(serializers.Serializer):
    comment_report_view = CommentReportViewSerializer()


class ListCommentReportsResponseSerializer(serializers.Serializer):
    comment_reports = serializers.ListField(child=CommentReportViewSerializer())


# Comment action serializers
class MarkCommentAsReadSerializer(serializers.Serializer):
    comment_reply_id = IdentityField()
    read = serializers.BooleanField()


class CommentReplyResponseSerializer(serializers.Serializer):
    comment_reply_view = CommentViewSerializer()


class DistinguishCommentSerializer(serializers.Serializer):
    comment_id = RelatedLemmyObjectField(source="comment", queryset=models.Comment.objects.all())
    distinguished = serializers.BooleanField()


class ListCommentLikesSerializer(serializers.Serializer):
    comment_id = IdentityField()
    page = serializers.IntegerField(required=False, default=1)
    limit = serializers.IntegerField(required=False, default=10)


class PurgeCommentSerializer(serializers.Serializer):
    comment_id = RelatedLemmyObjectField(source="comment", queryset=models.Comment.objects.all())
    reason = serializers.CharField(required=False, allow_blank=True)


# Site metadata serializers
class GetSiteMetadataSerializer(serializers.Serializer):
    url = serializers.URLField()


class LinkMetadataSerializer(serializers.Serializer):
    title = serializers.CharField(allow_null=True, required=False)
    description = serializers.CharField(allow_null=True, required=False)
    image = serializers.URLField(allow_null=True, required=False)
    embed_video_url = serializers.URLField(allow_null=True, required=False)


class GetSiteMetadataResponseSerializer(serializers.Serializer):
    metadata = LinkMetadataSerializer()


# Like list serializers
class ListPostLikesSerializer(serializers.Serializer):
    post_id = IdentityField()
    page = serializers.IntegerField(required=False, default=1)
    limit = serializers.IntegerField(required=False, default=10)


class VoteViewSerializer(serializers.Serializer):
    creator = PersonSerializer()
    score = serializers.IntegerField()


class ListPostLikesResponseSerializer(serializers.Serializer):
    post_likes = serializers.ListField(child=VoteViewSerializer())


class ListCommentLikesResponseSerializer(serializers.Serializer):
    comment_likes = serializers.ListField(child=VoteViewSerializer())


class GetCommunitySerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False, allow_null=True)
    name = serializers.CharField(required=False, allow_null=True)

    def validate(self, data):
        if not data.get("id") and not data.get("name"):
            raise serializers.ValidationError("Either id or name must be provided")
        return data


class GetCommunityResponseSerializer(serializers.Serializer):
    community_view = CommunityViewSerializer(source="*")
    site = SiteSerializer(required=False, allow_null=True)
    moderators = serializers.ListField(child=PersonViewSerializer(), default=list)
    discussion_languages = LanguageSerializer(many=True, default=list)


class ListCommunitiesSerializer(serializers.Serializer):
    type_ = serializers.CharField(required=False, allow_null=True)
    sort = serializers.CharField(required=False, allow_null=True)
    show_nsfw = serializers.BooleanField(required=False, default=True)
    page = serializers.IntegerField(required=False, default=1)
    limit = serializers.IntegerField(required=False, default=10)


class ListCommunitiesResponseSerializer(serializers.Serializer):
    communities = CommunityViewSerializer(many=True)


class FollowCommunitySerializer(serializers.Serializer):
    community_id = RelatedLemmyObjectField(
        source="community", queryset=models.Community.objects.all()
    )
    follow = serializers.BooleanField()


class BlockCommunitySerializer(serializers.Serializer):
    community_id = RelatedLemmyObjectField(
        source="community", queryset=models.Community.objects.all()
    )
    block = serializers.BooleanField()


class BlockCommunityResponseSerializer(serializers.Serializer):
    community_view = CommunityViewSerializer()
    blocked = serializers.BooleanField()


class SearchSerializer(LemmySerializer):
    """
    Serializer for search query parameters.

    The search endpoint supports:
    - Webfinger addresses: @user@domain, !community@domain
    - Direct URLs: https://example.com/post/123
    - Plain text search: searches local database
    """

    q = serializers.CharField(required=True)
    type_ = serializers.ChoiceField(
        choices=SearchType.choices, required=False, default=SearchType.ALL
    )
    community_id = RelatedLemmyObjectField(
        source="community",
        queryset=models.Community.objects.all(),
        required=False,
        allow_null=True,
    )
    community_name = serializers.CharField(required=False, allow_null=True)
    creator_id = RelatedLemmyObjectField(
        source="creator",
        queryset=models.Person.objects.all(),
        required=False,
        allow_null=True,
    )
    sort = serializers.CharField(required=False, allow_null=True)
    listing_type = serializers.CharField(required=False, allow_null=True)
    page = serializers.IntegerField(required=False, default=1, min_value=1)
    limit = serializers.IntegerField(required=False, default=10, min_value=1, max_value=50)


class SearchResponseSerializer(LemmySerializer):
    """
    Response serializer for search results.

    Returns lists of matching objects based on search type.
    """

    type_ = serializers.ChoiceField(choices=SearchType.choices, read_only=True)
    comments = CommentViewSerializer(many=True, read_only=True)
    posts = PostViewSerializer(many=True, read_only=True)
    communities = CommunityViewSerializer(many=True, read_only=True)
    users = PersonViewSerializer(many=True, read_only=True)


class LocalUserSerializer(LemmyModelSerializer):
    id = IdentityField(source="user.id")
    person_id = IdentityField(source="person.object_id")

    class Meta:
        model = models.UserProfile
        fields = ("id", "person_id")


class LocalUserVoteDisplaySerializer(LemmyModelSerializer):
    local_user_id = IdentityField(source="user.id")
    score = serializers.BooleanField(source="show_vote_score")
    upvotes = serializers.BooleanField(source="show_upvotes")
    downvotes = serializers.BooleanField(source="show_downvotes")
    upvote_percentage = serializers.BooleanField(source="show_upvote_percentage")

    class Meta:
        model = models.UserSettings
        fields = ("local_user_id", "score", "upvotes", "downvotes", "upvote_percentage")


# User / Account Serializers
class LocalUserViewSerializer(LemmyModelSerializer):
    local_user = LocalUserSerializer(source="*")
    local_user_vote_display_mode = LocalUserVoteDisplaySerializer(source="user.lemmy_settings")
    person = PersonSerializer()
    counts = PersonAggregatesSerializer(source="person")

    class Meta:
        model = models.UserProfile
        fields = ("local_user", "local_user_vote_display_mode", "person", "counts")
        read_only_fields = ("local_user", "person", "counts")


class IdentityFollowSerializer(LemmySerializer):
    community = CommunitySerializer()
    follower = PersonSerializer()


class UserProfileSerializer(LemmySerializer):
    follows = serializers.SerializerMethodField()
    moderates = serializers.SerializerMethodField()
    community_blocks = serializers.SerializerMethodField()
    instance_blocks = serializers.SerializerMethodField()
    person_blocks = serializers.SerializerMethodField()

    def get_follows(self, obj):
        communities = obj.person and obj.person.subscribed_communities.all()

        if not communities:
            return []

        person_data = PersonSerializer(instance=obj.person).data
        return [
            {"community": CommunitySerializer(instance=c).data, "follower": person_data}
            for c in communities
        ]

    def get_moderates(self, obj):
        return []

    def get_community_blocks(self, obj):
        return []

    def get_person_blocks(self, obj):
        return []

    def get_instance_blocks(self, obj):
        return []

    class Meta:
        model = models.UserProfile
        fields = (
            "follows",
            "moderates",
            "community_blocks",
            "instance_blocks",
            "person_blocks",
        )


class GetPersonDetailsSerializer(LemmySerializer):
    """Input validation for GET /api/v3/user"""

    person_id = IdentityField(required=False, allow_null=True)
    username = serializers.CharField(required=False, allow_null=True)
    sort = serializers.CharField(required=False, allow_null=True)
    page = serializers.IntegerField(required=False, default=1)
    limit = serializers.IntegerField(required=False, default=10)
    community_id = IdentityField(required=False, allow_null=True)
    saved_only = serializers.BooleanField(required=False, default=False)


class CommunityModeratorViewSerializer(LemmySerializer):
    """For the 'moderates' list in GetPersonDetailsResponse"""

    community = CommunitySerializer()
    moderator = PersonSerializer()


class GetPersonDetailsResponseSerializer(LemmySerializer):
    """Response for GET /api/v3/user"""

    person_view = PersonViewSerializer()
    site = SiteSerializer(required=False, allow_null=True)
    comments = CommentViewSerializer(many=True)
    posts = PostViewSerializer(many=True)
    moderates = CommunityModeratorViewSerializer(many=True)


class InstanceWithFederationStateSerializer(LemmyModelSerializer):
    """
    Serializes a Site as an instance for the federated_instances endpoint.
    Includes optional federation_state if tracking data exists.
    """

    # Map Site fields to API response fields
    domain = serializers.CharField(source="reference.domain.netloc", read_only=True)
    published = serializers.DateTimeField(source="reference.created", read_only=True)
    updated = serializers.DateTimeField(source="reference.modified", read_only=True)
    software = serializers.CharField(read_only=True)  # Uses Site.software property
    version = serializers.CharField(read_only=True)  # Uses Site.version property

    # Federation state - nested object (only if data exists)
    federation_state = serializers.SerializerMethodField()

    def get_federation_state(self, obj):
        """Return federation_state only if we have tracking data"""
        if not obj.last_successful_notification_id and obj.fail_count == 0:
            return None

        return {
            "instance_id": obj.object_id,
            "last_successful_id": obj.last_successful_notification_id,
            "last_successful_published_time": obj.last_successful_published_time,
            "fail_count": obj.fail_count,
            "last_retry": obj.last_retry,
            "next_retry": obj.next_retry,  # Uses Site.next_retry property
        }

    class Meta:
        model = models.Site
        fields = (
            "id",  # From LemmyModelSerializer (object_id)
            "domain",
            "published",
            "updated",
            "software",
            "version",
            "federation_state",
        )


class FederatedInstancesSerializer(LemmySerializer):
    """Container for linked/allowed/blocked instance lists"""

    linked = InstanceWithFederationStateSerializer(many=True)
    allowed = InstanceWithFederationStateSerializer(many=True)
    blocked = InstanceWithFederationStateSerializer(many=True)


class GetFederatedInstancesResponseSerializer(LemmySerializer):
    """Top-level response wrapper for GET /api/v3/federated_instances"""

    federated_instances = FederatedInstancesSerializer(allow_null=True)


class LoginTokenSerializer(serializers.ModelSerializer):
    """
    Serializer for LoginToken (used in list_logins response).
    Returns login session metadata for the API.
    """

    published = serializers.DateTimeField(source="created")
    user_id = serializers.SerializerMethodField()

    def get_user_id(self, obj):
        """Convert Django user to Lemmy Person object_id"""
        if obj.user:
            identity = Identity.objects.filter(user=obj.user).first()
            if identity:
                person = models.Person.objects.filter(reference=identity.actor.reference).first()
                return person and person.object_id
        return None

    class Meta:
        model = models.LoginToken
        fields = ("user_id", "published", "ip", "user_agent")
