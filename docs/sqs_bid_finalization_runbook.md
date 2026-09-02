# SQS FIFO bid-finalization runbook

This queue is only for Take the Board bid-finalization triggers. It is not a
general application job queue, and queue messages never contain user text,
display names, payment payloads, tokens, or raw webhook data.

## Queue and DLQ

Create a FIFO queue whose URL ends in `.fifo` and configure:

- `FifoQueue=true`.
- Explicit message deduplication (`ContentBasedDeduplication=false`). The app
  supplies `bid-finalization-v1-<bid public UUID>` as the stable deduplication ID.
- `DeduplicationScope=messageGroup` and `FifoThroughputLimit=perMessageGroupId`
  so one board serializes while different boards can make progress independently.
- A FIFO DLQ with a redrive policy of `maxReceiveCount=5` (or the value selected
  in `TAKEBOARD_SQS_BID_FINALIZATION_MAX_RECEIVE_COUNT`). Keep DLQ retention long
  enough for operator review; do not blindly replay messages without checking the
  bid and payment state in Django Admin.
- Queue visibility timeout at least the configured
  `TAKEBOARD_SQS_BID_FINALIZATION_VISIBILITY_TIMEOUT_SECONDS` (default 120s),
  with enough headroom for the Stripe capture API and database transaction.
  The consumer applies bounded retry visibility (default 30s, exponential, capped
  at 900s).
- Queue receive wait time of 20 seconds. The worker uses SQS long polling and
  deletes only after safe database handling.

## IAM and application configuration

Grant the worker task role `sqs:ReceiveMessage`, `sqs:DeleteMessage`,
`sqs:ChangeMessageVisibility`, `sqs:GetQueueAttributes`, and `sqs:SendMessage`
on the queue. The web task only stores the verified Stripe event; the worker
processes it and publishes the finalization trigger. Do not add static AWS keys
to the application; ECS task roles are the production credential source.

Set:

```text
TAKEBOARD_BID_FINALIZATION_MODE=sqs_fifo
TAKEBOARD_SQS_BID_FINALIZATION_QUEUE_URL=https://sqs.<region>.amazonaws.com/<account>/<name>.fifo
TAKEBOARD_SQS_BID_FINALIZATION_REGION=<region>
TAKEBOARD_SQS_BID_FINALIZATION_WAIT_SECONDS=20
TAKEBOARD_SQS_BID_FINALIZATION_VISIBILITY_TIMEOUT_SECONDS=120
TAKEBOARD_SQS_BID_FINALIZATION_RETRY_VISIBILITY_SECONDS=30
TAKEBOARD_SQS_BID_FINALIZATION_MAX_RECEIVE_COUNT=5
```

Production settings fail closed when Stripe is enabled without SQS mode or when
the selected queue URL/region is invalid. The local default remains
`TAKEBOARD_BID_FINALIZATION_MODE=polling`; normal free-play and local Stripe
sandbox tests therefore need no AWS queue.

## Staging smoke test

1. Verify the staging web and worker task roles can send, receive, change
   visibility, and delete a message.
2. Place a Stripe test-mode bid on a board with an active guarantee. Confirm the
   authorization webhook creates one queue message whose body contains only the
   opaque bid ID, with `MessageGroupId=board-<id>`.
3. Run `python manage.py run_bid_worker` and confirm the message is not captured
   before `guaranteed_until`, then is captured and deleted afterward.
4. Deliver the same message twice and confirm no duplicate takeover, capture, or
   ledger entry. Deliver a stale/canceled bid message and confirm it is settled
   without changing the current board.
5. Force a transient database/provider failure. Confirm the message remains
   unacknowledged, visibility is extended, and the configured receive-count limit
   eventually sends it to the FIFO DLQ. Alerting should cover worker failures,
   queue depth/age, and DLQ messages before enabling production traffic.
