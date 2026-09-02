import logging
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect

from apps.accounts.services.rate_limit import RateLimitExceeded, RateLimitUnavailable, enforce_admin_login_rate_limit

logger = logging.getLogger(__name__)
ADMIN_MFA_SESSION_KEY = "takeboard.admin.mfa_verified"


class AdminSecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/admin/login/" and request.method == "POST":
            try:
                enforce_admin_login_rate_limit(request.META.get("REMOTE_ADDR", "unknown"))
            except RateLimitUnavailable:
                logger.warning("admin_login_throttle_unavailable")
                return HttpResponse("Admin sign-in is temporarily unavailable.", status=503)
            except RateLimitExceeded:
                logger.info("admin_login_rate_limited")
                return HttpResponse("Too many admin sign-in attempts. Try again later.", status=429)
        if request.path.startswith("/admin/") and settings.TAKEBOARD_ENVIRONMENT != "local":
            if request.path not in {"/admin/login/", "/admin/mfa/", "/admin/mfa/enroll/"} and getattr(request, "user", None) and request.user.is_staff:
                if not request.session.get(ADMIN_MFA_SESSION_KEY):
                    return redirect("admin_mfa")
        return self.get_response(request)
