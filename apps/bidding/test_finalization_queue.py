import json
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.boards.models import Board
from apps.schools.models import Competition, Entity

from .models import Bid
from .services.finalization_queue import (
    FinalizationQueueConfigurationError,
    FinalizationQueueConfig,
    SqsBidFinalizationConsumer,
    enqueue_bid_finalization,
    get_queue_config,
)
from apps.payments.models import StripeEvent
from apps.payments.services.process_webhooks import process_stripe_event


class FakeSqsClient:
    def __init__(self, messages=None):
        self.messages = list(messages or [])
        self.sent = []
        self.deleted = []
        self.visibility_changes = []

    def send_message(self, **kwargs):
        self.sent.append(kwargs)

    def receive_message(self, **kwargs):
        self.receive_kwargs = kwargs
        if not self.messages:
            return {}
        return {"Messages": [self.messages.pop(0)]}

    def delete_message(self, **kwargs):
        self.deleted.append(kwargs)

    def change_message_visibility(self, **kwargs):
        self.visibility_changes.append(kwargs)


@override_settings(
    TAKEBOARD_BID_FINALIZATION_MODE="sqs_fifo",
    TAKEBOARD_SQS_BID_FINALIZATION_QUEUE_URL="https://sqs.us-east-1.amazonaws.com/123/bids.fifo",
    TAKEBOARD_SQS_BID_FINALIZATION_REGION="us-east-1",
)
class FinalizationQueueTests(TestCase):
    def setUp(self):
        competition = Competition.objects.create(name="Football", slug="football", sport="Football")
        self.school = Entity.objects.create(
            competition=competition,
            name="Alabama",
            slug="alabama",
            short_name="Alabama",
            group_name="SEC",
            accent_color="#000000",
        )
        self.other_school = Entity.objects.create(
            competition=competition,
            name="Auburn",
            slug="auburn",
            short_name="Auburn",
            group_name="SEC",
            accent_color="#000000",
        )
        self.board = Board.objects.create(entity=self.school)
        self.other_board = Board.objects.create(entity=self.other_school)
        self.player = UserProfile.objects.create(
            cognito_sub="queue-test",
            email="queue@example.invalid",
            display_name="QueueFan",
        )

    def bid(self, board=None):
        return Bid.objects.create(
            board=board or self.board,
            bidder=self.player,
            represented_entity=self.other_school,
            message="PRIVATE MESSAGE MUST NOT BE QUEUED",
            amount_cents=100,
            status=Bid.Status.AUTHORIZED,
            authorized_at=timezone.now(),
        )

    @override_settings(TAKEBOARD_SQS_BID_FINALIZATION_QUEUE_URL="https://sqs.example/bids")
    def test_selected_queue_mode_rejects_a_non_fifo_queue(self):
        with self.assertRaises(FinalizationQueueConfigurationError):
            get_queue_config()

    def test_grouping_and_deduplication_are_stable_and_payload_is_opaque(self):
        first = self.bid()
        second = self.bid(self.other_board)
        client = FakeSqsClient()

        enqueue_bid_finalization(bid=first, client=client, now=timezone.now())
        enqueue_bid_finalization(bid=first, client=client, now=timezone.now())
        enqueue_bid_finalization(bid=second, client=client, now=timezone.now())

        self.assertEqual(client.sent[0]["MessageGroupId"], f"board-{self.board.id}")
        self.assertEqual(client.sent[2]["MessageGroupId"], f"board-{self.other_board.id}")
        self.assertEqual(client.sent[0]["MessageDeduplicationId"], client.sent[1]["MessageDeduplicationId"])
        self.assertEqual(json.loads(client.sent[0]["MessageBody"]), {"bid_id": str(first.public_id)})
        self.assertNotIn("PRIVATE MESSAGE", client.sent[0]["MessageBody"])

    def test_producer_uses_guarantee_expiry_as_bounded_fifo_delay(self):
        bid = self.bid()
        client = FakeSqsClient()
        now = timezone.now()

        enqueue_bid_finalization(
            bid=bid,
            client=client,
            now=now,
            due_at=now + timedelta(seconds=31),
        )

        self.assertEqual(client.sent[0]["DelaySeconds"], 31)

    def test_duplicate_delivery_is_acknowledged_after_harmless_processing(self):
        bid = self.bid()
        bid.board.pending_bid = bid
        bid.board.guaranteed_until = timezone.now() + timedelta(minutes=1)
        bid.board.save(update_fields=["pending_bid", "guaranteed_until"])
        message = {
            "Body": json.dumps({"bid_id": str(bid.public_id)}),
            "ReceiptHandle": "receipt-1",
            "Attributes": {"MessageGroupId": f"board-{self.board.id}", "ApproximateReceiveCount": "1"},
        }
        client = FakeSqsClient([message, {**message, "ReceiptHandle": "receipt-2"}])
        consumer = SqsBidFinalizationConsumer(
            client=client,
            config=FinalizationQueueConfig(
                queue_url="https://sqs.example/bids.fifo",
                region="us-east-1",
                wait_seconds=20,
                visibility_timeout_seconds=120,
                retry_visibility_seconds=30,
                max_receive_count=5,
            ),
        )

        self.assertEqual(consumer.consume_once(), 1)
        self.assertEqual(consumer.consume_once(), 1)
        self.assertEqual([item["ReceiptHandle"] for item in client.deleted], ["receipt-1", "receipt-2"])
        self.assertEqual(client.receive_kwargs["WaitTimeSeconds"], 20)

    def test_stale_bid_message_is_settled_without_finalizing_new_pending_bid(self):
        stale = self.bid()
        current = self.bid()
        self.board.pending_bid = current
        self.board.guaranteed_until = timezone.now() - timedelta(seconds=1)
        self.board.save(update_fields=["pending_bid", "guaranteed_until"])
        message = {
            "Body": json.dumps({"bid_id": str(stale.public_id)}),
            "ReceiptHandle": "receipt-stale",
            "Attributes": {"MessageGroupId": f"board-{self.board.id}", "ApproximateReceiveCount": "1"},
        }
        client = FakeSqsClient([message])
        consumer = SqsBidFinalizationConsumer(
            client=client,
            config=FinalizationQueueConfig("https://sqs.example/bids.fifo", "us-east-1", 20, 120, 30, 5),
        )

        consumer.consume_once()

        self.board.refresh_from_db()
        self.assertEqual(self.board.pending_bid_id, current.id)
        self.assertEqual(client.deleted[0]["ReceiptHandle"], "receipt-stale")

    def test_processing_failure_changes_visibility_and_does_not_acknowledge(self):
        bid = self.bid()
        message = {
            "Body": json.dumps({"bid_id": str(bid.public_id)}),
            "ReceiptHandle": "receipt-fail",
            "Attributes": {"MessageGroupId": f"board-{self.board.id}", "ApproximateReceiveCount": "2"},
        }
        client = FakeSqsClient([message])
        consumer = SqsBidFinalizationConsumer(
            client=client,
            config=FinalizationQueueConfig("https://sqs.example/bids.fifo", "us-east-1", 20, 120, 30, 5),
        )

        with patch("apps.bidding.services.finalization_queue._finalize_message", side_effect=RuntimeError("transient")):
            consumer.consume_once()

        self.assertEqual(client.deleted, [])
        self.assertEqual(client.visibility_changes[0]["VisibilityTimeout"], 60)

    @patch("apps.payments.services.process_webhooks.enqueue_bid_finalization")
    def test_authorization_transition_enqueues_inside_the_payment_event_boundary(self, enqueue):
        bid = self.bid()
        bid.status = Bid.Status.CHECKOUT_CREATED
        bid.save(update_fields=["status"])
        StripeEvent.objects.create(
            event_id="evt_queue_authorized",
            event_type="payment_intent.amount_capturable_updated",
            payload={
                "data": {
                    "object": {
                        "id": "pi_queue_123",
                        "metadata": {"bid_id": str(bid.public_id)},
                    }
                }
            },
        )

        process_stripe_event("evt_queue_authorized")

        bid.refresh_from_db()
        self.assertEqual(bid.status, Bid.Status.AUTHORIZED)
        enqueue.assert_called_once()
        self.assertEqual(enqueue.call_args.kwargs["bid"].id, bid.id)
