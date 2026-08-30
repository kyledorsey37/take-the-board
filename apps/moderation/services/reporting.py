"""Transactional public report submission for immutable published takeovers."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.boards.models import BoardTakeover
from apps.bidding.models import Bid
from apps.moderation.models import MessageReport, MessageReportCase
from apps.moderation.services.rate_limits import enforce_message_report_limits, safe_key


logger = logging.getLogger(__name__)


class ReportUnavailable(Exception):
    """The public target is unavailable, closed, or cannot accept a report."""


@dataclass(frozen=True)
class ReportSubmission:
    accepted: bool
    opened_case: bool = False
    duplicate: bool = False


def remote_addr(request) -> str:
    return request.META.get("REMOTE_ADDR", "unknown")


def submit_message_report(*, takeover_public_id, reporter, category: str, remote_addr: str) -> ReportSubmission:
    """Create at most one report per profile/case without leaking case state."""
    if category not in MessageReport.Category.values:
        raise ReportUnavailable

    with transaction.atomic():
        takeover = (
            BoardTakeover.objects.select_for_update()
            .select_related("board", "bid")
            .filter(public_id=takeover_public_id)
            .first()
        )
        if not takeover:
            raise ReportUnavailable

        # Only published takeovers are represented by this model. Explicitly
        # reject a malformed/non-visible record instead of treating a display
        # string as the report target.
        if takeover.board_id != takeover.bid.board_id or takeover.bid.status not in {
            Bid.Status.WON,
            Bid.Status.DEMO_WON,
        }:
            raise ReportUnavailable

        report_case = (
            MessageReportCase.objects.select_for_update()
            .filter(takeover=takeover)
            .first()
        )
        if report_case and report_case.status != MessageReportCase.Status.OPEN:
            raise ReportUnavailable

        now = timezone.now()
        opened_case = report_case is None
        enforce_message_report_limits(
            user_id=reporter.id,
            remote_addr=remote_addr,
            opening_case=opened_case,
        )
        if opened_case:
            try:
                with transaction.atomic():
                    report_case = MessageReportCase.objects.create(
                        takeover=takeover,
                        last_reported_at=now,
                    )
            except IntegrityError:
                # Another transaction won the one-to-one creation race. Fetch
                # and lock its row so a distinct reporter can still submit.
                report_case = MessageReportCase.objects.select_for_update().get(takeover=takeover)
                opened_case = False
                if report_case.status != MessageReportCase.Status.OPEN:
                    raise ReportUnavailable

        try:
            with transaction.atomic():
                MessageReport.objects.create(
                    case=report_case,
                    reporter=reporter,
                    category=category,
                    reporter_ip_hash=safe_key("ip", remote_addr),
                )
        except IntegrityError:
            logger.info(
                "message_report_duplicate",
                extra={"profile_id": reporter.public_id if hasattr(reporter, "public_id") else reporter.pk, "takeover_id": str(takeover.public_id)},
            )
            return ReportSubmission(accepted=False, duplicate=True)

        report_case.last_reported_at = now
        report_case.save(update_fields=["last_reported_at", "updated_at"])
        logger.info(
            "message_report_submitted",
            extra={
                "profile_id": reporter.pk,
                "takeover_id": str(takeover.public_id),
                "case_id": str(report_case.public_id),
                "board_id": takeover.board_id,
                "category": category,
            },
        )
        if opened_case:
            logger.info(
                "message_report_case_opened",
                extra={"case_id": str(report_case.public_id), "takeover_id": str(takeover.public_id), "board_id": takeover.board_id},
            )
        return ReportSubmission(accepted=True, opened_case=opened_case)
