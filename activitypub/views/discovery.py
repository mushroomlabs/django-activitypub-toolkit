from django.http import Http404, HttpResponse, JsonResponse
from django.views.generic import View

from ..models import Account, Domain
from ..settings import app_settings


class NodeInfo(View):
    """
    Returns the well-known nodeinfo response, pointing to the 2.0 one
    """

    def get(self, request):
        default_domain = Domain.get_default()
        host = request.META.get("HTTP_HOST", default_domain)
        scheme = "http://" if not request.is_secure() else "https://"
        return JsonResponse(
            {
                "links": [
                    {
                        "rel": "http://nodeinfo.diaspora.software/ns/schema/2.0",
                        "href": f"{scheme}{host}/nodeinfo/2.0",
                    },
                    {
                        "rel": "http://nodeinfo.diaspora.software/ns/schema/2.1",
                        "href": f"{scheme}{host}/nodeinfo/2.1",
                    },
                ]
            }
        )


class NodeInfo20(View):
    def get_metadata(self, request):
        return {}

    def get_usage(self, request):
        default_domain = Domain.get_default()
        host = request.META.get("HTTP_HOST", default_domain.name).split(":", 1)[0]
        return {"users": {"total": Account.objects.filter(domain__name=host).count()}}

    def get(self, request):
        return JsonResponse(
            {
                "version": "2.0",
                "software": {
                    "name": app_settings.NodeInfo.software_name,
                    "version": app_settings.NodeInfo.software_version,
                },
                "protocols": ["activitypub"],
                "services": {"outbound": [], "inbound": []},
                "openRegistrations": app_settings.Instance.open_registrations,
                "metadata": self.get_metadata(request),
                "usage": self.get_usage(request),
            }
        )


class NodeInfo21(View):
    def get_metadata(self, request):
        return {}

    def get_usage(self, request):
        default_domain = Domain.get_default()
        host = request.META.get("HTTP_HOST", default_domain.name).split(":", 1)[0]
        return {"users": {"total": Account.objects.filter(domain__name=host).count()}}

    def get(self, request):
        return JsonResponse(
            {
                "version": "2.1",
                "software": {
                    "name": app_settings.NodeInfo.software_name,
                    "version": app_settings.NodeInfo.software_version,
                },
                "protocols": ["activitypub"],
                "services": {"outbound": [], "inbound": []},
                "openRegistrations": app_settings.Instance.open_registrations,
                "metadata": self.get_metadata(request),
                "usage": self.get_usage(request),
            }
        )


class Webfinger(View):
    def resolve_account(self, request, subject_name):
        try:
            return Account.objects.get_by_subject_name(subject_name)
        except Account.DoesNotExist:
            raise Http404

    def get_profile_page_url(self, request, account):
        return None

    def related_links(self, request, account):
        links = []
        profile_page = self.get_profile_page_url(request, account)
        if profile_page:
            links.append(
                {
                    "rel": "http://webfinger.net/rel/profile-page",
                    "type": "text/html",
                    "href": profile_page,
                }
            )
        links.append(
            {
                "rel": "self",
                "type": "application/activity+json",
                "href": account.actor.uri,
            }
        )
        return links

    def get(self, request):
        CONTENT_TYPE = "application/jrd+json"
        resource = request.GET.get("resource")
        if not resource:
            return JsonResponse(
                {"error": "No resource specified"}, content_type=CONTENT_TYPE, status=400
            )
        if not resource.startswith("acct:"):
            return JsonResponse(
                {"error": "Not an account resource"}, content_type=CONTENT_TYPE, status=400
            )
        subject_name = resource[5:]

        try:
            account = self.resolve_account(request, subject_name)
        except Http404:
            return JsonResponse(
                {"error": "account not found"}, content_type="application/jrd+json", status=404
            )

        account_data = {
            "subject": f"acct:{subject_name}",
            "aliases": [
                account.actor.uri,
            ],
            "links": self.related_links(request, account),
        }

        return JsonResponse(account_data, content_type="application/jrd+json")


class HostMeta(View):
    def get(self, request):
        CONTENT_TYPE = "application/xrd+xml"
        host = request.META.get("HTTP_HOST", Domain.get_default().name)
        scheme = "http://" if not request.is_secure() else "https://"
        xml = """
        <?xml version="1.0" encoding="UTF-8"?>
        <XRD xmlns="http://docs.oasis-open.org/ns/xri/xrd-1.0">
        <Link rel="lrdd" template="{0}{1}/.well-known/webfinger?resource={{uri}}"/>
        </XRD>""".format(scheme, host)
        return HttpResponse(xml.strip().replace(8 * " ", ""), content_type=CONTENT_TYPE)


__all__ = ["NodeInfo", "NodeInfo20", "NodeInfo21", "Webfinger", "HostMeta"]
