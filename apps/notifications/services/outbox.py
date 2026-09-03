"""Idempotent email intents and retry-safe provider delivery."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from apps.moderation.models import MessageReportCase, ModerationPaymentAction

from ..models import EmailOutbox
from .providers import EmailMessage, EmailProvider, EmailProviderError, get_email_provider


logger = logging.getLogger(__name__)


def _absolute_url(path: str) -> str:
    base_url = str(settings.TAKEBOARD_EMAIL_PUBLIC_BASE_URL).rstrip("/")
    return f"{base_url}{path}"


def _date_text(value) -> str:
    local_value = timezone.localtime(value)
    return local_value.strftime("%B %d, %Y").replace(" 0", " ")


def _reference(public_id) -> str:
    return f"TTB-{str(public_id).split('-')[0].upper()}"


def _recipient_for_bid(bid) -> str:
    evidence = getattr(bid, "purchase_evidence", None)
    return str(evidence.email if evidence else bid.bidder.email).strip()


def _enqueue(
    *,
    event_key: str,
    kind: str,
    recipient_email: str,
    context: dict[str, Any],
    waiting_for_refund: bool = False,
) -> EmailOutbox | None:
    try:
        validate_email(recipient_email)
    except ValidationError:
        logger.warning("email_outbox_skipped_invalid_recipient", extra={"event_key": event_key})
        return None
    outbox, created = EmailOutbox.objects.get_or_create(
        event_key=event_key,
        defaults={
            "kind": kind,
            "recipient_email": recipient_email,
            "context": context,
            "waiting_for_refund": waiting_for_refund,
        },
    )
    if (
        not created
        and outbox.waiting_for_refund
        and not waiting_for_refund
        and outbox.status not in {EmailOutbox.Status.SENT, EmailOutbox.Status.SUPPRESSED}
    ):
        outbox.waiting_for_refund = False
        outbox.available_at = timezone.now()
        outbox.save(update_fields=["waiting_for_refund", "available_at", "updated_at"])
    return outbox


def _removal_context(*, case: MessageReportCase) -> dict[str, Any]:
    takeover = case.takeover
    bid = takeover.bid
    return {
        "board_name": takeover.board.entity.name,
        "removed_on": _date_text(case.resolved_at or timezone.now()),
        "reference": _reference(bid.public_id),
        "policy_url": _absolute_url(reverse("core:community_guidelines")),
        "support_url": _absolute_url(reverse("core:contact")),
        "support_email": settings.TAKEBOARD_SUPPORT_EMAIL,
    }


def enqueue_message_removed_notice(
    *, case: MessageReportCase, waiting_for_refund: bool = False
) -> EmailOutbox | None:
    event_key = f"message-removed-v1:{case.public_id}"
    return _enqueue(
        event_key=event_key,
        kind=EmailOutbox.Kind.MESSAGE_REMOVED,
        recipient_email=_recipient_for_bid(case.takeover.bid),
        context=_removal_context(case=case),
        waiting_for_refund=waiting_for_refund,
    )


def attach_refund_to_removal_notice(*, action: ModerationPaymentAction) -> EmailOutbox | None:
    """Complete the one removal email with the actual fee-deducted refund."""
    case = action.case
    bid = action.bid
    capture = bid.payment_capture
    context = _removal_context(case=case)
    context.update(
        {
            "amount_paid": f"${bid.amount_cents / 100:.2f}",
            "processing_fee": f"${capture.stripe_fee_cents / 100:.2f}",
            "refund_amount": f"${action.amount_cents / 100:.2f}",
        }
    )
    event_key = f"message-removed-v1:{case.public_id}"
    outbox = EmailOutbox.objects.filter(event_key=event_key).first()
    if outbox is None:
        return _enqueue(
            event_key=event_key,
            kind=EmailOutbox.Kind.MESSAGE_REMOVED,
            recipient_email=_recipient_for_bid(bid),
            context=context,
        )
    if outbox.status in {EmailOutbox.Status.SENT, EmailOutbox.Status.SUPPRESSED}:
        return outbox
    outbox.context = context
    outbox.waiting_for_refund = False
    outbox.available_at = timezone.now()
    outbox.save(update_fields=["context", "waiting_for_refund", "available_at", "updated_at"])
    return outbox


def _claim(outbox_id: int | None = None) -> EmailOutbox | None:
    now = timezone.now()
    stale_before = now - timedelta(seconds=settings.TAKEBOARD_EMAIL_PROCESSING_TIMEOUT_SECONDS)
    available = Q(waiting_for_refund=False) & (
        Q(status=EmailOutbox.Status.PENDING, available_at__lte=now)
        | Q(status=EmailOutbox.Status.FAILED, available_at__lte=now)
        | Q(status=EmailOutbox.Status.PROCESSING, locked_at__lt=stale_before)
    )
    with transaction.atomic():
        query = (
            EmailOutbox.objects.select_for_update()
            .filter(available)
            .order_by("available_at", "id")
        )
        if outbox_id is not None:
            query = query.filter(pk=outbox_id)
        outbox = query.first()
        if outbox is None:
            return None
        outbox.status = EmailOutbox.Status.PROCESSING
        outbox.locked_at = now
        outbox.attempts += 1
        outbox.last_error_code = ""
        outbox.save(
            update_fields=["status", "locked_at", "attempts", "last_error_code", "updated_at"]
        )
        return outbox


def _render_message(outbox: EmailOutbox) -> EmailMessage:
    subject = {
        EmailOutbox.Kind.MESSAGE_REMOVED: "An update about your Take the Board message",
        EmailOutbox.Kind.REFUND_CONFIRMATION: "Your Take the Board refund is confirmed",
    }[outbox.kind]
    context = dict(outbox.context)
    return EmailMessage(
        subject=subject,
        text_body=render_to_string(f"emails/{outbox.kind}.txt", context).strip(),
        html_body=render_to_string(f"emails/{outbox.kind}.html", context).strip(),
        recipient_email=outbox.recipient_email,
    )


def _retry_delay(attempts: int) -> int:
    return min(
        settings.TAKEBOARD_EMAIL_RETRY_MAX_SECONDS,
        settings.TAKEBOARD_EMAIL_RETRY_BASE_SECONDS * (2 ** max(0, attempts - 1)),
    )


def process_email_outbox_item(outbox_id: int, *, provider: EmailProvider | None = None) -> bool:
    outbox = _claim(outbox_id)
    if outbox is None:
        return False
    try:
        result = (provider or get_email_provider()).send(
            _render_message(outbox), idempotency_key=outbox.event_key
        )
    except EmailProviderError as error:
        with transaction.atomic():
            current = EmailOutbox.objects.select_for_update().get(pk=outbox.pk)
            if current.status == EmailOutbox.Status.PROCESSING:
                current.status = EmailOutbox.Status.FAILED
                current.last_error_code = error.code
                current.available_at = timezone.now() + timedelta(
                    seconds=_retry_delay(current.attempts)
                )
                current.locked_at = None
                current.save(
                    update_fields=[
                        "status",
                        "last_error_code",
                        "available_at",
                        "locked_at",
                        "updated_at",
                    ]
                )
        logger.warning(
            "email_delivery_failed",
            extra={"email_kind": outbox.kind, "error_code": error.code},
        )
        return False
    except Exception:
        with transaction.atomic():
            current = EmailOutbox.objects.select_for_update().get(pk=outbox.pk)
            if current.status == EmailOutbox.Status.PROCESSING:
                current.status = EmailOutbox.Status.FAILED
                current.last_error_code = "provider_unexpected_error"
                current.available_at = timezone.now() + timedelta(
                    seconds=_retry_delay(current.attempts)
                )
                current.locked_at = None
                current.save(
                    update_fields=[
                        "status",
                        "last_error_code",
                        "available_at",
                        "locked_at",
                        "updated_at",
                    ]
                )
        logger.warning(
            "email_delivery_failed",
            extra={"email_kind": outbox.kind, "error_code": "provider_unexpected_error"},
        )
        return False

    with transaction.atomic():
        current = EmailOutbox.objects.select_for_update().get(pk=outbox.pk)
        if current.status != EmailOutbox.Status.PROCESSING:
            return current.status in {EmailOutbox.Status.SENT, EmailOutbox.Status.SUPPRESSED}
        current.status = (
            EmailOutbox.Status.SUPPRESSED if result.suppressed else EmailOutbox.Status.SENT
        )
        current.provider_message_id = result.provider_message_id or ""
        current.sent_at = timezone.now()
        current.locked_at = None
        current.last_error_code = "email_delivery_disabled" if result.suppressed else ""
        current.save(
            update_fields=[
                "status",
                "provider_message_id",
                "sent_at",
                "locked_at",
                "last_error_code",
                "updated_at",
            ]
        )
    logger.info(
        "email_delivery_completed",
        extra={
            "email_kind": outbox.kind,
            "delivery_status": "suppressed" if result.suppressed else "sent",
        },
    )
    return not result.suppressed


def process_pending_email_outbox(limit: int = 100, *, provider: EmailProvider | None = None) -> int:
    if not settings.TAKEBOARD_EMAIL_ENABLED:
        return 0
    outbox_ids = list(
        EmailOutbox.objects.filter(
            Q(
                status__in=[EmailOutbox.Status.PENDING, EmailOutbox.Status.FAILED],
                available_at__lte=timezone.now(),
                waiting_for_refund=False,
            )
            | Q(
                status=EmailOutbox.Status.PROCESSING,
                locked_at__lt=timezone.now()
                - timedelta(seconds=settings.TAKEBOARD_EMAIL_PROCESSING_TIMEOUT_SECONDS),
            )
        )
        .order_by("available_at", "id")
        .values_list("id", flat=True)[:limit]
    )
    return sum(
        process_email_outbox_item(outbox_id, provider=provider) for outbox_id in outbox_ids
    )
