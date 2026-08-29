from dataclasses import dataclass

from django.conf import settings

from apps.core.models import GameConfig


@dataclass(frozen=True)
class BoardRules:
    minimum_bid_increment_cents: int
    maximum_bid_cents: int
    guaranteed_display_seconds: int
    message_max_length: int
    bidding_enabled: bool


def current_board_rules() -> BoardRules:
    config = GameConfig.objects.order_by("id").first()
    if config:
        return BoardRules(
            minimum_bid_increment_cents=config.minimum_bid_increment_cents,
            maximum_bid_cents=config.maximum_bid_cents,
            guaranteed_display_seconds=config.guaranteed_display_seconds,
            message_max_length=config.message_max_length,
            bidding_enabled=config.bidding_enabled,
        )

    return BoardRules(
        minimum_bid_increment_cents=settings.TAKEBOARD_MINIMUM_BID_INCREMENT_CENTS,
        maximum_bid_cents=settings.TAKEBOARD_MAXIMUM_BID_CENTS,
        guaranteed_display_seconds=settings.TAKEBOARD_GUARANTEED_DISPLAY_SECONDS,
        message_max_length=settings.TAKEBOARD_MESSAGE_MAX_LENGTH,
        bidding_enabled=True,
    )


def effective_high_bid_cents(current_amount_cents: int, pending_amount_cents: int = 0) -> int:
    return max(current_amount_cents, pending_amount_cents)


def minimum_takeover_cents(
    current_amount_cents: int,
    rules: BoardRules,
    pending_amount_cents: int = 0,
) -> int:
    effective_high_bid = effective_high_bid_cents(current_amount_cents, pending_amount_cents)
    if effective_high_bid == 0:
        return rules.minimum_bid_increment_cents
    return effective_high_bid + rules.minimum_bid_increment_cents
