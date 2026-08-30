# Content Reporting and Payment Remediation UI Test Plan

**Status:** Active living document  
**Scope:** Public reporting, paid-bid confirmation and risk controls, moderator
review, Stripe capture snapshots, disputes, and fee-deducted refunds for Take
the Board.

Update this document whenever the public reporting flow, Admin workflow,
payment policy, or a relevant UI contract changes. Record test results in a PR,
issue, or release note; do not add real customer content, email addresses,
payment IDs, or card data here.

## Test environment

Run these scenarios against a local or staging environment only, using Stripe
test mode. Do not test moderation removals or refunds against real customers.

Before testing:

1. Start the app and its worker:

   ```bash
   docker compose up -d
   docker compose ps
   ```

   `web`, `demo-finalizer`, and the database must be running. The
   `demo-finalizer` worker processes Stripe events, capture fee reconciliation,
   and queued moderation payment actions.

2. Apply migrations:

   ```bash
   docker compose exec -T web python manage.py migrate
   ```

3. Verify a public board after the migration before testing any UI flow:

   ```bash
   curl --fail --silent --show-error http://127.0.0.1:8001/schools/alabama/
   ```

   The response must be `200` and render the school page. Do not continue after
   a Django error page, missing-column error, or a stale container response.

4. For Stripe scenarios, use a Stripe CLI webhook forwarder configured with the
   local webhook secret. Verify that `payment_intent.amount_capturable_updated`,
   `payment_intent.succeeded`, `charge.updated`, and `charge.dispute.created`
   events reach the app.

5. Prepare three accounts:

   - **Controller:** posts the board message.
   - **Reporter:** files a report; use a second reporter for the multiple-report
     scenario.
   - **Moderator:** a Django Admin user.

6. Keep a note of the school board and the public takeover/bid IDs for the test
   run. Use neutral test messages only.

## Core public-board tests

### 1. Report affordance and sign-in prompts

| Scenario | Steps | Expected behavior |
| --- | --- | --- |
| Signed-out visitor reports a live message | Open a school board while signed out and select **Report message** under the current message. | The button is visible. A sign-in dialog opens with reporting-specific copy: “You need to be signed in to report a public board message.” No report is created. |
| Signed-out visitor takes a board | From the same signed-out page select **Take the board**. | The sign-in dialog uses takeover-specific copy: “You need to be signed in to take the board.” It must not reuse the report wording. |
| Signed-in reporter opens a report dialog | Sign in as Reporter, return to the board, and select **Report message** on the current message and one history row. | The matching dialog opens each time. It shows the category choices and **Submit report**. Closing it does not change data. |
| Removed message | After completing the moderator removal scenario, return to the board and history. | Removed content is redacted as “Message removed for violating community guidelines.” It has no report button or report dialog. |

### 2. Submit and deduplicate reports

| Scenario | Steps | Expected behavior |
| --- | --- | --- |
| First report | As Reporter, select one category and submit. | The modal shows “Thanks. We’ll review this message.” without a full-page navigation. Django Admin contains one open **Message report case** and one immutable **Message report**. |
| Missing category | Open a fresh report dialog and try to submit without choosing a category. | Browser validation prevents submission; no report is created. |
| Same reporter twice | Submit the same takeover again as the same Reporter. | The UI responds that the message is no longer accepting reports. The case still has exactly one report from that reporter. |
| Second reporter | Sign in as the second reporter and submit a different valid category for the same takeover. | The existing case remains open; its report count becomes two and its category summary includes both categories. No duplicate case is created. |

### 3. Approved-message behavior

1. In Django Admin, open the case at **Moderation → Message report cases**.
2. Enter a resolution reason and select **Dismiss / approve message**.
3. Reload the public school board as a signed-in user.

Expected behavior:

- The message remains on the board and in history.
- **Report message** remains visible; it is not replaced by a special success
  badge.
- Selecting it opens a read-only dialog that says the message has already been
  reported and reviewed as acceptable under the community guidelines.
- The dialog has no report categories or submit control.
- Subsequent report submissions are rejected and do not create more report rows.

## Moderator Admin tests

### 4. Case list and case detail

1. Go to **Moderation → Message report cases**.
2. Confirm the list provides board/school, takeover time, message preview,
   status, report count, and category summary.
3. Filter by status, school, report category, and “target is currently live.”
4. Open the test case.

Expected behavior:

- The case detail shows the reported message itself, controller, represented
  school, takeover amount, whether it is current, the linked bid, PaymentIntent,
  Checkout Session, and any remediation action.
- The resolution-reason field and both action buttons are inside the change form
  and are clickable.
- A blank reason cannot resolve a case; an explanatory Admin error is shown.
- The case, reports, audit records, and payment records are read-only. Admin
  users cannot create or delete them manually.

