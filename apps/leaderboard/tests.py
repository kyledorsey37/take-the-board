from datetime import datetime, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.bidding.models import Bid
from apps.boards.models import Board, BoardTakeover
from apps.schools.models import Competition, Entity

from apps.boards.services.reset_boards import reset_boards

from .models import EntityPeriodStats, CompetitionPeriod
from .services import build_leaderboard
from .week_services import current_period_window, weekly_reset_schedule


class LeaderboardTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.competition = Competition.objects.get(
            name="College Football", slug="college-football", sport="Football"
        )
        cls.sec_school = Entity.objects.create(
            competition=cls.competition,
            name="Alabama",
            slug="alabama",
            short_name="Alabama",
            group_name="SEC",
            accent_color="#9E1B32",
        )
        cls.big_ten_school = Entity.objects.create(
            competition=cls.competition,
            name="Michigan",
            slug="michigan",
            short_name="Michigan",
            group_name="Big Ten",
            accent_color="#00274C",
        )
        cls.board = Board.objects.create(entity=cls.sec_school)
        cls.other_board = Board.objects.create(entity=cls.big_ten_school)
        cls.first_fan = UserProfile.objects.create(
            cognito_sub="fan-one",
            email="one@example.com",
            display_name="FirstFan",
        )
        cls.second_fan = UserProfile.objects.create(
            cognito_sub="fan-two",
            email="two@example.com",
            display_name="SecondFan",
        )

    def create_takeover(
        self,
        *,
        bidder: UserProfile,
        board: Board,
        represented_entity: Entity,
        amount_cents: int,
        occurred_at=None,
        status: str = Bid.Status.DEMO_WON,
    ) -> BoardTakeover:
        bid = Bid.objects.create(
            board=board,
            bidder=bidder,
            represented_entity=represented_entity,
            message="A TAKEOVER MESSAGE.",
            amount_cents=amount_cents,
            status=status,
        )
        takeover = BoardTakeover.objects.create(
            board=board,
            bid=bid,
            controller=bidder,
            controller_display_name=bidder.display_name,
            represented_entity=represented_entity,
            message=bid.message,
            amount_cents=amount_cents,
        )
        if occurred_at is not None:
            BoardTakeover.objects.filter(pk=takeover.pk).update(occurred_at=occurred_at)
            takeover.refresh_from_db()
        return takeover

    def test_leaderboard_credits_fanbase_and_conference_by_represented_entity(self) -> None:
        self.create_takeover(
            bidder=self.first_fan,
            board=self.board,
            represented_entity=self.sec_school,
            amount_cents=1200,
        )
        self.create_takeover(
            bidder=self.first_fan,
            board=self.other_board,
            represented_entity=self.big_ten_school,
            amount_cents=800,
        )

        data = build_leaderboard()

        self.assertEqual(data["fanbase_rows"][0]["school_name"], "Alabama")
        self.assertEqual(data["fanbase_rows"][0]["total_spend_cents"], 1200)
        self.assertEqual(data["conference_rows"][0]["conference"], "SEC")
        self.assertEqual(data["spender_rows"][0]["display_name"], "FirstFan")
        self.assertEqual(data["attacked_rows"][0]["school_name"], "Alabama")

    def test_week_period_uses_active_period(self) -> None:
        now = timezone.now()
        CompetitionPeriod.objects.create(
            competition=self.competition,
            year=now.year,
            week_number=1,
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=6),
            active=True,
        )
        self.create_takeover(
            bidder=self.first_fan,
            board=self.board,
            represented_entity=self.sec_school,
            amount_cents=900,
            occurred_at=now - timedelta(hours=1),
        )
        self.create_takeover(
            bidder=self.second_fan,
            board=self.other_board,
            represented_entity=self.big_ten_school,
            amount_cents=700,
            occurred_at=now - timedelta(days=3),
        )

        data = build_leaderboard("week")

        self.assertEqual(data["period"], "week")
        self.assertEqual(data["summary"]["total_spend_cents"], 900)

    def test_public_reset_schedule_uses_the_active_period_deadline(self) -> None:
        now = timezone.make_aware(datetime(2026, 8, 27, 12, 0, 0))
        period = CompetitionPeriod.objects.create(
            competition=self.competition,
            year=2026,
            week_number=34,
            starts_at=now - timedelta(days=4),
            ends_at=now + timedelta(days=3, hours=11, minutes=59),
            active=True,
        )

        schedule = weekly_reset_schedule(competition=self.competition, now=now)

        self.assertEqual(schedule.server_now, now)
        self.assertEqual(schedule.reset_at, period.ends_at)
        self.assertFalse(schedule.is_due)
        self.assertEqual(schedule.week_number, 34)

    def test_public_reset_schedule_marks_a_late_reset_as_due(self) -> None:
        now = timezone.make_aware(datetime(2026, 8, 31, 12, 0, 0))
        period = CompetitionPeriod.objects.create(
            competition=self.competition,
            year=2026,
            week_number=35,
            starts_at=now - timedelta(days=7),
            ends_at=now - timedelta(hours=12),
            active=True,
        )

        schedule = weekly_reset_schedule(competition=self.competition, now=now)

        self.assertEqual(schedule.reset_at, period.ends_at)
        self.assertTrue(schedule.is_due)
        self.assertEqual(schedule.week_number, 35)

    def test_refunded_takeovers_do_not_count_in_public_standings(self) -> None:
        self.create_takeover(
            bidder=self.first_fan,
            board=self.board,
            represented_entity=self.sec_school,
            amount_cents=1200,
        )
        self.create_takeover(
            bidder=self.second_fan,
            board=self.other_board,
            represented_entity=self.big_ten_school,
            amount_cents=5000,
            status=Bid.Status.REFUNDED,
        )

        data = build_leaderboard()

        self.assertEqual(data["summary"]["total_spend_cents"], 1200)
        self.assertEqual(data["fanbase_rows"][0]["school_name"], "Alabama")

    def test_public_leaderboard_renders_the_standings_sections(self) -> None:
        self.create_takeover(
            bidder=self.first_fan,
            board=self.board,
            represented_entity=self.sec_school,
            amount_cents=1200,
        )

        response = self.client.get(reverse("leaderboard:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Top schools by backing")
        self.assertContains(response, "Conference showdown")
        self.assertContains(response, "Top spenders")
        self.assertContains(response, "SEC")
        self.assertContains(response, "FirstFan")
        self.assertContains(response, "$12.00")
        self.assertEqual(response.content.count(b'class="round-status-rail"'), 1)
        self.assertContains(response, 'data-analytics-surface="standings"')
        self.assertNotContains(response, "weekly-reset-note")

    def test_week_marker_uses_the_iso_week_year(self) -> None:
        new_year_boundary = timezone.make_aware(datetime(2026, 1, 4, 23, 59, 1))

        window = current_period_window(new_year_boundary)

        self.assertEqual(window.year, 2026)
        self.assertEqual(window.week_number, 1)

    def test_weekly_reset_preserves_history_rebuilds_stats_and_clears_live_boards(self) -> None:
        reset_at = timezone.make_aware(datetime(2026, 8, 30, 23, 59, 1))
        previous_window = current_period_window(reset_at - timedelta(minutes=2))
        previous_week = CompetitionPeriod.objects.create(
            competition=self.competition,
            year=previous_window.year,
            week_number=previous_window.week_number,
            starts_at=previous_window.starts_at,
            ends_at=previous_window.ends_at,
            active=True,
        )
        current_bid = Bid.objects.create(
            board=self.board,
            bidder=self.first_fan,
            represented_entity=self.sec_school,
            period=previous_week,
            message="LAST WEEK'S MESSAGE.",
            amount_cents=1200,
            status=Bid.Status.DEMO_WON,
        )
        takeover = BoardTakeover.objects.create(
            board=self.board,
            bid=current_bid,
            controller=self.first_fan,
            controller_display_name=self.first_fan.display_name,
            represented_entity=self.sec_school,
            period=previous_week,
            message=current_bid.message,
            amount_cents=current_bid.amount_cents,
        )
        BoardTakeover.objects.filter(pk=takeover.pk).update(
            occurred_at=previous_window.starts_at + timedelta(days=1)
        )
        pending_bid = Bid.objects.create(
            board=self.board,
            bidder=self.second_fan,
            represented_entity=self.sec_school,
            period=previous_week,
            message="PENDING MESSAGE.",
            amount_cents=1300,
            status=Bid.Status.AUTHORIZED,
        )
        self.board.current_bid = current_bid
        self.board.current_controller = self.first_fan
        self.board.current_amount_cents = 1200
        self.board.current_message = current_bid.message
        self.board.pending_bid = pending_bid
        self.board.guaranteed_until = reset_at + timedelta(seconds=30)
        self.board.version = 4
        self.board.save()

        result = reset_boards(competition=self.competition, now=reset_at)

        self.board.refresh_from_db()
        current_bid.refresh_from_db()
        pending_bid.refresh_from_db()
        previous_week.refresh_from_db()
        next_week = CompetitionPeriod.objects.get(competition=self.competition, active=True)
        previous_stats = EntityPeriodStats.objects.get(entity=self.sec_school, period=previous_week)

        self.assertFalse(result.already_reset)
        self.assertEqual(result.boards_reset, 2)
        self.assertEqual(next_week.week_number, current_period_window(reset_at).week_number)
        self.assertNotEqual(next_week.pk, previous_week.pk)
        self.assertIsNotNone(next_week.reset_completed_at)
        self.assertFalse(previous_week.active)
        self.assertIsNone(self.board.current_bid_id)
        self.assertIsNone(self.board.current_controller_id)
        self.assertEqual(self.board.current_amount_cents, 0)
        self.assertEqual(self.board.current_message, "THIS BOARD IS OPEN.")
        self.assertIsNone(self.board.pending_bid_id)
        self.assertIsNone(self.board.guaranteed_until)
        self.assertEqual(self.board.version, 5)
        self.assertEqual(current_bid.status, Bid.Status.DEMO_WON)
        self.assertEqual(pending_bid.status, Bid.Status.AUTH_CANCELED)
        self.assertTrue(BoardTakeover.objects.filter(pk=takeover.pk).exists())
        self.assertEqual(previous_stats.total_spend_cents, 1200)
        self.assertEqual(previous_stats.takeovers, 1)
        self.assertEqual(result.stats_rows, 2)

        version_after_reset = self.board.version
        second_result = reset_boards(competition=self.competition, now=reset_at + timedelta(minutes=1))

        self.board.refresh_from_db()
        self.assertTrue(second_result.already_reset)
        self.assertEqual(self.board.version, version_after_reset)
