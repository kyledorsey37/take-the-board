# Payment Flow

The local Stripe sandbox path is implemented at `POST /webhooks/stripe/` and through
the authenticated bid flow. Django requires a fresh, matching, one-time approved
`MessageValidation` before it creates an Embedded Checkout Session with
manual capture, verifies Stripe signatures against the raw request body, stores each
event once in `StripeEvent`, and lets the local worker process authorization,
cancellation, and capture transitions. In production, authorized bids enqueue an
opaque finalization trigger on the configured SQS FIFO queue; local free-play and
the local Stripe sandbox retain Postgres polling when queue mode is not selected.

## Invariants

- No message reaches payment unless it has passed moderation.
- No bid is captured unless it is still a valid winning bid at finalization.
- Browser success redirects are never authoritative.
- Duplicate webhooks and worker retries must be harmless.
- A successful capture immediately publishes the board and guarantees that message for 30 seconds.
- During that guarantee, only the highest authorized challenger remains pending; superseded authorizations must be canceled and never captured.
- The next minimum is based on the greater of the current captured amount and pending challenger amount.
- User-facing bid amounts are whole dollars. Payment records remain stored in cents internally.
- Every successful Stripe capture creates an immutable `PaymentCapture` record with
  the PaymentIntent, charge, gross amount, currency, and a corresponding gross
  `LedgerEntry`. Stripe fee, net, and balance-transaction fields are completed only
  when Stripe makes that accounting data available.
- Every real-money Checkout starts from an immutable `BidConfirmation` snapshot.
  The snapshot records the confirmed amount, message, board price, pending challenger,
  confirmation version, and request context; Checkout rechecks it server-side.
- Risk limits are centralized in `BidRiskConfig`: captured net spend plus active
  authorizations count toward rolling limits, and an open Stripe dispute suspends
  paid bidding immediately.
- A captured takeover creates immutable `PurchaseEvidence` with confirmation,
  account, payment, publication, guarantee, and delivery-end context for disputes.

## Current Local Flow

1. An authenticated user submits a board message.
2. Django applies deterministic policy checks, Redis limits/cache, and the configured
   Bedrock/Nova classifier; provider failure is rejected temporarily.
3. Django rechecks price and risk, then displays a mandatory, compact second-step
   confirmation in the bid modal. It records the exact snapshot server-side for all
   paid bids; only bids above the configured very-high threshold (default $100)
   add the payment acknowledgement and typed confirmation.
4. On explicit confirmation, checkout creation transactionally rechecks the approved
   validation, current board price, risk limits, and confirmation snapshot before
   creating a `Bid` and Stripe Embedded Checkout Session using manual capture.
5. Stripe authorizes the card and sends webhooks through the local Stripe CLI.
6. Django verifies the webhook, stores a `StripeEvent`, and the local worker processes it.
7. Authorization processing checks whether the board has a current takeover
   inside an active guarantee. For a protected board it enqueues
   `{"bid_id": "<opaque UUID>"}` with `MessageGroupId=board-<board id>` and a stable
   per-bid deduplication ID. No message text, display name, payment payload,
   token, or other user data is sent.
8. If the board has no current takeover inside an active guarantee, the worker
   captures and publishes the authorized bid immediately. Otherwise, it keeps
   only the highest authorized challenger during the current guarantee.
9. The worker captures the pending payment only after the guarantee expires, and only if it is still valid.
10. Board state and takeover history update only after successful capture. Publication starts a new 30-second guarantee.
11. The worker processes `charge.updated` and periodically reconciles pending capture
    snapshots so delayed Stripe balance-transaction fee data is attached without
    changing the original captured amount.

After Embedded Checkout reports completion, the browser only observes the bidder's
safe status endpoint. `authorized` means the card authorization succeeded and the
bid is the current pending challenger behind an active protected takeover; it is
rendered as “You're up next,” not as a win. An open board is captured and published
in the worker transaction, so the browser observes `won` instead. The browser stops
polling in the authorized state and returns to the board with
`move=pending` after the visible ten-second return window unless the user stays.
Only a server-observed `won` state renders the success treatment and uses
`move=live`. A short or unavailable status poll renders a non-claiming delayed
message with `move=processing`; browser state never triggers capture or publishing.

In local settings the worker deliberately polls Postgres, so free-play tests do
not require AWS. Select `TAKEBOARD_BID_FINALIZATION_MODE=sqs_fifo` only in an
environment with a valid FIFO queue configuration. Production Stripe settings
fail closed unless that mode is selected and the queue URL/region are valid.

## SQS FIFO finalization boundary

`apps/bidding/services/finalization_queue.py` owns both enqueue and consumption.
The producer runs inside the authorization transaction; if `SendMessage` fails,
the authorization rolls back and the Stripe event remains retryable. Because SQS
FIFO does not support per-message delivery delays, the consumer long-polls one
message at a time and extends visibility for the current authorized bid until
the protected window ends. It then checks the bid's current board and pending-bid
identity under the existing board row lock, and deletes a message only after that
safe handling completes. Missing, duplicate, stale, canceled, outbid, and already
finalized messages are settled without changing state. Unexpected failures leave
the message invisible for bounded exponential retry and allow the queue redrive
policy to move it to the FIFO DLQ.

Required application settings are `TAKEBOARD_BID_FINALIZATION_MODE`,
`TAKEBOARD_SQS_BID_FINALIZATION_QUEUE_URL`, `TAKEBOARD_SQS_BID_FINALIZATION_REGION`,
`TAKEBOARD_SQS_BID_FINALIZATION_WAIT_SECONDS`,
`TAKEBOARD_SQS_BID_FINALIZATION_VISIBILITY_TIMEOUT_SECONDS`,
`TAKEBOARD_SQS_BID_FINALIZATION_RETRY_VISIBILITY_SECONDS`, and
`TAKEBOARD_SQS_BID_FINALIZATION_MAX_RECEIVE_COUNT`. Queue creation, DLQ, IAM,
alerts, and staging smoke testing remain external operational work; see the
[SQS finalization runbook](sqs_bid_finalization_runbook.md).

