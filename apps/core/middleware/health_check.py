from django.conf import settings


class HealthCheckHostMiddleware:
    """Allow the ALB health checker to reach the public health endpoint.

    The ALB sends its target IP as the Host header. Django validates that
    header before resolving the URL, so normalize only the known ALB health
    check request to the first configured public host.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        if (
            request.path == "/healthz/"
            and request.method in {"GET", "HEAD"}
            and user_agent.startswith("ELB-HealthChecker/")
            and settings.ALLOWED_HOSTS
        ):
            request.META["HTTP_HOST"] = settings.ALLOWED_HOSTS[0]
            request.META["HTTP_X_FORWARDED_PROTO"] = "https"
        return self.get_response(request)
