"""Select and maintain the board featured on the landing page."""

from django.db.models import F
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.boards.models import Board
from apps.core.models import BoardVisit
from apps.schools.services import default_competition


def record_board_visit(*, profile: UserProfile, board: Board) -> None:
    """Increment a signed-in player's private interest signal for one board."""
    visit, created = BoardVisit.objects.get_or_create(
        profile=profile,
        board=board,
        defaults={"visit_count": 1},
    )
    if not created:
        BoardVisit.objects.filter(pk=visit.pk).update(
            visit_count=F("visit_count") + 1,
            last_visited_at=timezone.now(),
        )


def most_active_board_for(profile: UserProfile) -> Board | None:
    """Return the board a player visits most, resolving ties by recency."""
    visit = (
        BoardVisit.objects.filter(
            profile=profile,
            board__entity__competition=default_competition(),
            board__entity__active=True,
            board__bidding_enabled=True,
        )
        .select_related("board__entity", "board__current_controller")
        .order_by("-visit_count", "-last_visited_at", "board__entity__name")
        .first()
    )
    return visit.board if visit else None


def most_active_board() -> Board | None:
    """Return the active board with the highest current takeover amount."""
    return (
        Board.objects.filter(
            entity__competition=default_competition(),
            entity__active=True,
            bidding_enabled=True,
        )
        .select_related("entity", "current_controller", "current_bid__represented_entity")
        .order_by("-current_amount_cents", "-updated_at", "entity__name")
        .first()
    )