## Protected Display Window

Every captured takeover receives `guaranteed_until = published_at + 30 seconds`. Higher bids may authorize during this period, but the board holds a single pending challenger rather than a future queue. A new higher authorization replaces and cancels the old pending authorization. At expiration, Stripe capture failure marks that pending bid as `payment_failed`, clears it, and leaves the current message live.

The authoritative business specification is `docs/Take the Board — Updated Bidding, Guarantee, and Chargeback Rules.md`.

## Stripe Webhooks

```text
POST /webhooks/stripe/
```

Requirements:

- CSRF exempt only because it is a verified third-party webhook.
- Verify `Stripe-Signature` against the raw request body.
- Store event IDs with a unique constraint.
- Return 200 for already-stored duplicate events.
- Do not update board state in the webhook request.

`payment_intent.payment_failed` represents a failed payment attempt and must
not be treated as permanently terminal when Stripe can retry the same
PaymentIntent. A later `payment_intent.amount_capturable_updated` for that
PaymentIntent must still be able to authorize the bid. Late failure events must
not downgrade an already authorized or captured bid. The implementation story,
state matrix, and acceptance criteria are in [payment retry after a failed
attempt](payment_retry_after_failed_attempt_story.md).

While a Checkout Session remains open, each failed card attempt increments the
bid's local payment-failure counter and timestamp for risk controls but leaves
the bid in `checkout_created`. Only a canceled PaymentIntent invalidates that
retryable checkout; `payment_failed` is reserved for a failed capture after an
authorization, where the pending challenger is cleared and the live board is
unchanged.

The local receiver can be exercised with the Stripe CLI:

```bash
stripe listen --forward-to http://127.0.0.1:8000/webhooks/stripe/
```

Use the signing secret printed by `stripe listen` as the local `STRIPE_WEBHOOK_SECRET`.
Dashboard-created endpoints have different signing secrets for test and live mode.

## Ledger

Captured bids, refunds, chargebacks, and adjustments must be recorded as ledger entries. Historical bid and takeover records should not be deleted for refunds or disputes.

`PaymentCapture` is the provider-accounting companion to the ledger: it contains
only stable identifiers and money fields needed to reconcile a Stripe capture, not a
raw provider payload or card data. A pending fee status is expected briefly because
Stripe can create the balance transaction asynchronously. For Stripe accounts where
Balance Transaction fees are not available, finance reconciliation must use Stripe's
Payment fees report rather than inventing a local fee value.

After deploying this feature, backfill prior Stripe captures once with:

```bash
python manage.py reconcile_payment_captures
```

It only reads historical PaymentIntents for captured, refunded, or disputed bids
that do not yet have a `PaymentCapture`, then writes the same idempotent snapshot
used for new captures.

## Refunds And Disputes

Refunds and disputes are admin-reviewed operational workflows. They should update payment state and ledger entries while preserving historical records for audit.

Before taking live money, the authenticated user experience also needs a
post-purchase support surface. It should show active and historical takeovers,
the state of each bid and payment, a safe receipt or transaction reference that
does not expose card details, and refund/dispute status. Failed, delayed, and
outbid bids need plain-language outcomes and a route to support. The existing
bidder-owned status endpoint supports checkout polling but is not a replacement
for an account history view. See `docs/launch_readiness.md`.

Paid bidding also requires a one-time, versioned 18+ acknowledgement on the
account. The first paid-bid form collects it before a Checkout Session is
created; the confirmation and Checkout service boundaries recheck it. The
acknowledgement timestamp and version are copied to `PurchaseEvidence` when a
paid takeover is captured. Local free-play does not collect this acknowledgement.

Captured bids in account history include a pre-addressed support email action.
It includes only a safe Take the Board reference, board, amount, status, and date,
so customers have a clear way to ask about a charge before considering a dispute.

`charge.dispute.created` is processed asynchronously and idempotently: it stores the
Stripe dispute ID on the bid, records a chargeback ledger entry, increments the user's
dispute history, and suspends paid bidding while the dispute is open. Users may still browse.

When moderation removes a captured paid message, the refund is a partial refund
equal to the capture's gross amount less Stripe's actual recorded processing fee.
The worker leaves the durable remediation action pending until the associated
`PaymentCapture` has fee data; it never estimates a fee or sends a full refund
as a fallback. The resulting `LedgerEntry(type=REFUND)` is the exact negative
amount returned to the customer.

After a successful refund action commits its bid status and refund ledger entry,
the transaction completes the one customer moderation-resolution email intent
created when the message was removed. That email explains the removal and shows
the amount paid, the actual Stripe processing fee, and the net refund issued;
the removed message text and payment-provider identifiers are omitted. A paid
removal waits for the refund action before delivery, so it does not produce a
separate removal email and refund email. The durable outbox record is delivered
asynchronously with a stable provider idempotency key. Email delivery failure
never rolls back or blocks the payment or moderation state transition. See
[backend overview](backend_overview.md) for the provider and retry
configuration; delivery remains disabled until the sender and provider are
configured.

## Weekly Reset Interaction

The weekly reset clears live board state without deleting captured payment history.
Any pending authorized challenger is canceled before the board is cleared. In a
Stripe-enabled environment, the reset command must be invoked with the payment
cancellation callback so the PaymentIntent authorization is released as well as
the local bid being marked canceled.
