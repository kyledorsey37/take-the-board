"""Create one-time Stripe Checkout Sessions for authenticated takeovers."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import stripe
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.bidding.models import Bid
from apps.bidding.models import BidConfirmation
from apps.bidding.services.create_bid import (
    BidTooLowError,
    TakeoverError,
    authenticated_player,
    dollars_to_cents,
)
from apps.bidding.services.finalize_bid import finalize_locked_pending_bid
from apps.bidding.services.rules import BoardRules, minimum_takeover_cents
from apps.boards.models import Board
from apps.leaderboard.week_services import get_or_create_current_period
from apps.moderation.models import MessageValidation
from apps.moderation.services.rate_limits import safe_key
from apps.moderation.services.validators import DeterministicReject, validate_message_deterministically
from apps.schools.models import Entity
from apps.bidding.services.risk import validate_bid_risk

from .capture_payment import capture_payment


@dataclass(frozen=True)
class CheckoutResult:
    bid_id: int
    bid_public_id: str
    client_secret: str


@transaction.atomic
def create_checkout(
    *,
    board_id: int,
    profile_id: int,
    represented_entity_id: int,
    amount: Decimal,
    message: str,
    validation_id: int,
    confirmation_id: int | None = None,
    rules: BoardRules,
    return_url: str,
    now: datetime | None = None,
) -> CheckoutResult:
    if not settings.STRIPE_SECRET_KEY:
        raise TakeoverError("Stripe payments are not configured yet.")

    now = now or timezone.now()
    try:
        candidate = validate_message_deterministically(message)
    except DeterministicReject as error:
        raise TakeoverError("That does not meet the Take the Board community guidelines.") from error
    board = Board.objects.select_for_update().select_related("entity__competition").get(pk=board_id)
    if not board.bidding_enabled or not rules.bidding_enabled:
        raise TakeoverError("Takeovers are paused for this board.")

    # Settle an expired challenger before calculating the new price. The worker
    # normally handles this, but checkout creation must be correct on its own.
    finalize_locked_pending_bid(
        board=board,
        rules=rules,
        now=now,
        capture_pending_bid=capture_payment,
    )
    board.refresh_from_db(fields=["current_bid", "current_amount_cents", "pending_bid", "guaranteed_until"])

    represented_entity = Entity.objects.get(
        pk=represented_entity_id,
        competition=board.entity.competition,
        active=True,
    )
    period = get_or_create_current_period(competition=board.entity.competition, now=now)
    amount_cents = dollars_to_cents(amount)
    pending_amount_cents = board.pending_bid.amount_cents if board.pending_bid_id else 0
    required_cents = minimum_takeover_cents(
        board.current_amount_cents,
        rules,
        pending_amount_cents,
    )
    if amount_cents < required_cents:
        raise BidTooLowError(required_cents)

    player = authenticated_player(
        profile_id=profile_id,
        favorite_entity=represented_entity,
    )
    if not player.has_age_acknowledgement:
        raise TakeoverError("Confirm that you are 18 or older before placing a paid bid.")
    confirmation = None
    if confirmation_id is not None:
        try:
            confirmation = BidConfirmation.objects.select_for_update().get(pk=confirmation_id)
        except BidConfirmation.DoesNotExist as error:
            raise TakeoverError("A fresh bid confirmation is required before checkout.") from error
        if (
            confirmation.user_id != player.id
            or confirmation.board_id != board.id
            or confirmation.represented_entity_id != represented_entity.id
            or confirmation.message != message
            or confirmation.amount_cents != amount_cents
            or confirmation.expires_at <= now
            or confirmation.consumed_at is not None
        ):
            raise TakeoverError("A fresh bid confirmation is required before checkout.")

    risk_decision = validate_bid_risk(player, amount_cents, now=now)
    if not risk_decision.allowed:
        raise TakeoverError(risk_decision.user_message)

    try:
        validation = MessageValidation.objects.select_for_update().get(pk=validation_id)
    except MessageValidation.DoesNotExist as error:
        raise TakeoverError("A fresh message approval is required before checkout.") from error
    if (
        validation.user_id != player.id
        or validation.board_id != board.id
        or validation.represented_entity_id != represented_entity.id
        or validation.message_hash != safe_key("message-value", candidate.original)
        or validation.decision != MessageValidation.Decision.ALLOW
        or validation.policy_version != settings.TAKEBOARD_MODERATION_POLICY_VERSION
        or validation.expires_at <= now
        or validation.consumed_at is not None
    ):
        raise TakeoverError("A fresh message approval is required before checkout.")
    # This record is consumed before the bid is created. The surrounding atomic
    # transaction rolls it back if Stripe setup fails, making the exact approval
    # retryable only when no Checkout Session was persisted.
    validation.consumed_at = now
    validation.save(update_fields=["consumed_at"])
    bid = board.bids.create(
        bidder=player,
        represented_entity=represented_entity,
        period=period,
        message=message,
        message_validation=validation,
        confirmation=confirmation,
        amount_cents=amount_cents,
        status=Bid.Status.CREATED,
    )

    try:
        checkout_session = stripe.checkout.Session.create(
            mode="payment",
            ui_mode="embedded",
            managed_payments={"enabled": False},
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "product_data": {"name": "Takeover"},
                        "unit_amount": amount_cents,
                    },
                    "quantity": 1,
                }
            ],
            payment_intent_data={
                "capture_method": "manual",
                "statement_descriptor": settings.TAKEBOARD_STRIPE_STATEMENT_DESCRIPTOR,
                "metadata": {
                    "bid_id": str(bid.public_id),
                    "board_id": str(board.id),
                },
            },
            metadata={
                "bid_id": str(bid.public_id),
                "board_id": str(board.id),
            },
            customer_email=player.email,
            return_url=return_url,
            redirect_on_completion="if_required",
            api_key=settings.STRIPE_SECRET_KEY,
            idempotency_key=f"takeboard-checkout-{bid.public_id}",
        )
    except stripe.error.StripeError as error:
        raise TakeoverError("We could not start secure checkout. Please try again.") from error

    client_secret = checkout_session.get("client_secret")
    if not client_secret:
        raise TakeoverError("Stripe did not return a checkout session.")

    bid.status = Bid.Status.CHECKOUT_CREATED
    bid.stripe_checkout_session_id = checkout_session["id"]
    payment_intent_id = checkout_session.get("payment_intent")
    if payment_intent_id:
        bid.stripe_payment_intent_id = payment_intent_id
    bid.save(
        update_fields=[
            "status",
            "stripe_checkout_session_id",
            "stripe_payment_intent_id",
        ]
    )
    if confirmation:
        confirmation.confirmed_at = now
        confirmation.consumed_at = now
        confirmation.save(update_fields=["confirmed_at", "consumed_at"])
    return CheckoutResult(
        bid_id=bid.id,
        bid_public_id=str(bid.public_id),
        client_secret=client_secret,
    )
