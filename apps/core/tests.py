from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from apps.bidding.models import Bid
from apps.bidding.services.create_bid import BidTooLowError, create_bid
from apps.bidding.services.finalize_bid import finalize_due_board
from apps.bidding.services.rules import current_board_rules
from apps.boards.models import Board, BoardTakeover
from apps.core.models import BoardVisit, GameConfig
from apps.core.services.home_hero import HERO_VARIANT_SESSION_KEY
from apps.schools.models import Competition, Entity
from apps.accounts.models import UserProfile
from apps.accounts.services.session import AUTH_SESSION_KEY
from apps.moderation.services.rate_limits import RateLimitExceeded as ModerationRateLimitExceeded
from apps.rivalries.models import Rivalry
import uuid
from apps.core.error_views import (
    bad_request,
    page_not_found,
    permission_denied,
    server_error,
)
from django.test import RequestFactory
from unittest.mock import patch

from apps.moderation.services.nova_classifier import Classification


class BoardTestCase(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        GameConfig.objects.create()
        cls.competition = Competition.objects.get(
            name="College Football",
            slug="college-football",
            sport="Football",
        )
        cls.oklahoma = Entity.objects.create(
            competition=cls.competition,
            name="Oklahoma",
            slug="oklahoma",
            short_name="Oklahoma",
            group_name="SEC",
            accent_color="#841617",
        )
        cls.texas = Entity.objects.create(
            competition=cls.competition,
            name="Texas",
            slug="texas",
            short_name="Texas",
            group_name="SEC",
            accent_color="#BF5700",
        )
        cls.board = Board.objects.create(entity=cls.oklahoma)
        cls.rivalry = Rivalry.objects.create(
            name="Red River",
            slug="red-river",
            entity_a=cls.oklahoma,
            entity_b=cls.texas,
        )


class PublicNavigationTests(BoardTestCase):
    def test_homepage_links_to_public_exploration_routes(self) -> None:
        response = self.client.get(reverse("core:home"))

        self.assertContains(response, reverse("boards:index"))
        self.assertContains(response, reverse("rivalries:index"))
        self.assertContains(response, "Oklahoma")
        self.assertNotContains(response, 'href="/admin/"')

    def test_home_hero_variant_is_session_stable_and_tracks_conversion_context(self) -> None:
        session = self.client.session
        session[HERO_VARIANT_SESSION_KEY] = "b"
        session.save()

        response = self.client.get(reverse("core:home"))

        self.assertEqual(response.context["hero_variant"]["key"], "b")
        self.assertContains(response, "Say something your rival can't ignore.", html=True)
        self.assertContains(response, 'data-analytics-hero-variant="b"')
        self.assertContains(response, 'data-analytics-event="takeover_cta_clicked"')
        self.assertContains(response, 'data-analytics-cta="take_over_this_board"')
        self.assertContains(response, 'data-analytics-target="school_name"')
        self.assertContains(response, 'data-analytics-target="message"')

    def test_signed_out_home_features_the_board_with_the_highest_current_amount(self) -> None:
        texas_board = Board.objects.create(entity=self.texas)
        self.board.current_amount_cents = 1_000
        self.board.save(update_fields=["current_amount_cents"])
        texas_board.current_amount_cents = 2_500
        texas_board.save(update_fields=["current_amount_cents"])
        profile = UserProfile.objects.create(
            cognito_sub="home-spend-subject",
            email="home-spend@example.com",
            display_name="HomeSpendFan",
        )
        oklahoma_bid = Bid.objects.create(
            board=self.board,
            bidder=profile,
            represented_entity=self.oklahoma,
            message="OKLAHOMA FIRST.",
            amount_cents=1_000,
            status=Bid.Status.WON,
        )
        texas_bid = Bid.objects.create(
            board=texas_board,
            bidder=profile,
            represented_entity=self.texas,
            message="TEXAS TAKES IT.",
            amount_cents=2_500,
            status=Bid.Status.WON,
        )
        BoardTakeover.objects.create(
            board=self.board,
            bid=oklahoma_bid,
            controller=profile,
            controller_display_name=profile.display_name,
            represented_entity=self.oklahoma,
            message=oklahoma_bid.message,
            amount_cents=oklahoma_bid.amount_cents,
        )
        BoardTakeover.objects.create(
            board=texas_board,
            bid=texas_bid,
            controller=profile,
            controller_display_name=profile.display_name,
            represented_entity=self.texas,
            message=texas_bid.message,
            amount_cents=texas_bid.amount_cents,
        )

        response = self.client.get(reverse("core:home"))

        self.assertEqual(response.context["featured_board"].pk, texas_board.pk)
        self.assertEqual(response.context["featured_reason"], "Most active right now")
        self.assertContains(response, "Take over this board")

    def test_signed_in_home_features_the_players_most_visited_board(self) -> None:
        texas_board = Board.objects.create(entity=self.texas)
        profile = UserProfile.objects.create(
            cognito_sub="home-visit-subject",
            email="home-visit@example.com",
            display_name="HomeVisitFan",
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

        self.client.get(reverse("schools:detail", kwargs={"slug": "texas"}))
        self.client.get(reverse("schools:detail", kwargs={"slug": "texas"}))
        self.client.get(reverse("schools:detail", kwargs={"slug": "oklahoma"}))
        response = self.client.get(reverse("core:home"))

        visit = BoardVisit.objects.get(profile=profile, board=texas_board)
        self.assertEqual(visit.visit_count, 2)
        self.assertEqual(response.context["featured_board"].pk, texas_board.pk)
        self.assertEqual(response.context["featured_reason"], "Most active for you")
        self.assertContains(response, "Most active for you")

    def test_public_navigation_routes_render(self) -> None:
        for url_name, kwargs in (
            ("boards:index", {}),
            ("rivalries:index", {}),
            ("leaderboard:index", {}),
            ("schools:detail", {"slug": "oklahoma"}),
            ("rivalries:detail", {"slug": "red-river"}),
        ):
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name, kwargs=kwargs))
                self.assertEqual(response.status_code, 200)

    def test_google_tag_is_rendered_only_when_configured(self) -> None:
        response = self.client.get(reverse("core:home"))
        self.assertNotContains(response, "googletagmanager.com/gtag/js")

        with override_settings(GOOGLE_ANALYTICS_MEASUREMENT_ID="G-TEST123"):
            response = self.client.get(reverse("core:home"))

        self.assertContains(response, "googletagmanager.com/gtag/js?id=G-TEST123")
        self.assertContains(response, 'gtag("config", "G-TEST123")')

    @override_settings(DEBUG=False)
    def test_public_error_pages_are_branded_and_do_not_expose_debug_details(self) -> None:
        factory = RequestFactory()
        request = factory.get("/missing-page/", HTTP_X_REQUEST_ID="test-request-123")
        request.request_id = "test-request-123"

        responses = (
            bad_request(request, ValueError("internal detail")),
            permission_denied(request, PermissionError("internal detail")),
            page_not_found(request, ValueError("internal detail")),
            server_error(request),
        )

        for response in responses:
            with self.subTest(status=response.status_code):
                self.assertIn(response.status_code, {400, 403, 404, 500})
                body = response.content.decode()
                self.assertIn("Take the Board", body)
                self.assertIn("test-request-123", body)
                self.assertNotIn("internal detail", body)
                self.assertNotIn("Traceback", body)


