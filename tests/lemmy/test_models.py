from django.test import TestCase

from activitypub.adapters.lemmy.models import LocalSite


class LocalSiteTestCase(TestCase):
    def test_can_load_site(self):
        local_site = LocalSite.setup("http://testserver")
        self.assertIsNotNone(local_site)
        self.assertIsNotNone(local_site.site.actor)
        self.assertIsNotNone(local_site.site.actor.inbox)
        self.assertIsNotNone(local_site.site.actor.outbox)
