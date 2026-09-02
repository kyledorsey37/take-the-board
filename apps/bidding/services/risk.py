"""Centralized, auditable risk decisions for paid bids."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.bidding.models import Bid, BidRiskConfig
from apps.payments.models import LedgerEntry


class RiskReason:
    ACCOUNT_SUSPENDED = "account_suspended"
    OPEN_DISPUTE = "open_dispute"
    BID_TOO_LARGE = "bid_too_large"
    HOURLY_LIMIT_EXCEEDED = "hourly_limit_exceeded"
    DAILY_LIMIT_EXCEEDED = "daily_limit_exceeded"
    PAYMENT_FAILURE_COOLDOWN = "payment_failure_cooldown"
    NEW_USER_BIDDING_DISABLED = "new_user_bidding_disabled"
    HIGH_VALUE_BIDDING_DISABLED = "high_value_bidding_disabled"


@dataclass(frozen=True)
class BidLimits:
    max_bid_cents: int
    hourly_spend_cents: int
    daily_spend_cents: int


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str | None
    max_bid_cents: int
    hourly_remaining_cents: int
    daily_remaining_cents: int
    pending_authorization_cents: int
    requires_extra_confirmation: bool
    requires_typed_confirmation: bool

    @property
    def user_message(self) -> str:
        if self.reason == RiskReason.BID_TOO_LARGE:
            return f"This bid exceeds your current account limit of ${self.max_bid_cents / 100:.2f}."
        if self.reason in {RiskReason.HOURLY_LIMIT_EXCEEDED, RiskReason.DAILY_LIMIT_EXCEEDED}:
            return "You’ve reached your spending limit for now. You can place another bid later."
        if self.reason in {RiskReason.ACCOUNT_SUSPENDED, RiskReason.OPEN_DISPUTE}:
            return "Paid bidding is unavailable for this account while it is under review."
        if self.reason == RiskReason.PAYMENT_FAILURE_COOLDOWN:
            return "Please wait before trying another payment."
        return "Paid bidding is temporarily unavailable for this account."


def get_risk_config() -> BidRiskConfig:
    config = BidRiskConfig.objects.order_by("id").first()
    return config or BidRiskConfig()


def recalculate_risk_tier(user: UserProfile, *, now=None, save: bool = True) -> str:
    now = now or timezone.now()
    if user.paid_bidding_suspended or user.has_open_dispute:
        tier = UserProfile.RiskTier.SUSPENDED
    elif user.dispute_count:
        tier = UserProfile.RiskTier.RESTRICTED
    elif user.successful_bid_count >= 10 and user.created_at <= now - timedelta(days=7):
        tier = UserProfile.RiskTier.TRUSTED
    elif user.successful_bid_count >= 3 and user.created_at <= now - timedelta(hours=24):
        tier = UserProfile.RiskTier.ESTABLISHED
    else:
        tier = UserProfile.RiskTier.NEW
    if save and user.risk_tier != tier:
        user.risk_tier = tier
        user.save(update_fields=["risk_tier", "updated_at"])
    return tier


def get_user_risk_tier(user: UserProfile, *, now=None) -> str:
    return recalculate_risk_tier(user, now=now)


def get_bid_limits(user: UserProfile, *, config: BidRiskConfig | None = None, now=None) -> BidLimits:
    config = config or get_risk_config()
    tier = get_user_risk_tier(user, now=now)
    if tier == UserProfile.RiskTier.TRUSTED:
        limits = BidLimits(config.trusted_max_bid_cents, config.trusted_hourly_spend_cents, config.trusted_daily_spend_cents)
    elif tier == UserProfile.RiskTier.ESTABLISHED:
        limits = BidLimits(config.established_max_bid_cents, config.established_hourly_spend_cents, config.established_daily_spend_cents)
    else:
        limits = BidLimits(config.new_max_bid_cents, config.new_hourly_spend_cents, config.new_daily_spend_cents)
    return BidLimits(
        min(limits.max_bid_cents, config.global_max_bid_cents),
        min(limits.hourly_spend_cents, config.global_hourly_spend_cents),
        limits.daily_spend_cents,
    )


def _net_captured_spend(user: UserProfile, since) -> int:
    return int(
        LedgerEntry.objects.filter(
            user=user,
            created_at__gte=since,
            type__in=[LedgerEntry.Type.BID_CAPTURE, LedgerEntry.Type.REFUND, LedgerEntry.Type.CHARGEBACK],
        ).aggregate(total=Sum("amount_cents"))["total"]
        or 0
    )


def calculate_hourly_spend(user: UserProfile, *, now=None) -> int:
    return max(0, _net_captured_spend(user, (now or timezone.now()) - timedelta(hours=1)))


def calculate_daily_spend(user: UserProfile, *, now=None) -> int:
    return max(0, _net_captured_spend(user, (now or timezone.now()) - timedelta(hours=24)))


def calculate_pending_authorization_exposure(user: UserProfile) -> int:
    return int(
        Bid.objects.filter(bidder=user, status=Bid.Status.AUTHORIZED).aggregate(total=Sum("amount_cents"))["total"]
        or 0
    )


def _payment_failure_cooldown(user: UserProfile, config: BidRiskConfig, now) -> bool:
    window_start = now - timedelta(minutes=config.payment_failure_window_minutes)
    recent_failures = Bid.objects.filter(
        bidder=user,
        payment_failed_at__gte=window_start,
    ).aggregate(total=Sum("payment_failure_count"))["total"] or 0
    # Preserve the cooldown for terminal failures created before the retry
    # counter was introduced.
    legacy_failures = Bid.objects.filter(
        bidder=user,
        status=Bid.Status.PAYMENT_FAILED,
        payment_failed_at__isnull=True,
        created_at__gte=window_start,
    ).count()
    return int(recent_failures) + legacy_failures >= config.payment_failure_limit


def validate_bid_risk(user: UserProfile, amount_cents: int, *, now=None) -> RiskDecision:
    now = now or timezone.now()
    config = get_risk_config()
    limits = get_bid_limits(user, config=config, now=now)
    hourly_spend = calculate_hourly_spend(user, now=now)
    daily_spend = calculate_daily_spend(user, now=now)
    pending = calculate_pending_authorization_exposure(user)
    hourly_remaining = max(0, limits.hourly_spend_cents - hourly_spend - pending)
    daily_remaining = max(0, limits.daily_spend_cents - daily_spend - pending)
    tier = user.risk_tier
    reason = None
    if user.is_banned or user.paid_bidding_suspended or tier == UserProfile.RiskTier.SUSPENDED:
        reason = RiskReason.ACCOUNT_SUSPENDED
    elif user.has_open_dispute:
        reason = RiskReason.OPEN_DISPUTE
    elif tier == UserProfile.RiskTier.NEW and not config.new_user_bidding_enabled:
        reason = RiskReason.NEW_USER_BIDDING_DISABLED
    elif amount_cents > limits.max_bid_cents:
        reason = RiskReason.BID_TOO_LARGE
    elif amount_cents >= config.high_value_confirmation_threshold_cents and not config.high_value_bidding_enabled:
        reason = RiskReason.HIGH_VALUE_BIDDING_DISABLED
    elif amount_cents > hourly_remaining:
        reason = RiskReason.HOURLY_LIMIT_EXCEEDED
    elif amount_cents > daily_remaining:
        reason = RiskReason.DAILY_LIMIT_EXCEEDED
    elif _payment_failure_cooldown(user, config, now):
        reason = RiskReason.PAYMENT_FAILURE_COOLDOWN
    return RiskDecision(
        allowed=reason is None,
        reason=reason,
        max_bid_cents=limits.max_bid_cents,
        hourly_remaining_cents=hourly_remaining,
        daily_remaining_cents=daily_remaining,
        pending_authorization_cents=pending,
        requires_extra_confirmation=amount_cents >= config.high_value_confirmation_threshold_cents,
        requires_typed_confirmation=amount_cents > config.very_high_value_confirmation_threshold_cents,
    )