@override_settings(
    TAKEBOARD_DEMO_BIDDING_ENABLED=True,
    TAKEBOARD_STRIPE_ENABLED=False,
    TAKEBOARD_REQUIRE_AUTH_FOR_BIDDING=False,
    TAKEBOARD_AUTH_MODAL_PREVIEW=False,
)
class BoardMechanicsTests(BoardTestCase):
    def takeover_payload(self, **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "board_slug": "oklahoma",
            "display_name": "SoonerFan",
            "represented_entity": self.oklahoma.pk,
            "amount": "5.00",
            "message": "THE BOARD IS OURS.",
        }
        payload.update(overrides)
        return payload

    def test_school_page_renders_the_school_dropdown_and_takeover_modal(self) -> None:
        response = self.client.get(reverse("schools:detail", kwargs={"slug": "oklahoma"}))

        self.assertContains(response, 'id="bid-modal"')
        self.assertContains(response, 'name="represented_entity"')
        self.assertContains(response, "Oklahoma")
        self.assertContains(response, "Texas")
        self.assertContains(response, reverse("bidding:take"))
        self.assertContains(response, "Current message")
        self.assertContains(response, "--school-accent: #841617")
        self.assertContains(response, 'class="takeover-cta"')

    def test_rivalry_backing_query_selects_the_represented_entity(self) -> None:
        response = self.client.get(
            reverse("schools:detail", kwargs={"slug": "oklahoma"})
            + "?backing=texas"
        )

        self.assertContains(response, "<span data-school-picker-label>Texas</span>", html=True)
        self.assertContains(response, 'data-school-label="Texas"')
        self.assertContains(response, 'aria-selected="true"')
        self.assertContains(response, 'data-school-value="%s"' % self.texas.pk)

    def test_takeover_persists_board_state_and_history(self) -> None:
        response = self.client.post(
            reverse("bidding:take"),
            self.takeover_payload(message="<script>THE BOARD IS OURS.</script>"),
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 204)
        self.assertIn("HX-Redirect", response)
        self.board.refresh_from_db()
        self.assertEqual(self.board.current_amount_cents, 500)
        self.assertEqual(self.board.current_message, "<script>THE BOARD IS OURS.</script>")
        self.assertEqual(self.board.current_bid.status, Bid.Status.DEMO_WON)
        self.assertEqual(BoardTakeover.objects.filter(board=self.board).count(), 1)

        board_response = self.client.get(reverse("schools:detail", kwargs={"slug": "oklahoma"}))
        self.assertContains(board_response, "&lt;script&gt;THE BOARD IS OURS.&lt;/script&gt;")
        self.assertNotContains(board_response, "<script>THE BOARD IS OURS.</script>", html=True)

    def test_takeover_rechecks_the_current_minimum_before_writing(self) -> None:
        self.client.post(reverse("bidding:take"), self.takeover_payload())

        response = self.client.post(
            reverse("bidding:take"),
            self.takeover_payload(amount="1.00", message="TOO LOW."),
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Takeover price changed")
        self.assertContains(response, "That amount is no longer enough.")
        self.assertContains(response, "The board now requires at least $6.00.")
        self.assertNotContains(response, "The board was not changed.")
        self.assertEqual(BoardTakeover.objects.filter(board=self.board).count(), 1)

    def test_invalid_takeover_amounts_use_form_validation(self) -> None:
        for amount, expected_message in (
            ("0", "Enter a takeover amount greater than $0.00."),
            ("-1", "Enter a takeover amount greater than $0.00."),
            ("1e2", "Enter a valid takeover amount."),
            ("7.01", "Use whole dollar amounts."),
        ):
            with self.subTest(amount=amount):
                response = self.client.post(
                    reverse("bidding:take"),
                    self.takeover_payload(amount=amount),
                    HTTP_HX_REQUEST="true",
                )

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Check your bid")
                self.assertContains(response, expected_message)
                self.assertNotContains(response, "The board was not changed.")

        self.assertEqual(BoardTakeover.objects.filter(board=self.board).count(), 0)

    def test_history_snapshots_names_and_orders_newest_takeovers_first(self) -> None:
        self.client.post(
            reverse("bidding:take"),
            self.takeover_payload(display_name="FirstFan", amount="1.00", message="FIRST MOVE."),
        )
        self.board.refresh_from_db()
        self.board.guaranteed_until = timezone.now() - timedelta(seconds=1)
        self.board.save(update_fields=["guaranteed_until"])
        self.client.post(
            reverse("bidding:take"),
            self.takeover_payload(display_name="SecondFan", amount="2.00", message="SECOND MOVE."),
        )

        history = list(BoardTakeover.objects.filter(board=self.board))

        self.assertEqual([takeover.amount_cents for takeover in history], [200, 100])
        self.assertEqual(
            [takeover.controller_display_name for takeover in history],
            ["SecondFan", "FirstFan"],
        )

    def test_one_browser_can_simulate_distinct_fans_without_rewriting_the_live_controller(self) -> None:
        self.client.post(
            reverse("bidding:take"),
            self.takeover_payload(display_name="FirstFan", amount="5.00", message="FIRST MOVE."),
        )
        self.client.post(
            reverse("bidding:take"),
            self.takeover_payload(display_name="SecondFan", amount="6.00", message="SECOND MOVE."),
        )

        self.board.refresh_from_db()
        self.assertEqual(self.board.current_controller.display_name, "FirstFan")
        self.assertEqual(self.board.pending_bid.bidder.display_name, "SecondFan")

    def test_takeover_endpoint_keeps_csrf_protection(self) -> None:
        csrf_client = Client(enforce_csrf_checks=True)

        response = csrf_client.post(reverse("bidding:take"), self.takeover_payload())

        self.assertEqual(response.status_code, 403)

    def test_seed_command_is_idempotent(self) -> None:
        call_command("seed_demo_data")
        self.oklahoma.name = "Sooner State"
        self.oklahoma.save(update_fields=["name"])
        call_command("seed_demo_data")

        self.assertEqual(Entity.objects.filter(active=True).count(), 9)
        self.assertEqual(Board.objects.count(), 9)
        self.oklahoma.refresh_from_db()
        self.assertEqual(self.oklahoma.name, "Sooner State")


@override_settings(
    TAKEBOARD_DEMO_BIDDING_ENABLED=True,
    TAKEBOARD_STRIPE_ENABLED=False,
    TAKEBOARD_REQUIRE_AUTH_FOR_BIDDING=False,
    TAKEBOARD_AUTH_MODAL_PREVIEW=False,
)
class GuaranteedBidLifecycleTests(BoardTestCase):
    def submit_at(
        self,
        *,
        now,
        session_key: str,
        display_name: str,
        amount: str,
        message: str,
    ):
        return create_bid(
            board_id=self.board.id,
            session_key=session_key,
            display_name=display_name,
            represented_entity_id=self.oklahoma.id,
            amount=Decimal(amount),
            message=message,
            rules=current_board_rules(),
            now=now,
        )

    def test_only_the_highest_challenger_remains_pending_during_the_guarantee(self) -> None:
        published_at = timezone.now()
        first = self.submit_at(
            now=published_at,
            session_key="first-session",
            display_name="FirstFan",
            amount="50.00",
            message="FIRST MESSAGE.",
        )
        second = self.submit_at(
            now=published_at + timedelta(seconds=10),
            session_key="second-session",
            display_name="SecondFan",
            amount="55.00",
            message="SECOND MESSAGE.",
        )
        third = self.submit_at(
            now=published_at + timedelta(seconds=15),
            session_key="third-session",
            display_name="ThirdFan",
            amount="60.00",
            message="THIRD MESSAGE.",
        )

        self.board.refresh_from_db()
        self.assertTrue(first.published)
        self.assertFalse(second.published)
        self.assertFalse(third.published)
        self.assertEqual(self.board.current_bid_id, first.bid_id)
        self.assertEqual(self.board.current_amount_cents, 5000)
        self.assertEqual(self.board.pending_bid_id, third.bid_id)
        self.assertEqual(self.board.guaranteed_until, published_at + timedelta(seconds=30))
        self.assertEqual(Bid.objects.get(pk=second.bid_id).status, Bid.Status.AUTH_CANCELED)
        self.assertEqual(Bid.objects.get(pk=third.bid_id).status, Bid.Status.AUTHORIZED)
        self.assertEqual(BoardTakeover.objects.filter(board=self.board).count(), 1)


    def test_minimum_uses_the_pending_challenger_not_just_the_live_bid(self) -> None:
        published_at = timezone.now()
        self.submit_at(
            now=published_at,
            session_key="first-session",
            display_name="FirstFan",
            amount="50.00",
            message="FIRST MESSAGE.",
        )
        self.submit_at(
            now=published_at + timedelta(seconds=10),
            session_key="second-session",
            display_name="SecondFan",
            amount="60.00",
            message="SECOND MESSAGE.",
        )

        with self.assertRaises(BidTooLowError) as context:
            self.submit_at(
                now=published_at + timedelta(seconds=12),
                session_key="third-session",
                display_name="ThirdFan",
                amount="60.00",
                message="TOO LOW.",
            )

        self.assertEqual(context.exception.required_cents, 6100)

    def test_school_page_displays_the_guarantee_pending_challenger_and_effective_minimum(self) -> None:
        published_at = timezone.now()
        self.submit_at(
            now=published_at,
            session_key="first-session",
            display_name="FirstFan",
            amount="50.00",
            message="FIRST MESSAGE.",
        )
        self.submit_at(
            now=published_at + timedelta(seconds=10),
            session_key="second-session",
            display_name="SecondFan",
            amount="60.00",
            message="SECOND MESSAGE.",
        )

        response = self.client.get(reverse("schools:detail", kwargs={"slug": "oklahoma"}))

        self.assertContains(response, "Current board")
        self.assertContains(response, "Next up")
        self.assertContains(response, "$60.00")
        self.assertContains(response, "Minimum $61.00")

    def test_due_pending_challenger_publishes_and_starts_a_new_guarantee(self) -> None:
        published_at = timezone.now()
        first = self.submit_at(
            now=published_at,
            session_key="first-session",
            display_name="FirstFan",
            amount="50.00",
            message="FIRST MESSAGE.",
        )
        pending = self.submit_at(
            now=published_at + timedelta(seconds=10),
            session_key="second-session",
            display_name="SecondFan",
            amount="60.00",
            message="SECOND MESSAGE.",
        )
        result = finalize_due_board(
            board_id=self.board.id,
            rules=current_board_rules(),
            now=published_at + timedelta(seconds=30),
        )

        self.board.refresh_from_db()
        self.assertTrue(result.published)
        self.assertEqual(self.board.current_bid_id, pending.bid_id)
        self.assertEqual(self.board.current_amount_cents, 6000)
        self.assertIsNone(self.board.pending_bid_id)
        self.assertEqual(self.board.guaranteed_until, published_at + timedelta(seconds=60))
        self.assertEqual(Bid.objects.get(pk=first.bid_id).status, Bid.Status.DEMO_WON)
        self.assertEqual(Bid.objects.get(pk=pending.bid_id).status, Bid.Status.DEMO_WON)
        self.assertEqual(BoardTakeover.objects.filter(board=self.board).count(), 2)

    def test_failed_pending_capture_keeps_the_current_controller_live(self) -> None:
        published_at = timezone.now()
        first = self.submit_at(
            now=published_at,
            session_key="first-session",
            display_name="FirstFan",
            amount="50.00",
            message="FIRST MESSAGE.",
        )
        pending = self.submit_at(
            now=published_at + timedelta(seconds=10),
            session_key="second-session",
            display_name="SecondFan",
            amount="60.00",
            message="SECOND MESSAGE.",
        )
        result = finalize_due_board(
            board_id=self.board.id,
            rules=current_board_rules(),
            now=published_at + timedelta(seconds=30),
            capture_pending_bid=lambda bid: False,
        )

        self.board.refresh_from_db()
        self.assertFalse(result.published)
        self.assertEqual(self.board.current_bid_id, first.bid_id)
        self.assertIsNone(self.board.pending_bid_id)
        self.assertEqual(Bid.objects.get(pk=pending.bid_id).status, Bid.Status.PAYMENT_FAILED)
        self.assertEqual(BoardTakeover.objects.filter(board=self.board).count(), 1)


@override_settings(
    TAKEBOARD_DEMO_BIDDING_ENABLED=True,
    TAKEBOARD_STRIPE_ENABLED=False,
    TAKEBOARD_REQUIRE_AUTH_FOR_BIDDING=True,
    TAKEBOARD_AUTH_MODAL_PREVIEW=False,
)
class AuthenticatedBiddingTests(BoardTestCase):
    def test_message_rate_limit_is_explained_in_the_bid_result(self) -> None:
        profile = UserProfile.objects.create(
            cognito_sub="rate-limited-bid-subject",
            email="rate-limited-bid@example.com",
            display_name="RateLimitedBidder",
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
            "apps.bidding.views.validate_message",
            side_effect=ModerationRateLimitExceeded,
        ):
            response = self.client.post(
                reverse("bidding:take"),
                {
                    "board_slug": "oklahoma",
                    "display_name": "NotTheAuthenticatedName",
                    "represented_entity": self.oklahoma.pk,
                    "amount": "5.00",
                    "message": "THE BOARD IS OURS.",
                },
                HTTP_HX_REQUEST="true",
            )

        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "Rate limit reached", status_code=429)
        self.assertContains(response, "reached the limit", status_code=429)

    def test_authenticated_session_is_used_for_a_takeover(self) -> None:
        profile = UserProfile.objects.create(
            cognito_sub=uuid.uuid4(),
            email="fan@example.com",
            display_name="AuthenticatedFan",
        )
        session = self.client.session
        session[AUTH_SESSION_KEY] = {
            "profile_id": profile.id,
            "cognito_sub": str(profile.cognito_sub),
            "access_token": "access-token",
            "id_token": "id-token",
            "refresh_token": "refresh-token",
            "expires_at": 4_000_000_000,
        }
        session.save()

        with patch(
            "apps.moderation.services.validation.classify_message",
            return_value=Classification("allow", "safe", 0.99),
        ):
            response = self.client.post(
                reverse("bidding:take"),
                {
                    "board_slug": "oklahoma",
                    "display_name": "NotTheAuthenticatedName",
                    "represented_entity": self.oklahoma.pk,
                    "amount": "5.00",
                    "message": "THE BOARD IS OURS.",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.board.refresh_from_db()
        self.assertEqual(self.board.current_controller_id, profile.id)
        profile.refresh_from_db()
        self.assertEqual(profile.display_name, "AuthenticatedFan")

    def test_authenticated_bid_modal_uses_the_saved_board_name(self) -> None:
        profile = UserProfile.objects.create(
            cognito_sub="authenticated-cognito-subject",
            email="fan@example.com",
            display_name="AuthenticatedFan",
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

        response = self.client.get(reverse("schools:detail", kwargs={"slug": "oklahoma"}))

        self.assertNotContains(response, 'name="display_name"')

    def test_guest_cannot_take_the_board_when_auth_is_required(self) -> None:
        response = self.client.post(
            reverse("bidding:take"),
            {
                "board_slug": "oklahoma",
                "display_name": "GuestFan",
                "represented_entity": self.oklahoma.pk,
                "amount": "5.00",
                "message": "THE BOARD IS OURS.",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sign in to take the board.")
