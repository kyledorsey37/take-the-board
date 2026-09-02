from django.contrib.auth.models import AnonymousUser, User
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.core.admin_mfa import _staff
from apps.core.middleware.health_check import HealthCheckHostMiddleware
from apps.core.middleware.request_id import REQUEST_ID_PATTERN, RequestIDMiddleware
from apps.core.middleware.security import SecurityHeadersMiddleware


class SecurityHeaderTests(SimpleTestCase):
    def test_malformed_request_id_is_replaced(self):
        request = RequestFactory().get("/", HTTP_X_REQUEST_ID="x" * 65)
        response = RequestIDMiddleware(lambda request: HttpResponse("ok"))(request)
        self.assertRegex(response["X-Request-ID"], REQUEST_ID_PATTERN)

    @override_settings(CSP_REPORT_ONLY="default-src 'self'", PERMISSIONS_POLICY="camera=()")
    def test_security_headers_and_auth_cache_policy(self):
        request = RequestFactory().get("/auth/callback/")
        response = SecurityHeadersMiddleware(lambda request: HttpResponse("ok"))(request)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["Content-Security-Policy-Report-Only"], "default-src 'self'")
        self.assertEqual(response["Permissions-Policy"], "camera=()")


class HealthCheckHostMiddlewareTests(SimpleTestCase):
    @override_settings(ALLOWED_HOSTS=["taketheboard.com"])
    def test_normalizes_alb_health_check_host(self):
        request = RequestFactory().get(
            "/healthz/",
            HTTP_HOST="10.42.1.25:8000",
            HTTP_USER_AGENT="ELB-HealthChecker/2.0",
        )
        response = HealthCheckHostMiddleware(
            lambda request: HttpResponse(request.get_host())
        )(request)

        self.assertEqual(response.content, b"taketheboard.com")
        self.assertEqual(request.META["HTTP_X_FORWARDED_PROTO"], "https")

    @override_settings(ALLOWED_HOSTS=["taketheboard.com"])
    def test_does_not_normalize_non_health_check_requests(self):
        request = RequestFactory().get(
            "/healthz/",
            HTTP_HOST="10.42.1.25:8000",
            HTTP_USER_AGENT="Mozilla/5.0",
        )
        HealthCheckHostMiddleware(lambda request: HttpResponse("ok"))(request)

        self.assertEqual(request.META["HTTP_HOST"], "10.42.1.25:8000")


class AdminMfaPredicateTests(SimpleTestCase):
    def test_staff_predicate_accepts_the_user_passed_by_django(self):
        staff_user = User(is_staff=True)
        non_staff_user = User(is_staff=False)

        self.assertTrue(_staff(staff_user))
        self.assertFalse(_staff(non_staff_user))
        self.assertFalse(_staff(AnonymousUser()))


class AdminMfaViewTests(TestCase):
    def test_staff_user_can_reach_the_mfa_gate(self):
        staff_user = User.objects.create_user(username="staff", is_staff=True)
        self.client.force_login(staff_user)

        response = self.client.get(reverse("admin_mfa"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data:image/svg+xml;base64,")
        self.assertContains(response, "Can’t scan? Use a setup key")
        self.assertNotContains(response, "otpauth://")
