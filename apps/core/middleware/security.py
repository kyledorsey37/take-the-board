from django.conf import settings


class SecurityHeadersMiddleware:
    """Application-owned browser policy; edge headers may add stricter policy."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["Content-Security-Policy-Report-Only"] = settings.CSP_REPORT_ONLY
        response["Permissions-Policy"] = settings.PERMISSIONS_POLICY
        response["X-Content-Type-Options"] = "nosniff"
        response["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.path.startswith(("/api/auth/", "/auth/callback/", "/login/", "/signup/")):
            response["Cache-Control"] = "no-store"
        return response
