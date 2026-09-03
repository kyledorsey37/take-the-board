from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError
from django.test import Client, TestCase, override_settings
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.accounts.services.cognito import (
    CognitoTokens,
    CognitoError,
    hydrate_profile,
    start_email_auth,
    verify_email_code,
)
from apps.accounts.services.session import (
    AUTH_SESSION_KEY,
    PENDING_AUTH_SESSION_KEY,
    get_authenticated_profile,
)
from apps.moderation.services.rate_limits import RateLimitExceeded as ModerationRateLimitExceeded
from apps.bidding.models import Bid
from apps.boards.models import Board, BoardTakeover
from apps.payments.models import LedgerEntry, PaymentCapture
from apps.schools.models import Competition, Entity


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
        initial_session_key = session.session_key
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
        self.assertEqual(
            set(auth_session),
            {"profile_id", "cognito_sub", "expires_at"},
        )
        self.assertEqual(auth_session["profile_id"], profile.id)
        self.assertEqual(auth_session["cognito_sub"], profile.cognito_sub)
        self.assertNotIn("access_token", auth_session)
        self.assertNotIn("id_token", auth_session)
        self.assertNotIn("refresh_token", auth_session)
        self.assertNotIn(PENDING_AUTH_SESSION_KEY, self.client.session)
        self.assertNotEqual(self.client.session.session_key, initial_session_key)

    def test_legacy_token_fields_are_removed_from_an_existing_session(self) -> None:
        profile = UserProfile.objects.create(
            cognito_sub="legacy-session-subject",
            email="legacy-session@example.com",
        )
        session = self.client.session
        session[AUTH_SESSION_KEY] = {
            "profile_id": profile.id,
            "cognito_sub": profile.cognito_sub,
            "expires_at": 4_000_000_000,
        }
        session.save()

        request = self.client.get(reverse("core:home")).wsgi_request
        self.assertEqual(get_authenticated_profile(request), profile)
        auth_session = self.client.session[AUTH_SESSION_KEY]
        self.assertEqual(set(auth_session), {"profile_id", "cognito_sub", "expires_at"})

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

    def test_expired_authenticated_session_loses_access(self) -> None:
        profile = UserProfile.objects.create(
            cognito_sub="expired-session-subject",
            email="expired-session@example.com",
        )
        session = self.client.session
        session[AUTH_SESSION_KEY] = {
            "profile_id": profile.id,
            "cognito_sub": profile.cognito_sub,
            "expires_at": 1,
        }
        session.save()

        response = self.client.get(reverse("accounts:account_detail"))

        self.assertEqual(response.status_code, 302)
        self.assertNotIn(AUTH_SESSION_KEY, self.client.session)

    def test_logout_clears_authentication_and_pending_state(self) -> None:
        session = self.client.session
        session[AUTH_SESSION_KEY] = {
            "profile_id": 1,
            "cognito_sub": "logout-subject",
            "expires_at": 4_000_000_000,
        }
        session[PENDING_AUTH_SESSION_KEY] = {"flow": "signin", "expires_at": 4_000_000_000}
        session.save()

        response = self.client.post(reverse("accounts:logout"))

        self.assertEqual(response.status_code, 302)
        self.assertNotIn(AUTH_SESSION_KEY, self.client.session)
        self.assertNotIn(PENDING_AUTH_SESSION_KEY, self.client.session)

    def test_hosted_callback_rejects_an_invalid_state(self) -> None:
        session = self.client.session
        session["takeboard.auth.oauth_state"] = "expected-state"
        session.save()

        response = self.client.get(reverse("accounts:oauth_callback"), {"state": "wrong-state", "code": "code"})

        self.assertEqual(response.status_code, 400)

    def test_hosted_callback_hydrates_a_minimal_session(self) -> None:
        profile = UserProfile.objects.create(
            cognito_sub="hosted-cognito-subject",
            email="hosted@example.com",
        )
        session = self.client.session
        session["takeboard.auth.oauth_state"] = "expected-state"
        session.save()
        initial_session_key = session.session_key
        tokens = CognitoTokens(
            access_token="access-token",
            id_token="id-token",
            refresh_token="refresh-token",
            expires_in=3600,
        )

        with patch("apps.accounts.views.exchange_authorization_code", return_value=tokens), patch(
            "apps.accounts.views.hydrate_profile", return_value=profile
        ):
            response = self.client.get(
                reverse("accounts:oauth_callback"),
                {"state": "expected-state", "code": "code"},
            )

        self.assertEqual(response.status_code, 302)
        auth_session = self.client.session[AUTH_SESSION_KEY]
        self.assertEqual(set(auth_session), {"profile_id", "cognito_sub", "expires_at"})
        self.assertNotEqual(self.client.session.session_key, initial_session_key)

    def test_sign_in_modal_renders_when_cognito_auth_is_enabled(self) -> None:
        response = self.client.get(reverse("core:home"))

        self.assertContains(response, 'id="auth-modal"')
        self.assertContains(response, reverse("accounts:email_start"))


