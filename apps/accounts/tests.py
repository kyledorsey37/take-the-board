from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError
from django.test import Client, TestCase, override_settings
from django.core.cache import cache
from django.urls import reverse

from apps.accounts.models import UserProfile
from apps.accounts.services.cognito import (
    CognitoTokens,
    CognitoError,
    hydrate_profile,
    start_email_auth,
    verify_email_code,
)
from apps.accounts.services.session import AUTH_SESSION_KEY, PENDING_AUTH_SESSION_KEY
from apps.moderation.services.rate_limits import RateLimitExceeded as ModerationRateLimitExceeded


AUTH_SETTINGS = {
    "TAKEBOARD_COGNITO_AUTH_ENABLED": True,
    "COGNITO_REGION": "us-east-1",
    "COGNITO_USER_POOL_ID": "us-east-1_example",
    "COGNITO_CLIENT_ID": "test-client-id",
}


@override_settings(**AUTH_SETTINGS)
class EmailAuthenticationTests(TestCase):
    @override_settings(
        TAKEBOARD_COGNITO_AUTH_ENABLED=False,
        TAKEBOARD_AUTH_MODAL_PREVIEW=True,
    )
    def test_preview_renders_the_email_modal_without_enabling_cognito(self) -> None:
        response = self.client.get(reverse("core:home"))

        self.assertContains(response, 'id="auth-modal"')
        self.assertContains(response, "Preview mode")
        self.assertContains(response, "Sign in")
        self.assertContains(response, "Use a different email")
        self.assertContains(response, 'data-auth-preview="true"')

    def test_start_email_auth_stores_only_pending_server_state(self) -> None:
        with patch(
            "apps.accounts.views.start_email_auth",
            return_value={
                "flow": "signin",
                "username": "cognito-user",
                "email": "fan@example.com",
                "challenge_session": "cognito-session",
            },
        ) as start_email_auth:
            response = self.client.post(reverse("accounts:email_start"), {"email": " FAN@EXAMPLE.COM "})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "message": "Check your email for a code."})
        start_email_auth.assert_called_once_with("fan@example.com")
        self.assertEqual(self.client.session[PENDING_AUTH_SESSION_KEY]["email"], "fan@example.com")

    @patch("apps.accounts.services.cognito.client")
    def test_signup_confirmation_uses_the_same_code_to_sign_in(self, mock_client) -> None:
        cognito = MagicMock()
        cognito.confirm_sign_up.return_value = {"Session": "confirmed-signup-session"}
        cognito.initiate_auth.return_value = {
            "AuthenticationResult": {
                "AccessToken": "access-token",
                "IdToken": "id-token",
                "RefreshToken": "refresh-token",
                "ExpiresIn": 3600,
            }
        }
        mock_client.return_value = cognito

        pending = {
            "flow": "signup",
            "username": "new-cognito-user",
            "email": "fan@example.com",
        }
        next_pending, tokens = verify_email_code(pending, "123456")

        self.assertIsNone(next_pending)
        self.assertEqual(tokens.access_token, "access-token")
        cognito.confirm_sign_up.assert_called_once()
        initiate_kwargs = cognito.initiate_auth.call_args.kwargs
        self.assertEqual(initiate_kwargs["ClientId"], "test-client-id")
        self.assertEqual(initiate_kwargs["AuthFlow"], "USER_AUTH")
        self.assertEqual(initiate_kwargs["Session"], "confirmed-signup-session")
        self.assertEqual(initiate_kwargs["AuthParameters"]["USERNAME"], "new-cognito-user")
        self.assertNotIn("PREFERRED_CHALLENGE", initiate_kwargs["AuthParameters"])

    def test_verified_email_otp_hydrates_a_server_side_session(self) -> None:
        profile = UserProfile.objects.create(
            cognito_sub="existing-cognito-subject",
            email="fan@example.com",
        )
        session = self.client.session
        session[PENDING_AUTH_SESSION_KEY] = {
            "flow": "signin",
            "username": "cognito-user",
            "email": "fan@example.com",
            "challenge_session": "otp-session",
            "expires_at": 4_000_000_000,
        }
        session.save()
        tokens = CognitoTokens(
            access_token="access-token",
            id_token="id-token",
            refresh_token="refresh-token",
            expires_in=3600,
        )
        with patch("apps.accounts.views.verify_email_code", return_value=(None, tokens)), patch(
            "apps.accounts.views.hydrate_profile", return_value=profile
        ):
            response = self.client.post(reverse("accounts:email_verify"), {"code": "123456"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"ok": True, "signed_in": True, "needs_display_name": True},
        )
        auth_session = self.client.session[AUTH_SESSION_KEY]
        self.assertEqual(auth_session["profile_id"], profile.id)
        self.assertEqual(auth_session["access_token"], "access-token")
        self.assertNotIn(PENDING_AUTH_SESSION_KEY, self.client.session)

    def test_authenticated_user_can_set_a_board_name_once(self) -> None:
        cache.clear()
        profile = UserProfile.objects.create(
            cognito_sub="new-cognito-subject",
            email="fan@example.com",
        )
        session = self.client.session
        session[AUTH_SESSION_KEY] = {
            "profile_id": profile.id,
            "cognito_sub": profile.cognito_sub,
            "access_token": "access-token",
            "id_token": "id-token",
            "refresh_token": "refresh-token",
            "expires_at": 4_000_000_000,
        }
        session.save()

        with patch(
            "apps.moderation.services.validation.classify_message",
            return_value=__import__(
                "apps.moderation.services.nova_classifier", fromlist=["Classification"]
            ).Classification("allow", "safe", 0.99),
        ):
            response = self.client.post(
                reverse("accounts:set_display_name"),
                {"display_name": "BoardBoss"},
            )

        self.assertEqual(response.json(), {"ok": True})
        profile.refresh_from_db()
        self.assertEqual(profile.display_name, "BoardBoss")

        response = self.client.post(
            reverse("accounts:set_display_name"),
            {"display_name": "DifferentName"},
        )
        self.assertEqual(response.status_code, 409)

    def test_display_name_rate_limit_is_reported_as_a_rate_limit(self) -> None:
        profile = UserProfile.objects.create(
            cognito_sub="rate-limited-cognito-subject",
            email="rate-limited@example.com",
        )
        session = self.client.session
        session[AUTH_SESSION_KEY] = {
            "profile_id": profile.id,
            "cognito_sub": profile.cognito_sub,
            "access_token": "access-token",
            "id_token": "id-token",
            "refresh_token": "refresh-token",
            "expires_at": 4_000_000_000,
        }
        session.save()

        with patch(
            "apps.accounts.views.validate_display_name",
            side_effect=ModerationRateLimitExceeded,
        ):
            response = self.client.post(
                reverse("accounts:set_display_name"),
                {"display_name": "RateLimitedFan"},
            )

        self.assertEqual(response.status_code, 429)
        self.assertIn("reached the limit", response.json()["error"])

    @patch("apps.accounts.services.cognito.client")
    def test_email_only_pool_uses_email_as_the_cognito_username(self, mock_client) -> None:
        cognito = MagicMock()
        cognito.list_users.return_value = {"Users": []}
        cognito.sign_up.return_value = {"UserConfirmed": False}
        mock_client.return_value = cognito

        pending = start_email_auth("fan@example.com")

        self.assertEqual(pending["username"], "fan@example.com")
        self.assertEqual(cognito.sign_up.call_args.kwargs["Username"], "fan@example.com")

    @patch("apps.accounts.services.cognito.client")
    def test_cognito_start_logs_only_the_safe_aws_error_code(self, mock_client) -> None:
        cognito = MagicMock()
        cognito.list_users.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "sensitive detail"}},
            "ListUsers",
        )
        mock_client.return_value = cognito

        with self.assertLogs("apps.accounts.services.cognito", level="WARNING") as logs:
            with self.assertRaises(CognitoError):
                start_email_auth("fan@example.com")

        self.assertIn("cognito_email_auth_start_failed code=AccessDeniedException", logs.output[0])
        self.assertNotIn("sensitive detail", logs.output[0])

    @patch("apps.accounts.services.cognito.client")
    def test_cognito_subject_is_stored_as_an_opaque_string(self, mock_client) -> None:
        cognito = MagicMock()
        cognito.get_user.return_value = {
            "UserAttributes": [
                {"Name": "sub", "Value": "opaque-cognito-subject"},
                {"Name": "email", "Value": "fan@example.com"},
            ]
        }
        mock_client.return_value = cognito
        tokens = CognitoTokens(
            access_token="access-token",
            id_token="id-token",
            refresh_token="refresh-token",
            expires_in=3600,
        )

        profile = hydrate_profile(tokens)

        self.assertEqual(profile.cognito_sub, "opaque-cognito-subject")

    def test_email_endpoints_keep_csrf_protection(self) -> None:
        csrf_client = Client(enforce_csrf_checks=True)

        response = csrf_client.post(reverse("accounts:email_start"), {"email": "fan@example.com"})

        self.assertEqual(response.status_code, 403)

    def test_hosted_callback_rejects_an_invalid_state(self) -> None:
        session = self.client.session
        session["takeboard.auth.oauth_state"] = "expected-state"
        session.save()

        response = self.client.get(reverse("accounts:oauth_callback"), {"state": "wrong-state", "code": "code"})

        self.assertEqual(response.status_code, 400)

    def test_sign_in_modal_renders_when_cognito_auth_is_enabled(self) -> None:
        response = self.client.get(reverse("core:home"))

        self.assertContains(response, 'id="auth-modal"')
        self.assertContains(response, reverse("accounts:email_start"))
