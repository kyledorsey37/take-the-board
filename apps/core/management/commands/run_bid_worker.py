import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import OperationalError, ProgrammingError
from botocore.exceptions import BotoCoreError, ClientError

from apps.bidding.services.finalize_bid import finalize_due_boards
from apps.bidding.services.finalization_queue import (
    FinalizationQueueConfigurationError,
    SqsBidFinalizationConsumer,
    get_queue_config,
    sqs_finalization_enabled,
)
from apps.bidding.services.rules import current_board_rules
from apps.core.sentry import capture_critical_exception
from apps.payments.services.capture_payment import capture_payment
from apps.payments.services.capture_records import reconcile_pending_capture_fees
from apps.payments.services.process_webhooks import process_pending_stripe_events
from apps.moderation.services.payment_actions import process_pending_payment_actions


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Process payment events and finalize due takeovers."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process due challenges once and exit.")
        parser.add_argument(
            "--poll-seconds",
            type=float,
            default=1.0,
            help="Seconds between local free-play finalization checks.",
        )

    def handle(self, *args, **options):
        if not (settings.TAKEBOARD_DEMO_BIDDING_ENABLED or settings.TAKEBOARD_STRIPE_ENABLED):
            raise CommandError("Bid finalization is disabled in this environment.")
        if options["poll_seconds"] <= 0:
            raise CommandError("--poll-seconds must be greater than zero.")
        finalization_mode = str(settings.TAKEBOARD_BID_FINALIZATION_MODE).strip().lower()
        if finalization_mode not in {"polling", "sqs_fifo"}:
            raise CommandError("TAKEBOARD_BID_FINALIZATION_MODE must be polling or sqs_fifo.")

        queue_enabled = sqs_finalization_enabled()
        if queue_enabled:
            try:
                queue_config = get_queue_config()
            except FinalizationQueueConfigurationError as error:
                raise CommandError(str(error)) from error
            consumer = SqsBidFinalizationConsumer(config=queue_config)

        while True:
            try:
                if settings.TAKEBOARD_STRIPE_ENABLED:
                    process_pending_stripe_events()
                    reconcile_pending_capture_fees()
                    process_pending_payment_actions()
                if queue_enabled:
                    consumer.consume_once(wait_seconds=0 if options["once"] else None)
                else:
                    results = finalize_due_boards(
                        rules=current_board_rules(),
                        capture_pending_bid=capture_payment if settings.TAKEBOARD_STRIPE_ENABLED else None,
                    )
                    published_count = sum(result.published for result in results)
                    if results:
                        logger.info(
                            "bid_finalization_completed",
                            extra={"finalized_count": len(results), "published_count": published_count},
                        )
            except (OperationalError, ProgrammingError):
                # The local worker can start before the web service has run migrations.
                logger.info("demo_bid_finalizer_waiting_for_database")
            except (BotoCoreError, ClientError) as error:
                # Queue/provider outages are retried by the next worker pass; no
                # message is acknowledged until the consumer completes safely.
                logger.exception("bid_finalization_queue_unavailable")
                capture_critical_exception(
                    "worker_provider_outage",
                    error,
                    minimum_occurrences=3,
                    window_seconds=60,
                )
                if not options["once"]:
                    time.sleep(options["poll_seconds"])

            if options["once"]:
                return
            if not queue_enabled:
                time.sleep(options["poll_seconds"])
