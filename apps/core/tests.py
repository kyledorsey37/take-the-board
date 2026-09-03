from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from urllib.parse import parse_qs, urlparse
from datetime import timedelta
from decimal import Decimal
import os
from pathlib import Path

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
from apps.leaderboard.models import CompetitionPeriod
import uuid
from apps.core.error_views import (
    bad_request,
    page_not_found,
    permission_denied,
    server_error,
)
from io import BytesIO
from unittest.mock import patch

from django.test import RequestFactory
from PIL import Image

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


class ProductionRosterCommandTests(TestCase):
    @patch.dict(os.environ, {"TAKEBOARD_ENVIRONMENT": "production"})
    def test_production_roster_is_idempotent(self) -> None:
        call_command("seed_production_roster")
        call_command("seed_production_roster")

        self.assertEqual(Entity.objects.filter(active=True).count(), 9)
        self.assertEqual(Board.objects.count(), 9)
        self.assertEqual(Rivalry.objects.filter(active=True).count(), 3)


class PublicNavigationTests(BoardTestCase):
    def test_homepage_links_to_public_exploration_routes(self) -> None:
        response = self.client.get(reverse("core:home"))

        self.assertContains(response, reverse("boards:index"))
        self.assertContains(response, reverse("rivalries:index"))
        self.assertContains(response, reverse("core:how_it_works"))
        self.assertContains(response, "Oklahoma")
        self.assertNotContains(response, 'href="/admin/"')

    def test_home_board_preview_uses_directory_card_contract(self) -> None:
        response = self.client.get(reverse("core:home"))

        self.assertContains(response, "board-directory-card")
        self.assertContains(response, "board-card-school")
        self.assertContains(response, 'style="--board-accent: #841617;"')
        self.assertContains(response, 'data-analytics-surface="home_board_preview"')
        self.assertContains(response, "Open board")

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
            ("core:how_it_works", {}),
            ("schools:detail", {"slug": "oklahoma"}),
            ("rivalries:detail", {"slug": "red-river"}),
        ):
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name, kwargs=kwargs))
                self.assertEqual(response.status_code, 200)

    def test_public_policy_and_support_pages_render_and_are_linked(self) -> None:
        pages = (
            ("core:privacy", "Privacy Policy"),
            ("core:terms", "Terms of Service"),
            ("core:refunds", "Refunds and Payment Policy"),
            ("core:community_guidelines", "Community Guidelines"),
            ("core:contact", "Contact us"),
        )

        for url_name, heading in pages:
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, heading)
                self.assertNotContains(response, "Draft for legal review")
                self.assertNotContains(response, "counsel")

        terms = self.client.get(reverse("core:terms"))
        self.assertContains(terms, "You must be 18 or older to place bids")
        self.assertContains(terms, "The game week runs Sunday-to-Sunday")

        privacy = self.client.get(reverse("core:privacy"))
        self.assertContains(privacy, "an internal account identifier used to recognize your account")
        self.assertNotContains(privacy, "Cognito account identifier")
        self.assertContains(privacy, "Public board messages, board names, and takeover history may remain part of the public game record.")
        self.assertNotContains(privacy, "operator's documented retention schedule")

        home = self.client.get(reverse("core:home"))
        self.assertContains(home, reverse("core:privacy"))
        self.assertContains(home, reverse("core:terms"))
        self.assertContains(home, reverse("core:refunds"))
        self.assertContains(home, reverse("core:community_guidelines"))
        self.assertContains(home, reverse("core:contact"))

    def test_how_it_works_page_explains_the_public_takeover_loop(self) -> None:
        response = self.client.get(reverse("core:how_it_works"))

        self.assertContains(response, "Highest bid. Loudest message.")
        self.assertContains(response, "Find. Bid. Take the board.")
        self.assertContains(response, "The board moves when the payment settles.")
        self.assertContains(response, "Rivalry is the point. Crossing the line is not.")
        self.assertContains(response, "guaranteed to stay on the board for at least 30 seconds")
        self.assertContains(response, "Every Sunday, a new fight.")
        self.assertNotContains(response, "There is no guaranteed display duration.")
        self.assertContains(response, reverse("boards:index"))

    @override_settings(
        TAKEBOARD_DEMO_BIDDING_ENABLED=True,
        TAKEBOARD_STRIPE_ENABLED=False,
        TAKEBOARD_REQUIRE_AUTH_FOR_BIDDING=False,
        TAKEBOARD_AUTH_MODAL_PREVIEW=False,
    )
    def test_school_board_has_share_button_and_social_card_metadata(self) -> None:
        response = self.client.get(reverse("schools:detail", kwargs={"slug": "oklahoma"}))

        self.assertLess(
            response.content.find(b'class="round-status-rail'),
            response.content.find(b'class="live-board"'),
        )
        self.assertContains(response, 'data-share-board')
        self.assertContains(response, 'data-analytics-event="board_share_clicked"')
        self.assertContains(response, 'data-share-url="http://testserver/schools/oklahoma/"')
        self.assertContains(
            response,
            'data-share-text="See the Oklahoma board: THIS BOARD IS OPEN."',
        )
        self.assertContains(response, 'data-share-x')
        self.assertContains(response, "Share on X")
        self.assertContains(response, 'target="_blank"')
        self.assertContains(response, 'rel="noopener noreferrer"')
        self.assertContains(response, "(opens in a new tab)")
        x_share_url = response.context["x_share_url"]
        parsed_x_share_url = urlparse(x_share_url)
        self.assertEqual(parsed_x_share_url.scheme, "https")
        self.assertEqual(parsed_x_share_url.netloc, "x.com")
        self.assertEqual(parsed_x_share_url.path, "/intent/post")
        self.assertEqual(
            parse_qs(parsed_x_share_url.query),
            {
                "text": ["See the Oklahoma board on Take the Board."],
                "url": [response.context["board_url"]],
            },
        )
        self.assertContains(
            response,
            'href="' + x_share_url.replace("&", "&amp;") + '"',
        )
        self.assertEqual(response.content.count(b'class="round-status-rail"'), 1)
        self.assertContains(response, "data-round-status")
        self.assertContains(response, "data-round-reset-at=")
        self.assertContains(response, 'data-open-dialog="round-help-dialog"')
        self.assertContains(response, 'data-analytics-event="round_help_opened"')
        self.assertContains(response, f"Week {response.context['current_week_number']}")
        self.assertContains(response, "How weekly resets work")
        self.assertContains(
            response,
            "Each college football week starts fresh. Boards reset after the week's games, while takeover history remains part of the record. Your message stays live until another fan takes the board, it is removed for a policy violation, or the weekly reset occurs.",
        )
        self.assertNotContains(response, "How rounds work")
        self.assertNotContains(response, "Current game round")
        self.assertNotContains(response, "weekly-reset-note")
        self.assertContains(response, 'data-analytics-modal-id="bid"')
        self.assertContains(response, 'name="twitter:card" content="summary_large_image"')
        self.assertContains(response, 'property="og:title" content="Oklahoma board: “THIS BOARD IS OPEN.” | Take the Board"')
        self.assertContains(response, 'property="og:image:width" content="1200"')
        self.assertContains(
            response,
            reverse("boards:social_image", kwargs={"slug": "oklahoma"}) + "?v=0",
        )

    def test_board_x_share_reuses_the_existing_low_cardinality_analytics_contract(self) -> None:
        app_js = (Path(__file__).resolve().parents[2] / "static/js/app.js").read_text()
        x_share_handler = app_js[
            app_js.index('function trackXBoardShare') : app_js.index(
                "async function copyTextToClipboard"
            )
        ]

        self.assertIn('event.target.closest("[data-share-x]")', x_share_handler)
        self.assertIn('window.takeTheBoard.trackEvent("board_share_result"', x_share_handler)
        self.assertIn('result: "shared"', x_share_handler)
        self.assertIn('share_method: "x_twitter"', x_share_handler)
        self.assertNotIn("shareText", x_share_handler)
        self.assertNotIn("shareUrl", x_share_handler)

    def test_stale_pending_marker_does_not_override_a_published_board(self) -> None:
        profile = UserProfile.objects.create(
            cognito_sub="stale-pending-marker-fan",
            email="stale-pending-marker@example.com",
            display_name="PublishedFan",
        )
        bid = Bid.objects.create(
            board=self.board,
            bidder=profile,
            represented_entity=self.oklahoma,
            message="LIVE MESSAGE.",
            amount_cents=500,
            status=Bid.Status.WON,
        )
        self.board.current_bid = bid
        self.board.current_controller = profile
        self.board.current_amount_cents = bid.amount_cents
        self.board.current_message = bid.message
        self.board.save(
            update_fields=[
                "current_bid",
                "current_controller",
                "current_amount_cents",
                "current_message",
                "updated_at",
            ]
        )

        response = self.client.get(
            reverse("schools:detail", kwargs={"slug": "oklahoma"}),
            {"move": "pending"},
        )

        self.assertContains(response, "LIVE MESSAGE.")
        self.assertNotContains(response, "You're up next. Your message will appear shortly.")

    def test_school_board_groups_takeover_history_by_week(self) -> None:
        now = timezone.now()
        current_period = CompetitionPeriod.objects.create(
            competition=self.competition,
            year=2026,
            week_number=35,
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=6),
            active=True,
        )
        previous_period = CompetitionPeriod.objects.create(
            competition=self.competition,
            year=2026,
            week_number=34,
            starts_at=now - timedelta(days=8),
            ends_at=now - timedelta(days=1),
            active=False,
        )
        profile = UserProfile.objects.create(
            cognito_sub="history-grouping-fan",
            email="history-grouping@example.com",
            display_name="HistoryFan",
        )
        for period, message, occurred_at in (
            (current_period, "CURRENT WEEK MOVE.", now - timedelta(hours=1)),
            (previous_period, "PREVIOUS WEEK MOVE.", now - timedelta(days=2)),
        ):
            bid = Bid.objects.create(
                board=self.board,
                bidder=profile,
                represented_entity=self.oklahoma,
                period=period,
                message=message,
                amount_cents=100,
                status=Bid.Status.DEMO_WON,
            )
            takeover = BoardTakeover.objects.create(
                board=self.board,
                bid=bid,
                controller=profile,
                controller_display_name=profile.display_name,
                represented_entity=self.oklahoma,
                period=period,
                message=message,
                amount_cents=100,
            )
            BoardTakeover.objects.filter(pk=takeover.pk).update(occurred_at=occurred_at)

        response = self.client.get(reverse("schools:detail", kwargs={"slug": "oklahoma"}))
        body = response.content.decode()

        self.assertIn('<details class="takeover-week takeover-week-current" open>', body)
        self.assertIn('<details class="takeover-week">', body)
        self.assertLess(
            body.find('<details class="takeover-week takeover-week-current" open>'),
            body.find('<details class="takeover-week">'),
        )
        self.assertContains(response, "CURRENT WEEK MOVE.")
        self.assertContains(response, "PREVIOUS WEEK MOVE.")
        self.assertContains(response, 'data-analytics-event="takeover_history_week_toggled"')

    def test_board_social_image_is_a_large_png(self) -> None:
        response = self.client.get(reverse("boards:social_image", kwargs={"slug": "oklahoma"}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        with Image.open(BytesIO(response.content)) as image:
            self.assertEqual(image.size, (1200, 630))

    @override_settings(TAKEBOARD_ANALYTICS_CONSENT_PREVIEW=False)
    def test_google_tag_is_rendered_only_when_configured(self) -> None:
        response = self.client.get(reverse("core:home"))
        self.assertNotContains(response, "googletagmanager.com/gtag/js")
        self.assertNotContains(response, 'data-analytics-consent-choice="accepted"')
        self.assertNotContains(response, "Cookie settings")

        with override_settings(GOOGLE_ANALYTICS_MEASUREMENT_ID="G-TEST123"):
            response = self.client.get(reverse("core:home"))
            self.assertNotContains(response, "googletagmanager.com/gtag/js")
            self.assertContains(response, 'data-analytics-consent-choice="accepted"')
            self.assertContains(response, 'data-analytics-consent-choice="declined"')
            self.assertContains(response, "Cookie settings")

            self.client.cookies["ttb_analytics_consent"] = "accepted"
            response = self.client.get(reverse("core:home"))

        self.assertContains(response, "googletagmanager.com/gtag/js?id=G-TEST123")
        self.assertContains(response, 'gtag("config", "G-TEST123")')
        self.assertContains(response, 'analytics_storage": "granted"')
        self.assertContains(response, 'id="analytics-consent-banner"')
        self.assertEqual(response.context["analytics_consent"], "accepted")

    def test_declined_analytics_hides_banner_without_loading_tag(self) -> None:
        self.client.cookies["ttb_analytics_consent"] = "declined"

        with override_settings(GOOGLE_ANALYTICS_MEASUREMENT_ID="G-TEST123"):
            response = self.client.get(reverse("core:home"))

        self.assertNotContains(response, "googletagmanager.com/gtag/js")
        self.assertContains(response, 'id="analytics-consent-banner"')
        self.assertEqual(response.context["analytics_consent"], "declined")

    @override_settings(TAKEBOARD_ANALYTICS_CONSENT_PREVIEW=True)
    def test_analytics_consent_can_be_previewed_without_a_measurement_id(self) -> None:
        response = self.client.get(reverse("core:home"))

        self.assertContains(response, 'id="analytics-consent-banner"')
        self.assertContains(response, 'data-analytics-consent-choice="accepted"')
        self.assertContains(response, 'class="analytics-consent-title-compact">Cookies</span>')
        self.assertContains(response, 'class="analytics-consent-description-compact"')
        self.assertNotContains(response, "googletagmanager.com/gtag/js")

    def test_public_pages_expose_discovery_and_modal_funnel_events(self) -> None:
        boards = self.client.get(reverse("boards:index"))
        how_it_works = self.client.get(reverse("core:how_it_works"))
        now = timezone.now()
        CompetitionPeriod.objects.create(
            competition=self.competition,
            year=2026,
            week_number=1,
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=6),
            active=True,
        )
        leaderboard = self.client.get(reverse("leaderboard:index"))
        rivalry = self.client.get(reverse("rivalries:detail", kwargs={"slug": "red-river"}))

        self.assertContains(boards, 'data-analytics-event="board_opened"')
        self.assertEqual(boards.content.count(b'class="round-status-rail"'), 1)
        self.assertContains(boards, "board-directory-card")
        self.assertContains(boards, "board-card-school")
        self.assertContains(boards, 'style="--board-accent: #841617;"')
        self.assertContains(boards, 'aria-label="View Oklahoma board, currently open"')
        self.assertContains(how_it_works, 'data-faq-id="display_duration"')
        self.assertNotContains(how_it_works, "round-status-rail")
        self.assertContains(leaderboard, 'data-analytics-event="standings_period_changed"')
        self.assertEqual(leaderboard.content.count(b'class="round-status-rail"'), 1)
        self.assertContains(rivalry, 'data-analytics-event="rivalry_period_changed"')
        self.assertEqual(rivalry.content.count(b'class="round-status-rail"'), 1)

    def test_round_status_rail_is_absent_from_utility_and_legal_pages(self) -> None:
        for route_name in ("core:home", "core:how_it_works", "core:terms", "core:privacy"):
            response = self.client.get(reverse(route_name))
            self.assertNotContains(response, "round-status-rail")

    def test_board_directory_preserves_a_long_board_message(self) -> None:
        long_message = "THIS BOARD MESSAGE IS LONG ENOUGH TO WRAP ACROSS MORE THAN ONE LINE."
        self.board.current_message = long_message
        self.board.save(update_fields=["current_message"])

        response = self.client.get(reverse("boards:index"))

        self.assertContains(response, long_message)
        self.assertContains(response, 'aria-label="View Oklahoma board, currently open"')

    def test_board_directory_labels_an_occupied_card(self) -> None:
        profile = UserProfile.objects.create(
            cognito_sub="directory-card-holder",
            email="directory-card-holder@example.com",
            display_name="CardHolder",
        )
        self.board.current_controller = profile
        self.board.current_amount_cents = 700
        self.board.save(update_fields=["current_controller", "current_amount_cents"])

        response = self.client.get(reverse("boards:index"))

        self.assertContains(
            response,
            'aria-label="View Oklahoma board, held by CardHolder for $7.00"',
        )

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
