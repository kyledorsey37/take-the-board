# Payment Flow

The local Stripe sandbox path is implemented at `POST /webhooks/stripe/` and through
the authenticated bid flow. Django requires a fresh, matching, one-time approved
`MessageValidation` before it creates an Embedded Checkout Session with
manual capture, verifies Stripe signatures against the raw request body, stores each
event once in `StripeEvent`, and lets the local worker process authorization,
cancellation, and capture transitions. SQS FIFO delivery remains later production
work.

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
3. Django rechecks price and risk, then displays a mandatory confirmation screen.
4. On explicit confirmation, checkout creation transactionally rechecks the approved
   validation, current board price, risk limits, and confirmation snapshot before
   creating a `Bid` and Stripe Embedded Checkout Session using manual capture.
5. Stripe authorizes the card and sends webhooks through the local Stripe CLI.
6. Django verifies the webhook, stores a `StripeEvent`, and the local worker processes it.
7. The worker keeps only the highest authorized challenger during the current guarantee.
8. The worker captures the pending payment only after the guarantee expires, and only if it is still valid.
9. Board state and takeover history update only after successful capture. Publication starts a new 30-second guarantee.
10. The worker processes `charge.updated` and periodically reconciles pending capture
    snapshots so delayed Stripe balance-transaction fee data is attached without
    changing the original captured amount.

In the current local slice, message moderation is not yet connected to Bedrock/Nova and
the worker polls Postgres rather than consuming SQS FIFO messages. Do not use this mode
for real cards or production traffic.

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

`charge.dispute.created` is processed asynchronously and idempotently: it stores the
Stripe dispute ID on the bid, records a chargeback ledger entry, increments the user's
dispute history, and suspends paid bidding while the dispute is open. Users may still browse.

When moderation removes a captured paid message, the refund is a partial refund
equal to the capture's gross amount less Stripe's actual recorded processing fee.
The worker leaves the durable remediation action pending until the associated
`PaymentCapture` has fee data; it never estimates a fee or sends a full refund
as a fallback. The resulting `LedgerEntry(type=REFUND)` is the exact negative
amount returned to the customer.

## Weekly Reset Interaction

The weekly reset clears live board state without deleting captured payment history.
Any pending authorized challenger is canceled before the board is cleared. In a
Stripe-enabled environment, the reset command must be invoked with the payment
cancellation callback so the PaymentIntent authorization is released as well as
the local bid being marked canceled.
