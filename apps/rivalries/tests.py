from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import UserProfile
from apps.bidding.models import Bid
from apps.boards.models import Board, BoardTakeover
from apps.schools.models import School

from .models import Rivalry
from .services import build_rivalry_scoreboard


class RivalryScoreboardTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.alabama = School.objects.create(
            name="Alabama",
            slug="alabama",
            short_name="Alabama",
            conference="SEC",
            accent_color="#9E1B32",
        )
        cls.texas = School.objects.create(
            name="Texas",
            slug="texas",
            short_name="Texas",
            conference="SEC",
            accent_color="#BF5700",
        )
        cls.alabama_board = Board.objects.create(school=cls.alabama)
        cls.texas_board = Board.objects.create(school=cls.texas)
        cls.rivalry = Rivalry.objects.create(
            name="Alabama vs. Texas",
            slug="alabama-texas",
            school_a=cls.alabama,
            school_b=cls.texas,
        )
        cls.fan = UserProfile.objects.create(
            cognito_sub="rivalry-fan",
            email="fan@example.com",
            display_name="RivalryFan",
        )

    def create_takeover(
        self,
        *,
        board: Board,
        represented_school: School,
        amount_cents: int,
        status: str = Bid.Status.DEMO_WON,
    ) -> BoardTakeover:
        bid = Bid.objects.create(
            board=board,
            bidder=self.fan,
            represented_school=represented_school,
            message="A RIVALRY MESSAGE.",
            amount_cents=amount_cents,
            status=status,
        )
        return BoardTakeover.objects.create(
            board=board,
            bid=bid,
            controller=self.fan,
            controller_display_name=self.fan.display_name,
            represented_school=represented_school,
            message=bid.message,
            amount_cents=amount_cents,
        )

    def test_scoreboard_credits_the_backed_side_and_tracks_rival_board_attacks(self) -> None:
        self.create_takeover(
            board=self.texas_board,
            represented_school=self.alabama,
            amount_cents=1200,
        )
        self.create_takeover(
            board=self.alabama_board,
            represented_school=self.texas,
            amount_cents=800,
        )

        data = build_rivalry_scoreboard(self.rivalry)

        self.assertEqual(data["school_a"]["takeovers"], 1)
        self.assertEqual(data["school_a"]["spend_cents"], 1200)
        self.assertEqual(data["school_a"]["attacks"], 1)
        self.assertEqual(data["school_b"]["takeovers"], 1)
        self.assertEqual(data["school_b"]["spend_cents"], 800)
        self.assertEqual(data["school_b"]["attacks"], 1)
        self.assertEqual(data["leader"]["school"], self.alabama)

    def test_only_successful_moves_for_the_two_sides_count(self) -> None:
        self.create_takeover(
            board=self.alabama_board,
            represented_school=self.alabama,
            amount_cents=2000,
            status=Bid.Status.REFUNDED,
        )
        outsider = School.objects.create(
            name="Georgia",
            slug="georgia",
            short_name="Georgia",
            conference="SEC",
            accent_color="#BA0C2F",
        )
        self.create_takeover(
            board=self.texas_board,
            represented_school=outsider,
            amount_cents=3000,
        )

        data = build_rivalry_scoreboard(self.rivalry)

        self.assertEqual(data["total_takeovers"], 0)
        self.assertIsNone(data["biggest_move"])

    def test_public_rivalry_pages_show_matchup_and_board_actions(self) -> None:
        self.create_takeover(
            board=self.texas_board,
            represented_school=self.alabama,
            amount_cents=1200,
        )

        index_response = self.client.get(reverse("rivalries:index"))
        detail_response = self.client.get(
            reverse("rivalries:detail", kwargs={"slug": self.rivalry.slug})
        )

        self.assertEqual(index_response.status_code, 200)
        self.assertContains(index_response, "Alabama vs. Texas")
        self.assertContains(detail_response, "Who is taking over?")
        self.assertContains(detail_response, "Alabama")
        self.assertContains(detail_response, "Texas")
        self.assertContains(detail_response, "Back Alabama")
        self.assertContains(detail_response, "backing=alabama")
        self.assertContains(detail_response, "Recent moves")
