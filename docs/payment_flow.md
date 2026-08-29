# Payment Flow

The local Stripe sandbox path is implemented at `POST /webhooks/stripe/` and through
the authenticated bid flow. Django creates a one-time Embedded Checkout Session with
manual capture, verifies Stripe signatures against the raw request body, stores each
event once in `StripeEvent`, and lets the local worker process authorization,
cancellation, and capture transitions. Ledger entries, Bedrock/Nova moderation, and
SQS FIFO delivery remain later production work.

## Invariants

- No message reaches payment unless it has passed moderation.
- No bid is captured unless it is still a valid winning bid at finalization.
- Browser success redirects are never authoritative.
- Duplicate webhooks and worker retries must be harmless.
- A successful capture immediately publishes the board and guarantees that message for 30 seconds.
- During that guarantee, only the highest authorized challenger remains pending; superseded authorizations must be canceled and never captured.
- The next minimum is based on the greater of the current captured amount and pending challenger amount.
- User-facing bid amounts are whole dollars. Payment records remain stored in cents internally.

## Current Local Flow

1. An authenticated user submits a board message.
2. Checkout creation rechecks the current board price and creates a `Bid`.
3. Django creates a Stripe Embedded Checkout Session using manual capture.
4. Stripe authorizes the card and sends webhooks through the local Stripe CLI.
5. Django verifies the webhook, stores a `StripeEvent`, and the local worker processes it.
6. The worker keeps only the highest authorized challenger during the current guarantee.
7. The worker captures the pending payment only after the guarantee expires, and only if it is still valid.
8. Board state and takeover history update only after successful capture. Publication starts a new 30-second guarantee.

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
stripe listen --forward-to http://127.0.0.1:8001/webhooks/stripe/
```

Use the signing secret printed by `stripe listen` as the local `STRIPE_WEBHOOK_SECRET`.
Dashboard-created endpoints have different signing secrets for test and live mode.

## Ledger

Captured bids, refunds, chargebacks, and adjustments must be recorded as ledger entries. Historical bid and takeover records should not be deleted for refunds or disputes.

## Refunds And Disputes

Refunds and disputes are admin-reviewed operational workflows. They should update payment state and ledger entries while preserving historical records for audit.

## Weekly Reset Interaction

The weekly reset clears live board state without deleting captured payment history.
Any pending authorized challenger is canceled before the board is cleared. In a
Stripe-enabled environment, the reset command must be invoked with the payment
cancellation callback so the PaymentIntent authorization is released as well as
the local bid being marked canceled.
