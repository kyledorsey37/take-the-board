"""Creation and lifecycle updates for chargeback-ready delivery evidence."""

from __future__ import annotations

from datetime import datetime

from django.db import transaction

from apps.bidding.models import Bid
from apps.payments.models import PurchaseEvidence


@transaction.atomic
def record_purchase_evidence(*, bid: Bid, published_at: datetime, guaranteed_until: datetime) -> PurchaseEvidence:
    """Idempotently retain the purchase context when a captured bid goes live."""
    confirmation = bid.confirmation
    profile = bid.bidder
    defaults = {
        "confirmation": confirmation,
        "cognito_sub": str(profile.cognito_sub),
        "email": profile.email,
        "display_name": profile.display_name or "",
        "board_name": bid.board.entity.name,
        "ip_address": confirmation.ip_address if confirmation else None,
        "user_agent": confirmation.user_agent if confirmation else "",
        "request_id": confirmation.request_id if confirmation else "",
        "terms_version": profile.terms_version,
        "terms_accepted_at": profile.terms_accepted_at,
        "confirmation_version": confirmation.confirmation_version if confirmation else "",
        "risk_tier_at_purchase": profile.risk_tier,
        "published_at": published_at,
        "guaranteed_until": guaranteed_until,
    }
    evidence, _ = PurchaseEvidence.objects.get_or_create(bid=bid, defaults=defaults)
    return evidence


def record_delivery_end(*, bid_id: int | None, ended_at: datetime) -> None:
    if bid_id:
        PurchaseEvidence.objects.filter(bid_id=bid_id, ended_at__isnull=True).update(ended_at=ended_at)
