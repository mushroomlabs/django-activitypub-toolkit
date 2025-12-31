import pytest
from django.test import TestCase, override_settings

from activitypub import models
from activitypub.exceptions import RejectedFollowRequest
from activitypub.factories import ActorFactory
from activitypub.settings import app_settings


class FollowRequestPolicyTestCase(TestCase):
    def setUp(self):
        self.local_actor = ActorFactory(reference__domain__local=True)
        self.remote_actor = ActorFactory(reference__domain__local=False)

    def test_follow_request_accepted_without_manual_approval(self):
        self.local_actor.manually_approves_followers = False
        self.local_actor.save()

        follow_activity = models.Activity.make(
            reference=models.Activity.generate_reference(self.remote_actor.reference.domain),
            type=models.Activity.Types.FOLLOW,
            actor=self.remote_actor.reference,
            object=self.local_actor.reference,
        )

        follow_request = models.FollowRequest.objects.create(activity=follow_activity)

        self.assertEqual(follow_request.status, models.FollowRequest.STATUS.accepted)

    def test_follow_request_pending_with_manual_approval(self):
        self.local_actor.manually_approves_followers = True
        self.local_actor.save()

        follow_activity = models.Activity.make(
            reference=models.Activity.generate_reference(self.remote_actor.reference.domain),
            type=models.Activity.Types.FOLLOW,
            actor=self.remote_actor.reference,
            object=self.local_actor.reference,
        )

        follow_request = models.FollowRequest.objects.create(activity=follow_activity)

        self.assertEqual(follow_request.status, models.FollowRequest.STATUS.pending)

    @override_settings(
        FEDERATION={
            "REJECT_FOLLOW_REQUEST_CHECKS": [
                "activitypub.tests.test_policies.reject_all_policy",
            ]
        }
    )
    def test_follow_request_rejected_by_policy(self):
        self.local_actor.manually_approves_followers = False
        self.local_actor.save()

        follow_activity = models.Activity.make(
            reference=models.Activity.generate_reference(self.remote_actor.reference.domain),
            type=models.Activity.Types.FOLLOW,
            actor=self.remote_actor.reference,
            object=self.local_actor.reference,
        )

        follow_request = models.FollowRequest.objects.create(activity=follow_activity)

        self.assertEqual(follow_request.status, models.FollowRequest.STATUS.rejected)

    @override_settings(
        FEDERATION={
            "REJECT_FOLLOW_REQUEST_CHECKS": [
                "activitypub.tests.test_policies.accept_policy",
            ]
        }
    )
    def test_follow_request_passes_policy_check(self):
        self.local_actor.manually_approves_followers = False
        self.local_actor.save()

        follow_activity = models.Activity.make(
            reference=models.Activity.generate_reference(self.remote_actor.reference.domain),
            type=models.Activity.Types.FOLLOW,
            actor=self.remote_actor.reference,
            object=self.local_actor.reference,
        )

        follow_request = models.FollowRequest.objects.create(activity=follow_activity)

        self.assertEqual(follow_request.status, models.FollowRequest.STATUS.accepted)

    @override_settings(
        FEDERATION={
            "REJECT_FOLLOW_REQUEST_CHECKS": [
                "activitypub.tests.test_policies.reject_bot_actors",
            ]
        }
    )
    def test_follow_request_rejected_by_bot_check_policy(self):
        remote_bot = ActorFactory(
            reference__domain__local=False,
            reference__uri="https://bot.example.com/user/example-bot",
        )

        follow_activity = models.Activity.make(
            reference=models.Activity.generate_reference(remote_bot.reference.domain),
            type=models.Activity.Types.FOLLOW,
            actor=remote_bot.reference,
            object=self.local_actor.reference,
        )

        follow_request = models.FollowRequest.objects.create(activity=follow_activity)

        self.assertEqual(follow_request.status, models.FollowRequest.STATUS.rejected)

    def test_follow_request_only_processed_for_local_actors(self):
        remote_target = ActorFactory(reference__domain__local=False)
        remote_target.manually_approves_followers = False
        remote_target.save()

        follow_activity = models.Activity.make(
            reference=models.Activity.generate_reference(self.remote_actor.reference.domain),
            type=models.Activity.Types.FOLLOW,
            actor=self.remote_actor.reference,
            object=remote_target.reference,
        )

        follow_request = models.FollowRequest.objects.create(activity=follow_activity)

        self.assertEqual(follow_request.status, models.FollowRequest.STATUS.pending)


def reject_all_policy(follower, target):
    raise RejectedFollowRequest("Policy rejects all follows")


def accept_policy(follower, target):
    pass


def reject_bot_actors(follower, target):
    if "bot.example.com" in follower.uri:
        raise RejectedFollowRequest("Bots are automatically rejected")