class AccountHistoryTests(TestCase):
    def setUp(self) -> None:
        self.competition = Competition.objects.get(
            name="College Football", slug="college-football", sport="Football"
        )
        self.school = Entity.objects.create(
            competition=self.competition,
            name="Oklahoma",
            slug="account-oklahoma",
            short_name="Oklahoma",
            group_name="SEC",
            accent_color="#841617",
        )
        self.board = Board.objects.create(entity=self.school)
        self.profile = UserProfile.objects.create(
            cognito_sub="account-history-subject",
            email="account-history@example.com",
            display_name="AccountFan",
        )
        session = self.client.session
        session[AUTH_SESSION_KEY] = {
            "profile_id": self.profile.id,
            "cognito_sub": self.profile.cognito_sub,
            "expires_at": 4_000_000_000,
        }
        session.save()

    def test_account_history_shows_private_bid_outcome_and_charge_rollup(self) -> None:
        bid = Bid.objects.create(
            board=self.board,
            bidder=self.profile,
            represented_entity=self.school,
            message="OU OWNS THIS BOARD",
            amount_cents=1700,
            status=Bid.Status.WON,
            captured_at=timezone.now(),
        )
        self.board.current_bid = bid
        self.board.current_controller = self.profile
        self.board.current_amount_cents = bid.amount_cents
        self.board.save(update_fields=["current_bid", "current_controller", "current_amount_cents"])
        PaymentCapture.objects.create(
            bid=bid,
            stripe_payment_intent_id="pi_account_history",
            gross_amount_cents=1700,
            currency="usd",
        )
        LedgerEntry.objects.create(
            type=LedgerEntry.Type.BID_CAPTURE,
            amount_cents=1700,
            user=self.profile,
            entity=self.school,
            bid=bid,
        )
        LedgerEntry.objects.create(
            type=LedgerEntry.Type.REFUND,
            amount_cents=-500,
            user=self.profile,
            entity=self.school,
            bid=bid,
        )

        response = self.client.get(reverse("accounts:account_detail"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your moves")
        self.assertContains(response, "Active takeover")
        self.assertContains(response, "OU OWNS THIS BOARD")
        self.assertContains(response, "Captured $17.00")
        self.assertContains(response, "Refunded $5.00")
        self.assertContains(response, "TTB-")
        self.assertContains(response, "Contact us about this bid")
        self.assertContains(response, "mailto:support@taketheboard.com")
        support_url = response.context["bids"][0].support_url
        self.assertIn("%20", support_url)
        self.assertIn("%0A", support_url)
        self.assertNotIn("+", support_url)
        self.assertNotContains(response, "Available for your next move")
        self.assertNotContains(response, "18+ acknowledgement")

    def test_account_history_does_not_expose_another_users_bid(self) -> None:
        other_profile = UserProfile.objects.create(
            cognito_sub="other-history-subject",
            email="other-history@example.com",
            display_name="OtherFan",
        )
        Bid.objects.create(
            board=self.board,
            bidder=other_profile,
            represented_entity=self.school,
            message="PRIVATE OTHER MESSAGE",
            amount_cents=100,
            status=Bid.Status.PAYMENT_FAILED,
        )

        response = self.client.get(reverse("accounts:account_detail"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "PRIVATE OTHER MESSAGE")

    def test_account_history_requires_authentication(self) -> None:
        self.client.session.flush()

        response = self.client.get(reverse("accounts:account_detail"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/?next=%2Faccount%2F", response["Location"])