### 5. Remove a current message and restore a prior message

Prepare a board with two published takeovers, so there is a prior message to
restore. File a report against the current one.

1. Open its case in Admin, enter a reason, and select **Remove message and
   remediate payment**.
2. Return to the public board and refresh it.

Expected behavior:

- The case status is **Removed**, with resolver, timestamp, and reason.
- The removed takeover remains in Admin/history as an immutable record, but its
  public message is redacted.
- The board returns to the most recent prior non-removed takeover. If there is
  no valid prior takeover, it instead shows the default board message and no
  controller.
- Admin has `remove_message`, and when applicable
  `restore_previous_takeover`, audit records.
- A durable moderation payment action exists for the removed bid; refresh the
  action rather than pressing remove a second time.

### 6. Remove while a higher challenger is authorized

This verifies that removal cannot accidentally capture an authorization that was
made against now-removed content.

1. Keep a current message live.
2. In another browser/account, begin a higher Stripe test-mode takeover so it
   becomes the pending authorized challenger, but do not wait for it to capture.
3. Report and remove the current message through Admin.

Expected behavior:

- The pending challenger is cleared from the board and becomes
  `AUTH_CANCELED`.
- Its moderation payment action is **Cancel authorization**, not **Refund**.
- Stripe shows a cancellation of the authorization, not a captured charge.
- The challenger does not later become the current board message.

## Paid bidding, confirmation, and risk tests

### 7. Mandatory confirmation and first-purchase terms

| Scenario | Steps | Expected behavior |
| --- | --- | --- |
| Normal paid bid | Sign in with a fresh test account, enter a valid whole-dollar bid and approved message, then submit the takeover form. | A review screen appears before Stripe Checkout. It shows the current board amount, any pending challenger, minimum at review, message, represented school, exact bid, authorization explanation, and 30-second guarantee. No `Bid` or Checkout Session exists yet. |
| First real-money purchase | On that review screen, try to continue without checking the terms box, then check it and continue. | The unchecked attempt stays on the confirmation screen with an explanatory error. The checked attempt records the current terms version/timestamp and can proceed to Checkout. Later bids still require the review screen but not the first-purchase checkbox unless terms change. |
| Stale price | Leave a confirmation screen open. In another account, raise the board or its pending challenger above the reviewed amount. Return to the first screen and continue. | No Checkout Session is created. The user sees that the board price changed and must start a fresh confirmation at the new minimum. |
| Expired approval | Leave the confirmation screen open past the message-validation expiry, then continue. | Checkout is rejected with a fresh-approval message. The expired approval and confirmation cannot be reused. |

### 8. High-value friction

| Scenario | Steps | Expected behavior |
| --- | --- | --- |
| Threshold bid | Submit a bid exactly at the configured high-value threshold (default $50). | The confirmation has prominent high-value language and its CTA repeats the exact dollar amount. |
| Very high bid | Use an established/trusted test account and submit a bid at the configured very-high threshold (default $100). Try to continue without, then with, `CONFIRM 100`. | Checkout remains unavailable until the exact typed confirmation is supplied. A malformed value, decimal variant, or another amount is rejected. |
| Normal bid | Submit a bid below the high-value threshold. | The normal confirmation screen still appears; it does not require typed confirmation. |

### 9. Risk limits and pending exposure

| Scenario | Steps | Expected behavior |
| --- | --- | --- |
| New-user maximum | As a new account, submit $50 and then $51 with the default risk configuration. | $50 can reach confirmation; $51 is rejected before moderation/confirmation with a user-facing current-limit message. |
| Rolling hourly/daily limit | Create captured test spend close to the configured hourly or daily limit, then try a bid that crosses it. | The bid is rejected before moderation and Stripe. The message says that the spending limit has been reached; it does not expose fraud terminology. |
| Pending authorization exposure | Keep an authorized pending challenger for the account, then attempt another bid that would exceed captured spend plus pending authorization exposure. | The second bid is rejected before Checkout. Canceling or being outbid releases the exposure so a later eligible bid can proceed. |
| Payment-failure cooldown | Cause the configured number of failed test payments in the configured window, then submit another otherwise-valid bid. | Checkout is temporarily unavailable with a neutral wait-and-retry message. |

### 10. Risk operations and dispute suspension

1. In Django Admin, open **Accounts → User profiles** for the test bidder.
2. Confirm the risk tier, captured-bid count, refund/dispute counts, last dispute,
   and paid-bidding suspension state are visible and editable only through the
   intended controls.
3. Deliver a Stripe test `charge.dispute.created` event for a captured bid.
4. Refresh the user, bid, ledger, and public board.

Expected behavior:

- The bid is **Disputed** and retains the Stripe dispute ID.
- One negative **Chargeback** ledger entry exists; duplicate delivery does not
  create another entry or increment the dispute count again.
