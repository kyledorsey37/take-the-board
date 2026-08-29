"""Local free-play implementation of the protected-board bidding rules."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import uuid
from datetime import datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.bidding.models import Bid
from apps.boards.models import Board
from apps.boards.services.publish_takeover import publish_takeover
from apps.core.models import Activity
from apps.leaderboard.week_services import get_or_create_current_season_week
from apps.schools.models import School

from .finalize_bid import finalize_locked_pending_bid
from .rules import BoardRules, minimum_takeover_cents


class TakeoverError(Exception):
    """A user-facing failure while applying a local free-play takeover."""


class BidTooLowError(TakeoverError):
    def __init__(self, required_cents: int) -> None:
        self.required_cents = required_cents
        super().__init__(
            f"That amount is no longer enough. The board now requires at least ${required_cents / 100:.2f}."
        )


def dollars_to_cents(amount: Decimal) -> int:
    if amount != amount.to_integral_value():
        raise TakeoverError("Use whole dollar amounts.")
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def demo_subject_for_session(session_key: str, display_name: str) -> uuid.UUID:
    normalized_display_name = display_name.casefold()
    return uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"take-the-board-local-demo:{session_key}:{normalized_display_name}",
    )


def demo_player_for_session(
    *,
    session_key: str,
    display_name: str,
    favorite_school: School,
) -> UserProfile:
    subject = demo_subject_for_session(session_key, display_name)
    try:
        profile, created = UserProfile.objects.get_or_create(
            cognito_sub=subject,
            defaults={
                "email": f"demo-{subject}@example.invalid",
                "display_name": display_name,
                "favorite_school": favorite_school,
            },
        )
    except IntegrityError as error:
        raise TakeoverError("That display name is already in use in this local game.") from error

    if created or profile.favorite_school_id == favorite_school.id:
        return profile

    profile.favorite_school = favorite_school
    profile.save(update_fields=["favorite_school", "updated_at"])
    return profile


def authenticated_player(
    *,
    profile_id: int,
    favorite_school: School,
) -> UserProfile:
    try:
        profile = UserProfile.objects.select_for_update().get(pk=profile_id)
    except UserProfile.DoesNotExist as error:
        raise TakeoverError("Sign in again before taking the board.") from error
    if profile.is_banned:
        raise TakeoverError("This account cannot take the board.")
    if not profile.display_name:
        raise TakeoverError("Choose your board name before taking the board.")
    profile.favorite_school = favorite_school
    profile.save(update_fields=["favorite_school", "updated_at"])
    return profile


@dataclass(frozen=True)
class TakeoverResult:
    board_id: int
    bid_id: int
    published: bool


@transaction.atomic
def create_bid(
    *,
    board_id: int,
    session_key: str,
    display_name: str | None,
    represented_school_id: int,
    amount: Decimal,
    message: str,
    rules: BoardRules,
    now: datetime | None = None,
    authenticated_profile_id: int | None = None,
) -> TakeoverResult:
    now = now or timezone.now()
    board = Board.objects.select_for_update().select_related("school").get(pk=board_id)
    if not board.bidding_enabled or not rules.bidding_enabled:
        raise TakeoverError("Takeovers are paused for this board.")

    # A challenger that became due while no worker was polling must settle before
    # this challenger can be evaluated against the board's economic high bid.
    finalize_locked_pending_bid(board=board, rules=rules, now=now)
    board.refresh_from_db(fields=["current_bid", "current_amount_cents", "pending_bid", "guaranteed_until"])

    represented_school = School.objects.get(pk=represented_school_id, active=True)
    season_week = get_or_create_current_season_week(now=now)
    amount_cents = dollars_to_cents(amount)
    pending_amount_cents = board.pending_bid.amount_cents if board.pending_bid_id else 0
    required_cents = minimum_takeover_cents(
        board.current_amount_cents,
        rules,
        pending_amount_cents,
    )
    if amount_cents < required_cents:
        raise BidTooLowError(required_cents)

    if authenticated_profile_id:
        player = authenticated_player(
            profile_id=authenticated_profile_id,
            favorite_school=represented_school,
        )
    else:
        if display_name is None:
            raise TakeoverError("Choose a name for the board.")
        player = demo_player_for_session(
            session_key=session_key,
            display_name=display_name,
            favorite_school=represented_school,
        )
    bid = board.bids.create(
        bidder=player,
        represented_school=represented_school,
        season_week=season_week,
        message=message,
        amount_cents=amount_cents,
        status=Bid.Status.CREATED,
    )

    guarantee_is_active = bool(board.guaranteed_until and board.guaranteed_until > now)
    if board.current_bid_id and guarantee_is_active:
        previous_pending_bid_id = board.pending_bid_id
        if previous_pending_bid_id:
            Bid.objects.filter(pk=previous_pending_bid_id, status=Bid.Status.AUTHORIZED).update(
                status=Bid.Status.AUTH_CANCELED,
                canceled_at=now,
            )

        bid.status = Bid.Status.AUTHORIZED
        bid.authorized_at = now
        bid.save(update_fields=["status", "authorized_at"])
        board.pending_bid = bid
        board.save(update_fields=["pending_bid", "updated_at"])
        Activity.objects.create(
            type="demo_challenge_authorized",
            user=player,
            board=board,
            metadata={"bid_id": bid.id, "amount_cents": amount_cents},
        )
        return TakeoverResult(board_id=board.id, bid_id=bid.id, published=False)

    bid.status = Bid.Status.DEMO_WON
    bid.captured_at = now
    bid.save(update_fields=["status", "captured_at"])
    publish_takeover(
        board=board,
        bid=bid,
        guaranteed_display_seconds=rules.guaranteed_display_seconds,
        published_at=now,
    )
    Activity.objects.create(
        type="demo_takeover_published",
        user=player,
        board=board,
        metadata={"bid_id": bid.id, "amount_cents": amount_cents},
    )
    return TakeoverResult(board_id=board.id, bid_id=bid.id, published=True)
