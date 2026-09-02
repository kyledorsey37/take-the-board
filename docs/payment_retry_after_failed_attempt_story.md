# Payment retry after a failed card attempt

## Story

As a bidder, I want to retry a declined card in the same Stripe Checkout
window so that a failed payment attempt does not permanently invalidate an
otherwise valid takeover.

As the operator, I want late, duplicate, and out-of-order Stripe events to be
safe so that an uncaptured authorization is never stranded and a successful
authorization is not downgraded by an earlier failed attempt.

## Why this is needed

Stripe can reuse the same PaymentIntent after a card attempt fails. A later
successful attempt can move that PaymentIntent to `requires_capture` when the
Checkout flow uses manual capture. See the [Stripe PaymentIntent lifecycle]
and [payment status documentation].

On 2026-09-02 in dev, one Checkout window produced this sequence:

1. The first card attempt emitted `payment_intent.payment_failed`.
2. A second failed attempt emitted another `payment_intent.payment_failed`.
3. The bidder entered a valid card in the same Checkout window.
4. Stripe emitted `payment_intent.amount_capturable_updated` and
   `checkout.session.completed` for the same PaymentIntent.
5. The local bid remained `payment_failed`, while Stripe reported
   `requires_capture` with the full amount capturable.

The current behavior treats the first failed attempt as a terminal bid state.
The later authorization handler then ignores the bid, leaving the successful
authorization uncaptured and the browser showing “Payment not completed.”

## Scope

- Stripe Checkout with manual capture.
- `payment_intent.payment_failed`,
  `payment_intent.amount_capturable_updated`,
  `payment_intent.canceled`, and `payment_intent.succeeded` handling.
- Checkout status polling and its terminal-state presentation.
- SQS/local finalization enqueue behavior after a successful authorization.
- Idempotency and out-of-order event tests.

This story does not change prices, guarantee rules, capture eligibility, or
the duplicate-event storage contract.

## Intended state behavior

| Local state | Stripe event | Intended result |
| --- | --- | --- |
| `checkout_created` | `payment_intent.payment_failed` | Keep the bid retryable while the PaymentIntent/Checkout flow can accept another payment method. Do not strand an authorization or make the successful-retry path impossible. |
| `checkout_created` or retryable checkout state | `payment_intent.amount_capturable_updated` | Move the bid to `authorized`, set the PaymentIntent ID, set the board pending bid, and enqueue exactly one finalization trigger. |
| `authorized` / `processing` / `won` | Late `payment_intent.payment_failed` | Ignore the stale failure; never downgrade a later successful authorization or captured takeover. |
| Any retryable state | `payment_intent.canceled` | Mark the bid `auth_canceled`, clear it from `board.pending_bid` when applicable, and do not enqueue or capture it. |
| `authorized` at guarantee expiry | Capture error or non-success response | Mark the bid `payment_failed`, clear the pending bid, leave the current board message unchanged, and settle the queue message according to the existing retry policy. |
| Any state | Duplicate event ID | Return HTTP 200, process it once, and produce no duplicate authorization, queue message, capture, or ledger entry. |

The exact retryable local representation may be an existing state or a small
new payment-attempt record/state, but it must preserve the distinction between
“this card attempt failed” and “this bid can never complete.” The browser must
continue to use server-authoritative bid state; analytics must not determine
payment outcome.

## Acceptance criteria

- A test-mode card decline followed by the standard successful test card in
  the same Checkout window results in one authorized bid, one finalization
  trigger, and a normal capture/win.
- A failed payment attempt does not cause the polling UI to exit the Checkout
  flow as terminal if Stripe can still accept a retry.
- A late failure event cannot change an `authorized`, `processing`, or `won`
  bid to `payment_failed`.
- A successful authorization received after one or more failed attempts can
  transition the bid and board normally.
- The authorization path remains transactional and idempotent; duplicate
  webhook delivery cannot create duplicate queue work or payment records.
- A canceled PaymentIntent releases/invalidates the authorization, clears any
  pending challenger, and cannot later be captured by the worker.
- A deterministic capture failure after authorization still follows the
  existing safe path: no publication, no capture ledger entry, no duplicate
  retry side effect, and a clear terminal outcome.
- A dev smoke test verifies the above with Stripe test mode, and the orphaned
  authorization scenario is explicitly checked in Stripe and the local
  database.
- Logs remain free of card data, secrets, raw Stripe payloads, and user message
  text; they may include safe event types, request IDs, and internal outcome
  labels.

## Suggested implementation and test plan

1. Separate payment-attempt failure handling from terminal bid failure.
2. Make authorization processing accept a retryable bid and reject only truly
   invalid, canceled, outbid, or already-finalized bids.
3. Make terminal state transitions monotonic where appropriate so stale
   failure events cannot overwrite a successful state.
4. Update the checkout polling copy/termination rules to match the retryable
   state.
5. Add service tests for failed-then-successful attempts on one PaymentIntent,
   successful-then-late-failure ordering, duplicate event delivery, canceled
   authorization, and capture failure after authorization.
6. Run the real dev smoke test and confirm the SQS queue drains and Stripe has
   no remaining uncaptured test authorization from the scenario.

## Out of scope but operationally required

If a bug or operator action leaves a PaymentIntent in `requires_capture` while
the local bid is terminal, the operator needs a safe reconciliation/cancel
path before live payments. Test-mode orphaned authorizations should be canceled
after investigation; production cases should be reviewed before any manual
state repair.

[Stripe PaymentIntent lifecycle]: https://docs.stripe.com/payments/paymentintents/lifecycle
[payment status documentation]: https://docs.stripe.com/payments/payment-intents/verifying-status
