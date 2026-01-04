import httpretty
from django.test import TestCase, override_settings

from activitypub import models
from activitypub.exceptions import RejectedFollowRequest
from activitypub.factories import ActorFactory, ReferenceFactory, DomainFactory
from activitypub.tests.base import silence_notifications, use_nodeinfo, with_remote_reference


class FollowRequestPolicyTestCase(TestCase):
    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @use_nodeinfo("https://local.example.com", "nodeinfo/testserver.json")
    @with_remote_reference("https://remote.example.com/users/alice", "standard/actor.alice.json")
    def setUp(self):
        self.remote_domain = DomainFactory(name="remote.example.com", local=False)
        self.local_domain = DomainFactory(name="local.example.com", local=True)
        self.local_actor = ActorFactory(
            reference__uri="https://local.example.com/users/bob",
            reference__domain=self.local_domain,
        )
        self.remote_actor = ActorFactory(
            reference__uri="https://remote.example.com/users/alice",
            reference__domain=self.remote_domain,
        )
        self.remote_follow_reference = ReferenceFactory(domain=self.remote_domain)

    @httpretty.activate
    @use_nodeinfo("https://local.example.com", "nodeinfo/testserver.json")
    def test_follow_request_accepted_without_manual_approval(self):
        self.local_actor.manually_approves_followers = False
        self.local_actor.save()

        follow_activity = models.Activity.make(
            reference=self.remote_follow_reference,
            type=models.Activity.Types.FOLLOW,
            actor=self.remote_actor.reference,
            object=self.local_actor.reference,
        )

        follow_request = models.FollowRequest.objects.create(
            follower=follow_activity.actor,
            followed=follow_activity.object,
            activity=self.remote_follow_reference,
        )

        self.assertEqual(follow_request.status, models.FollowRequest.STATUS.accepted)

    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @use_nodeinfo("https://local.example.com", "nodeinfo/testserver.json")
    def test_follow_request_pending_with_manual_approval(self):
        self.local_actor.manually_approves_followers = True
        self.local_actor.save()

        follow_activity = models.Activity.make(
            reference=models.Activity.generate_reference(self.remote_domain),
            type=models.Activity.Types.FOLLOW,
            actor=self.remote_actor.reference,
            object=self.local_actor.reference,
        )

        follow_request = models.FollowRequest.objects.create(
            follower=follow_activity.actor,
            followed=follow_activity.object,
            activity=follow_activity.reference,
        )

        self.assertEqual(follow_request.status, models.FollowRequest.STATUS.submitted)

    @override_settings(
        FEDERATION={
            "REJECT_FOLLOW_REQUEST_CHECKS": [
                "activitypub.tests.test_policies.reject_all_policy",
            ]
        }
    )
    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @use_nodeinfo("https://local.example.com", "nodeinfo/testserver.json")
    def test_follow_request_rejected_by_policy(self):
        self.local_actor.manually_approves_followers = False
        self.local_actor.save()

        follow_activity = models.Activity.make(
            reference=models.Activity.generate_reference(self.remote_actor.reference.domain),
            type=models.Activity.Types.FOLLOW,
            actor=self.remote_actor.reference,
            object=self.local_actor.reference,
        )

        follow_request = models.FollowRequest.objects.create(
            follower=follow_activity.actor,
            followed=follow_activity.object,
            activity=follow_activity.reference,
        )

        self.assertEqual(follow_request.status, models.FollowRequest.STATUS.rejected)

    @override_settings(
        FEDERATION={
            "REJECT_FOLLOW_REQUEST_CHECKS": [
                "activitypub.tests.test_policies.accept_policy",
            ]
        }
    )
    @httpretty.activate
    @use_nodeinfo("https://remote.example.com", "nodeinfo/mastodon.json")
    @use_nodeinfo("https://local.example.com", "nodeinfo/testserver.json")
    def test_follow_request_passes_policy_check(self):
        self.local_actor.manually_approves_followers = False
        self.local_actor.save()

        follow_activity = models.Activity.make(
            reference=models.Activity.generate_reference(self.remote_domain),
            type=models.Activity.Types.FOLLOW,
            actor=self.remote_actor.reference,
            object=self.local_actor.reference,
        )

        follow_request = models.FollowRequest.objects.create(
            follower=follow_activity.actor,
            followed=follow_activity.object,
            activity=follow_activity.reference,
        )

        self.assertEqual(follow_request.status, models.FollowRequest.STATUS.accepted)

    @override_settings(
        FEDERATION={
            "REJECT_FOLLOW_REQUEST_CHECKS": [
                "activitypub.tests.test_policies.reject_bot_actors",
            ]
        }
    )
    @httpretty.activate
    @use_nodeinfo("https://bot.example.com", "nodeinfo/mastodon.json")
    @use_nodeinfo("https://local.example.com", "nodeinfo/testserver.json")
    def test_follow_request_rejected_by_bot_check_policy(self):
        remote_bot = ActorFactory(
            reference__domain__local=False,
            reference__domain__name="bot.example.com",
            reference__uri="https://bot.example.com/user/example-bot",
        )

        follow_activity = models.Activity.make(
            reference=models.Activity.generate_reference(remote_bot.reference.domain),
            type=models.Activity.Types.FOLLOW,
            actor=remote_bot.reference,
            object=self.local_actor.reference,
        )

        follow_request = models.FollowRequest.objects.create(
            follower=follow_activity.actor,
            followed=follow_activity.object,
            activity=follow_activity.reference,
        )

        self.assertEqual(follow_request.status, models.FollowRequest.STATUS.rejected)

    @httpretty.activate
    @use_nodeinfo("https://bot.example.com", "nodeinfo/mastodon.json")
    @use_nodeinfo("https://local.example.com", "nodeinfo/testserver.json")
    @silence_notifications("https://remote.example.com")
    def test_follow_request_only_processed_for_local_actors(self):
        remote_target = ActorFactory(reference__domain=self.remote_domain)
        remote_target.manually_approves_followers = False
        remote_target.save()

        follow_activity = models.Activity.make(
            reference=models.Activity.generate_reference(self.remote_domain),
            type=models.Activity.Types.FOLLOW,
            actor=self.remote_actor.reference,
            object=remote_target.reference,
        )

        follow_request = models.FollowRequest.objects.create(
            follower=follow_activity.actor,
            followed=follow_activity.object,
            activity=follow_activity.reference,
        )

        self.assertEqual(follow_request.status, models.FollowRequest.STATUS.submitted)


def reject_all_policy(follower, target):
    raise RejectedFollowRequest("Policy rejects all follows")


def accept_policy(follower, target):
    pass


def reject_bot_actors(follower, target):
    if "bot" in follower.uri:
        raise RejectedFollowRequest("Bots are automatically rejected")
