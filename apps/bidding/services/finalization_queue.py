"""SQS FIFO producer/consumer boundary for bid finalization.

Only opaque bid identifiers are placed on the queue.  The database remains the
source of truth: a message can trigger a finalization only while its bid is the
board's current pending challenger and the protected display window has ended.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import boto3
from django.conf import settings
from django.utils import timezone

from apps.bidding.models import Bid
from apps.bidding.services.finalize_bid import FinalizationResult, finalize_due_board
from apps.bidding.services.rules import current_board_rules
from apps.payments.services.capture_payment import capture_payment


logger = logging.getLogger(__name__)


class FinalizationQueueConfigurationError(RuntimeError):
    """The selected queue mode is not safe to run."""


@dataclass(frozen=True)
class FinalizationQueueConfig:
    queue_url: str
    region: str
    wait_seconds: int
    visibility_timeout_seconds: int
    retry_visibility_seconds: int
    max_receive_count: int


def sqs_finalization_enabled() -> bool:
    return str(settings.TAKEBOARD_BID_FINALIZATION_MODE).strip().lower() == "sqs_fifo"


def get_queue_config() -> FinalizationQueueConfig:
    if not sqs_finalization_enabled():
        raise FinalizationQueueConfigurationError("SQS FIFO finalization is not enabled.")
    queue_url = str(
        settings.TAKEBOARD_SQS_BID_FINALIZATION_QUEUE_URL
        or getattr(settings, "SQS_BID_FINALIZATION_QUEUE_URL", "")
        or ""
    ).strip()
    region = str(settings.TAKEBOARD_SQS_BID_FINALIZATION_REGION or "").strip()
    wait_seconds = int(settings.TAKEBOARD_SQS_BID_FINALIZATION_WAIT_SECONDS)
    visibility_timeout = int(settings.TAKEBOARD_SQS_BID_FINALIZATION_VISIBILITY_TIMEOUT_SECONDS)
    retry_visibility = int(settings.TAKEBOARD_SQS_BID_FINALIZATION_RETRY_VISIBILITY_SECONDS)
    max_receive_count = int(settings.TAKEBOARD_SQS_BID_FINALIZATION_MAX_RECEIVE_COUNT)
    if not queue_url or not queue_url.endswith(".fifo"):
        raise FinalizationQueueConfigurationError("A .fifo bid finalization queue URL is required.")
    if not region:
        raise FinalizationQueueConfigurationError(
            "An AWS region is required for SQS FIFO finalization."
        )
    if not 0 <= wait_seconds <= 20:
        raise FinalizationQueueConfigurationError(
            "SQS long-poll wait must be between 0 and 20 seconds."
        )
    if not 1 <= visibility_timeout <= 43200:
        raise FinalizationQueueConfigurationError("SQS visibility timeout is out of bounds.")
    if not 1 <= retry_visibility <= 900:
        raise FinalizationQueueConfigurationError("SQS retry visibility is out of bounds.")
    if not 1 <= max_receive_count <= 1000:
        raise FinalizationQueueConfigurationError("SQS maximum receive count is out of bounds.")
    return FinalizationQueueConfig(
        queue_url=queue_url,
        region=region,
        wait_seconds=wait_seconds,
        visibility_timeout_seconds=visibility_timeout,
        retry_visibility_seconds=retry_visibility,
        max_receive_count=max_receive_count,
    )


def _sqs_client(config: FinalizationQueueConfig):
    return boto3.client("sqs", region_name=config.region)


def _message_values(*, bid: Bid) -> tuple[str, str, str]:
    """Return body, board group, and stable deduplication id."""
    body = json.dumps({"bid_id": str(bid.public_id)}, separators=(",", ":"), sort_keys=True)
    group_id = f"board-{bid.board_id}"
    deduplication_id = f"bid-finalization-v1-{bid.public_id}"
    return body, group_id, deduplication_id


def enqueue_bid_finalization(
    *,
    bid: Bid,
    due_at: datetime | None = None,
    now: datetime | None = None,
    client: Any | None = None,
) -> bool:
    """Publish one authorization trigger; polling mode deliberately does nothing.

    The caller invokes this inside the authorization transaction.  A provider
    failure therefore rolls back the local authorization and leaves the Stripe
    event unprocessed for a later retry.
    """
    if not sqs_finalization_enabled():
        return False
    config = get_queue_config()
    body, group_id, deduplication_id = _message_values(bid=bid)
    now = now or timezone.now()
    delay_seconds = 0
    if due_at is not None and due_at > now:
        delay_seconds = max(0, math.ceil((due_at - now).total_seconds()))
        if delay_seconds > 900:
            raise FinalizationQueueConfigurationError(
                "SQS FIFO delay cannot cover a protected window longer than 15 minutes."
            )
    (client or _sqs_client(config)).send_message(
        QueueUrl=config.queue_url,
        MessageBody=body,
        MessageGroupId=group_id,
        MessageDeduplicationId=deduplication_id,
        DelaySeconds=delay_seconds,
    )
    return True


def _parse_message(message: dict[str, Any]) -> tuple[UUID, str] | None:
    """Parse only the opaque id and group metadata; reject all other shapes."""
    try:
        payload = json.loads(message.get("Body", ""))
        bid_id = UUID(str(payload["bid_id"]))
        if set(payload) != {"bid_id"}:
            return None
        attributes = message.get("MessageSystemAttributes") or message.get("Attributes") or {}
        group_id = str(attributes.get("MessageGroupId") or "")
        if not group_id:
            return None
        return bid_id, group_id
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _finalize_message(*, bid: Bid, group_id: str) -> FinalizationResult | None:
    if group_id != f"board-{bid.board_id}":
        return None
    return finalize_due_board(
        board_id=bid.board_id,
        expected_pending_bid_id=bid.id,
        rules=current_board_rules(),
        capture_pending_bid=capture_payment if settings.TAKEBOARD_STRIPE_ENABLED else None,
    )


class SqsBidFinalizationConsumer:
    """One-message-at-a-time consumer; SQS FIFO enforces per-board ordering."""

    def __init__(self, *, client: Any | None = None, config: FinalizationQueueConfig | None = None):
        self.config = config or get_queue_config()
        self.client = client or _sqs_client(self.config)

    def consume_once(self, *, wait_seconds: int | None = None) -> int:
        response = self.client.receive_message(
            QueueUrl=self.config.queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=self.config.wait_seconds if wait_seconds is None else wait_seconds,
            VisibilityTimeout=self.config.visibility_timeout_seconds,
            MessageSystemAttributeNames=["MessageGroupId", "ApproximateReceiveCount"],
        )
        messages = response.get("Messages") or []
        if not messages:
            return 0
        message = messages[0]
        receipt_handle = message.get("ReceiptHandle")
        parsed = _parse_message(message)
        if parsed is None or not receipt_handle:
            if receipt_handle:
                self.client.delete_message(
                    QueueUrl=self.config.queue_url,
                    ReceiptHandle=receipt_handle,
                )
            logger.warning("sqs_bid_finalization_message_settled_invalid")
            return 1

        bid_public_id, group_id = parsed
        bid = Bid.objects.select_related("board").filter(public_id=bid_public_id).first()
        if bid is None:
            self.client.delete_message(QueueUrl=self.config.queue_url, ReceiptHandle=receipt_handle)
            logger.info("sqs_bid_finalization_message_settled_missing_bid")
            return 1
        try:
            _finalize_message(bid=bid, group_id=group_id)
        except Exception:
            attributes = message.get("MessageSystemAttributes") or message.get("Attributes") or {}
            receive_count = int(attributes.get("ApproximateReceiveCount") or 1)
            if receive_count >= self.config.max_receive_count:
                logger.error("sqs_bid_finalization_retry_limit_reached", extra={"bid_id": bid.id})
            else:
                visibility = min(
                    900,
                    self.config.retry_visibility_seconds * (2 ** max(0, receive_count - 1)),
                )
                self.client.change_message_visibility(
                    QueueUrl=self.config.queue_url,
                    ReceiptHandle=receipt_handle,
                    VisibilityTimeout=visibility,
                )
                logger.warning("sqs_bid_finalization_processing_failed", extra={"bid_id": bid.id})
            return 1

        # A duplicate, stale, canceled, or already-finalized message reaches
        # here harmlessly and is acknowledged only after the DB check/transaction.
        self.client.delete_message(QueueUrl=self.config.queue_url, ReceiptHandle=receipt_handle)
        return 1
