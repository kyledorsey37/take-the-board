from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

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
