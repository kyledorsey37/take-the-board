"""Build the private, customer-facing account history from durable records."""

from collections import defaultdict
from decimal import Decimal
from urllib.parse import quote, urlencode

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse

from apps.bidding.models import Bid
from apps.payments.models import LedgerEntry


def _related_or_none(instance, relation: str):
    try:
        return getattr(instance, relation)
    except ObjectDoesNotExist:
        return None


def _money(cents: int) -> Decimal:
    return Decimal(cents) / 100


def _status_for_bid(bid: Bid) -> tuple[str, str, str]:
    if bid.status in {Bid.Status.WON, Bid.Status.DEMO_WON}:
        if bid.is_current:
            return "active", "Active takeover", "Your message is live on this board."
        if _related_or_none(bid, "takeover"):
            return "ended", "Takeover ended", "Your message was live on this board."
        return "won", "Won", "Your takeover was successfully finalized."
    if bid.status == Bid.Status.AUTHORIZED:
        return "pending", "Payment authorized", "Your card is temporarily authorized while this move waits to settle."
    if bid.status == Bid.Status.CHECKOUT_CREATED:
        return "pending", "Payment pending", "Checkout started. We are waiting for the payment result."
    if bid.status == Bid.Status.PROCESSING:
        return "pending", "Processing", "Your payment is being finalized."
    if bid.status in {Bid.Status.OUTBID, Bid.Status.AUTH_CANCELED}:
        return "released", "Outbid before takeover", "Your payment was not captured. Any temporary authorization will be released by your card issuer."
    if bid.status == Bid.Status.PAYMENT_FAILED:
        return "failed", "Payment failed", "The payment did not complete, so this bid did not go live."
    if bid.status == Bid.Status.REFUNDED:
        return "refunded", "Refunded", "This takeover was removed and a refund was issued."
    if bid.status == Bid.Status.DISPUTED:
        return "disputed", "Payment under dispute", "This payment is under review. Contact support if you need help."
    if bid.status == Bid.Status.MODERATION_APPROVED:
        return "pending", "Message approved", "Your message passed review and is waiting for payment."
    return "pending", "Bid started", "Your bid is being prepared."


def build_account_history(profile):
    bids = list(
        Bid.objects.filter(bidder=profile)
        .select_related("board__entity", "represented_entity", "payment_capture", "purchase_evidence", "takeover")
        .order_by("-created_at", "-id")
    )
    bid_ids = [bid.id for bid in bids]
    ledger_by_bid = defaultdict(list)
    for entry in LedgerEntry.objects.filter(bid_id__in=bid_ids).order_by("created_at", "id"):
        ledger_by_bid[entry.bid_id].append(entry)

    captured_total_cents = 0
    refunded_total_cents = 0
    chargeback_total_cents = 0
    open_authorizations_cents = 0
    active_takeovers_count = 0

    for bid in bids:
        bid.is_current = bid.board.current_bid_id == bid.id
        bid.status_class, bid.status_title, bid.status_description = _status_for_bid(bid)
        bid.reference = f"TTB-{str(bid.public_id).split('-')[0].upper()}"
        bid.board_url = reverse("schools:detail", kwargs={"slug": bid.board.entity.slug})
        entries = ledger_by_bid[bid.id]
        capture = _related_or_none(bid, "payment_capture")
        bid.charge_cents = capture.gross_amount_cents if capture else sum(
            entry.amount_cents
            for entry in entries
            if entry.type == LedgerEntry.Type.BID_CAPTURE and entry.amount_cents > 0
        )
        bid.refund_cents = -sum(
            entry.amount_cents for entry in entries if entry.type == LedgerEntry.Type.REFUND and entry.amount_cents < 0
        )
        bid.chargeback_cents = -sum(
            entry.amount_cents
            for entry in entries
            if entry.type == LedgerEntry.Type.CHARGEBACK and entry.amount_cents < 0
        )
        bid.charge_dollars = _money(bid.charge_cents)
        bid.refund_dollars = _money(bid.refund_cents)
        bid.chargeback_dollars = _money(bid.chargeback_cents)
        bid.net_dollars = _money(max(0, bid.charge_cents - bid.refund_cents - bid.chargeback_cents))
        bid.capture = capture
        bid.has_charge = bid.charge_cents > 0
        bid.has_refund = bid.refund_cents > 0
        bid.has_chargeback = bid.chargeback_cents > 0
        if bid.has_charge:
            support_subject = f"Question about Take the Board bid {bid.reference}"
            support_body = (
                "Hello,\n\n"
                "I have a question about this Take the Board bid.\n\n"
                f"Reference: {bid.reference}\n"
                f"Board: {bid.board.entity.name}\n"
                f"Bid amount: ${bid.amount_cents / 100:.2f}\n"
                f"Status: {bid.status_title}\n"
                f"Date: {bid.created_at:%B %-d, %Y}\n\n"
                "Please help me review this charge.\n"
            )
            bid.support_url = (
                f"mailto:{settings.TAKEBOARD_SUPPORT_EMAIL}?"
                f"{urlencode({'subject': support_subject, 'body': support_body}, quote_via=quote)}"
            )
        if bid.status == Bid.Status.DEMO_WON:
            bid.charge_label = "Free-play move"
        elif bid.has_charge:
            bid.charge_label = f"Captured ${bid.charge_dollars:.2f}"
        elif bid.status in {Bid.Status.AUTHORIZED, Bid.Status.CHECKOUT_CREATED, Bid.Status.PROCESSING}:
            bid.charge_label = "No charge yet"
        else:
            bid.charge_label = "Not captured"

        captured_total_cents += bid.charge_cents
        refunded_total_cents += bid.refund_cents
        chargeback_total_cents += bid.chargeback_cents
        if bid.status == Bid.Status.AUTHORIZED:
            open_authorizations_cents += bid.amount_cents
        if bid.is_current:
            active_takeovers_count += 1

    return {
        "bids": bids,
        "bid_count": len(bids),
        "active_takeovers_count": active_takeovers_count,
        "captured_total_dollars": _money(captured_total_cents),
        "refunded_total_dollars": _money(refunded_total_cents),
        "chargeback_total_dollars": _money(chargeback_total_cents),
        "open_authorizations_dollars": _money(open_authorizations_cents),
    }
