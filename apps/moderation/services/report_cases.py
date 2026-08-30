"""Admin-only report case resolution and durable payment remediation."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.bidding.models import Bid
from apps.boards.models import Board, BoardTakeover
from apps.moderation.models import MessageReportCase, ModerationPaymentAction
from apps.moderation.services.operations import audit_action


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CaseResolution:
    case_id: int
    changed: bool
    restored_previous: bool


def _payment_action_for_bid(*, case: MessageReportCase, bid: Bid) -> ModerationPaymentAction:
    """Create the single durable operation for a case/bid pair, if needed."""
    if bid.status == Bid.Status.AUTHORIZED:
        operation = ModerationPaymentAction.Operation.CANCEL_AUTHORIZATION
        amount_cents = None
        status = (
            ModerationPaymentAction.Status.PENDING
            if bid.stripe_payment_intent_id
            else ModerationPaymentAction.Status.NOT_REQUIRED
        )
    else:
        operation = ModerationPaymentAction.Operation.REFUND
        # The worker sets the immutable refund amount only after it has the
        # actual Stripe processing fee from the capture snapshot.
        amount_cents = None
        status = (
            ModerationPaymentAction.Status.PENDING
            if bid.status == Bid.Status.WON and bid.stripe_payment_intent_id
            else ModerationPaymentAction.Status.NOT_REQUIRED
        )
    action, created = ModerationPaymentAction.objects.get_or_create(
        case=case,
        bid=bid,
        defaults={"operation": operation, "amount_cents": amount_cents, "status": status},
    )
    if created and status == ModerationPaymentAction.Status.NOT_REQUIRED:
        action.completed_at = timezone.now()
        action.save(update_fields=["completed_at", "updated_at"])
    return action


def _prior_non_removed_takeover(takeover: BoardTakeover) -> BoardTakeover | None:
    """Follow immutable previous-bid links while guarding malformed cycles."""
    prior_bid_id = takeover.previous_bid_id
    visited = {takeover.bid_id}
    while prior_bid_id and prior_bid_id not in visited:
        visited.add(prior_bid_id)
        candidate = (
            BoardTakeover.objects.select_for_update()
            .select_related("bid", "controller")
            .filter(bid_id=prior_bid_id)
            .first()
        )
        if not candidate:
            return None
        # Lock the optional one-to-one row separately. PostgreSQL cannot apply
        # FOR UPDATE to the nullable side of the LEFT OUTER JOIN that
        # select_related("report_case") would otherwise generate.
        report_case = (
            MessageReportCase.objects.select_for_update()
            .filter(takeover_id=candidate.id)
            .first()
        )
        if not report_case or report_case.status != MessageReportCase.Status.REMOVED:
            return candidate
        prior_bid_id = candidate.previous_bid_id
    return None


@transaction.atomic
def approve_case(*, case_id: int, actor, reason: str) -> CaseResolution:
    reason = reason.strip()
    if not reason or len(reason) > 500:
        raise ValueError("A resolution reason of 1 to 500 characters is required.")
    case = MessageReportCase.objects.select_for_update().get(pk=case_id)
    if case.status != MessageReportCase.Status.OPEN:
        return CaseResolution(case_id=case.id, changed=False, restored_previous=False)
    now = timezone.now()
    case.status = MessageReportCase.Status.APPROVED
    case.resolved_at = now
    case.resolved_by = actor
    case.resolution_reason = reason
    case.save(update_fields=["status", "resolved_at", "resolved_by", "resolution_reason", "updated_at"])
    audit_action(actor=actor, action="dismiss_message_reports", target=case, reason=reason)
    logger.info("message_report_case_resolved", extra={"case_id": str(case.public_id), "status": case.status})
    return CaseResolution(case_id=case.id, changed=True, restored_previous=False)


@transaction.atomic
def remove_case(*, case_id: int, actor, reason: str) -> CaseResolution:
    """Redact a takeover and restore only a prior non-removed board state."""
    reason = reason.strip()
    if not reason or len(reason) > 500:
        raise ValueError("A resolution reason of 1 to 500 characters is required.")

    case = MessageReportCase.objects.select_for_update().get(pk=case_id)
    if case.status != MessageReportCase.Status.OPEN:
        return CaseResolution(case_id=case.id, changed=False, restored_previous=False)

    # Keep this lock order stable: case -> takeover -> bid -> board.
    takeover = BoardTakeover.objects.select_for_update().get(pk=case.takeover_id)
    bid = Bid.objects.select_for_update().get(pk=takeover.bid_id)
    board = Board.objects.select_for_update().get(pk=takeover.board_id)
    now = timezone.now()
    restored_previous = False

    if board.current_bid_id == bid.id:
        prior = _prior_non_removed_takeover(takeover)
        if prior:
            board.current_bid = prior.bid
            board.current_controller = prior.controller
            board.current_amount_cents = prior.amount_cents
            board.current_message = prior.message
            restored_previous = True
        else:
            board.current_bid = None
            board.current_controller = None
            board.current_amount_cents = 0
            board.current_message = settings.TAKEBOARD_DEFAULT_BOARD_MESSAGE
        board.guaranteed_until = None

        if board.pending_bid_id:
            pending_bid = Bid.objects.select_for_update().get(pk=board.pending_bid_id)
            board.pending_bid = None
            _payment_action_for_bid(case=case, bid=pending_bid)
            if pending_bid.status == Bid.Status.AUTHORIZED:
                pending_bid.status = Bid.Status.AUTH_CANCELED
                pending_bid.canceled_at = now
                pending_bid.save(update_fields=["status", "canceled_at"])

        board.version += 1
        board.save(
            update_fields=[
                "current_bid",
                "current_controller",
                "current_amount_cents",
                "current_message",
                "pending_bid",
                "guaranteed_until",
                "version",
                "updated_at",
            ]
        )

    case.status = MessageReportCase.Status.REMOVED
    case.resolved_at = now
    case.resolved_by = actor
    case.resolution_reason = reason
    case.save(update_fields=["status", "resolved_at", "resolved_by", "resolution_reason", "updated_at"])
    action = _payment_action_for_bid(case=case, bid=bid)
    audit_action(actor=actor, action="remove_message", target=case, reason=reason)
    if restored_previous:
        audit_action(actor=actor, action="restore_previous_takeover", target=board, reason=reason)
    audit_action(actor=actor, action="payment_remediation_queued", target=action, reason=reason)
    logger.info(
        "message_report_case_resolved",
        extra={"case_id": str(case.public_id), "status": case.status, "board_id": board.id},
    )
    return CaseResolution(case_id=case.id, changed=True, restored_previous=restored_previous)
