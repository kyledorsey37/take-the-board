"""Server-side confirmation snapshots for the paid bidding flow."""

from __future__ import annotations

from datetime import datetime

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.bidding.models import BidConfirmation
from apps.bidding.services.create_bid import BidTooLowError, TakeoverError
from apps.bidding.services.risk import RiskDecision, validate_bid_risk
from apps.bidding.services.rules import BoardRules, minimum_takeover_cents
from apps.boards.models import Board
from apps.moderation.models import MessageValidation
from apps.moderation.services.rate_limits import safe_key
from apps.moderation.services.validators import validate_message_deterministically
from apps.schools.models import Entity


@transaction.atomic
def create_confirmation(
    *,
    board_id: int,
    user: UserProfile,
    represented_entity_id: int,
    amount_cents: int,
    message: str,
    validation: MessageValidation,
    rules: BoardRules,
    ip_address: str | None,
    user_agent: str,
    request_id: str,
    now: datetime | None = None,
) -> tuple[BidConfirmation, RiskDecision]:
    now = now or timezone.now()
    candidate = validate_message_deterministically(message)
    board = Board.objects.select_for_update().select_related("entity__competition").get(pk=board_id)
    entity = Entity.objects.get(pk=represented_entity_id, competition=board.entity.competition, active=True)
    if not board.bidding_enabled or not rules.bidding_enabled:
        raise TakeoverError("Takeovers are paused for this board.")
    if (
        validation.user_id != user.id
        or validation.board_id != board.id
        or validation.represented_entity_id != entity.id
        or validation.message_hash != safe_key("message-value", candidate.original)
        or validation.decision != MessageValidation.Decision.ALLOW
        or validation.expires_at <= now
        or validation.consumed_at is not None
    ):
        raise TakeoverError("A fresh message approval is required before confirmation.")
    pending_amount = board.pending_bid.amount_cents if board.pending_bid_id else 0
    minimum = minimum_takeover_cents(board.current_amount_cents, rules, pending_amount)
    if amount_cents < minimum:
        raise BidTooLowError(minimum)
    decision = validate_bid_risk(user, amount_cents, now=now)
    if not decision.allowed:
        raise TakeoverError(decision.user_message)
    confirmation = BidConfirmation.objects.create(
        user=user,
        board=board,
        represented_entity=entity,
        message_validation=validation,
        message=message,
        amount_cents=amount_cents,
        current_board_amount_cents=board.current_amount_cents,
        pending_challenge_amount_cents=pending_amount or None,
        minimum_bid_cents=minimum,
        guaranteed_seconds=rules.guaranteed_display_seconds,
        expires_at=validation.expires_at,
        ip_address=ip_address,
        user_agent=user_agent[:2000],
        request_id=request_id[:64],
    )
    return confirmation, decision