- The account is suspended from paid bidding but can still view public boards.
- A later takeover attempt has a neutral account-review message and never opens
  Checkout.
- An operator can restore paid bidding only after resolving the underlying
  dispute review; historical dispute count remains intact.

### 11. Purchase and delivery evidence

1. Complete a Stripe test-mode captured takeover through the confirmation flow.
2. In Admin, open **Payments → Purchase evidences** and the linked bid and
   confirmation records.
3. Let a later successful takeover replace the message, then refresh the
   earlier evidence.

Expected behavior:

- A single immutable evidence record ties together the bid, confirmation, user
  identity snapshot, board, request context, terms/confirmation versions, risk
  tier, publication time, and guarantee deadline.
- The linked bid provides the Checkout Session, PaymentIntent, charge, and
  capture records; evidence does not store raw provider payloads or card data.
- `ended_at` is populated when the next winning message actually replaces the
  original message, preserving delivery evidence for a dispute response.

## Stripe capture and fee-deducted refund tests

### 12. Capture snapshot appears in Admin

1. Create a real Stripe **test-mode** takeover through the public UI and allow
   its guarantee/finalization window to complete.
2. Confirm the bid becomes **Won** and the message publishes.
3. In Admin, open **Payments → Payment captures**, then open the record for the
   bid. It is also linked from the bid and the report-case payment context.

Expected behavior:

- One `PaymentCapture` exists per captured bid.
- It contains immutable gross amount, currency, PaymentIntent, Charge, and (if
  available) Balance Transaction identifiers.
- When Stripe has supplied the Balance Transaction, **Fee status** is
  **Stripe fee data available** and gross = Stripe fee + net.
- If the fee is initially pending, the worker completes it from
  `charge.updated` or its reconciliation retry. Wait at least one worker retry
  interval and refresh; do not edit the record manually.
- One positive `LedgerEntry` of type **Bid capture** exists for the gross amount.

### 13. Remove a captured paid message: refund less the actual fee

Only run this in Stripe test mode. Use a newly captured takeover that has a
`PaymentCapture` with **Fee status: Stripe fee data available**.

1. File a report against that message and remove it through the case detail.
2. Open the linked **Moderation payment action**. Refresh after the worker runs.
3. Check **Payments → Ledger entries** and the corresponding test-mode payment
   in Stripe.

Expected behavior:

- The action is **Refund**, then **Succeeded** after Stripe confirms it.
- `amount_cents` equals the capture’s `net_amount_cents`, not its gross amount.
- Stripe displays a partial refund for that same net amount.
- The bid becomes **Refunded** only after Stripe success.
- Exactly one negative **Refund** ledger entry exists, with the same amount as
  the action.
- Retrying the action does not issue another refund because its idempotency key
  and action row are reused.

### 14. Fee-not-yet-available safety check

This state is timing-dependent. It is a useful staging test, but not a release
blocker if Stripe immediately supplies fee data.

1. Remove a captured message while its `PaymentCapture` still says **Pending
   Stripe fee data**.
2. Inspect the linked payment action before the next reconciliation completes.

Expected behavior:

- The action remains **Pending**, has no refund amount, and records
  `stripe_fee_data_pending` as its safe error code.
- No Stripe refund is sent and the bid remains **Won**.
- Once the fee data becomes available, the worker calculates the net amount and
  completes the normal refund flow in scenario 13.

## Operational checks

### 15. One-time historical snapshot backfill

After deployment, run once in the target environment:

```bash
python manage.py reconcile_payment_captures
```

Expected behavior: it creates snapshots only for captured, refunded, or disputed
Stripe bids that lack one. A second run is idempotent and should not duplicate
snapshots or capture ledger entries.

### 16. Automated release gate

UI testing complements, rather than replaces, the automated suite:

```bash
docker compose exec -T web python manage.py migrate --check
docker compose exec -T web python manage.py test
docker compose exec -T web python manage.py check
```

Expected behavior: all commands exit successfully. Investigate failures before
promoting a change, especially failures around payment idempotency, CSRF, report
deduplication, capture fee reconciliation, and refund amounts.

## Result log template

Copy this block into the relevant PR or release note. Keep it free of personal
data and provider payloads.

```text
Environment:
Commit:
Tester / date:
Stripe mode: test only

Scenario | Pass / fail | Notes / safe IDs
1–6      | Reporting and moderation |
7        | Confirmation and terms |
8        | High-value friction |
9        | Limits and pending exposure |
10       | Dispute suspension |
11       | Purchase evidence |
12       | Capture snapshot |
13       | Fee-deducted refund |
14       | Fee-pending safety |
15       | Snapshot backfill |
16       | Release gate |
```
