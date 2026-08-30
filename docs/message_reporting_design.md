# Message Reporting And Review Design

## Status

Implementation design for the MVP reporting mechanism. This document is
intended to be handed to an implementation thread. It extends
`docs/moderation_and_abuse_controls_design.md`, `docs/moderation_policy.md`,
and `docs/payment_flow.md`; those documents remain authoritative when this
document is silent.

The design covers reports on public board messages, aggregation and abuse
controls, Django Admin review, public redaction, board rollback, and payment
remediation. It does not create a public moderator dashboard or an automatic
crowd-voting system.

## Goals

- Give authenticated fans a clear way to report a public message.
- Aggregate reports against one immutable published takeover, not against
  mutable display text or a user account.
- Make repeated reports by one account ineffective and make mass reporting a
  review-priority signal rather than an automatic takedown.
- Give administrators a single case to dismiss or uphold in Django Admin.
- Preserve every bid, takeover, report, payment transition, and admin action
  for auditability.
- Remove an upheld message from every public surface and restore the prior
  valid board controller when the reported takeover is still current.
- Release or refund money safely and idempotently when an upheld removal
  affects a paid bid.
- Keep report submissions, candidate text, payment data, and operational
  secrets out of logs and public responses.

## Non-goals

- Allowing users to vote a message down or automatically remove content after a
  report threshold.
- Anonymous reporting in the MVP.
- Letting reporters submit arbitrary accusations or public comments about the
  author. A fixed category is sufficient for triage and reduces abuse and
  retention risk.
- Deleting `Bid`, `BoardTakeover`, `StripeEvent`, ledger, or audit history.
- Re-running Bedrock for every report. Existing moderation records and the
  administrator's review are the source of truth for a published message.

## Product policy

### What can be reported

Only a published, user-generated `BoardTakeover` can be reported. The default
`THIS BOARD IS OPEN.` message is not reportable. Pending bids and Checkout
messages are not public and are not reportable. A takeover remains one report
target whether it is currently live or appears in takeover history.

### Report categories

The user must choose exactly one category:

1. Hate speech or slur
2. Threats or violence
3. Personal information or doxxing
4. Harassment or sexual content
5. Spam or advertising
6. Impersonation
7. Other community-guideline violation

The first release should not accept a free-form report explanation. The
category is enough to prioritize review and avoids creating another channel
for abuse, personal data, or raw text that needs retention. An optional note
can be added later only with an explicit length limit, retention rule, and
separate sanitization tests.

### No automatic takedown

A report never hides a message, changes board state, cancels a payment, or
refunds a bidder. One report opens a case. Additional distinct reporters
increase the case's priority and category counts, but do not decide whether the
message violated policy. This prevents a fanbase from taking down a rival's
message merely by coordinating reports.

### Report eligibility

- Require a Cognito-authenticated Django session and a non-banned
  `UserProfile`.
- Require CSRF and a `POST` mutation endpoint.
- Do not allow a user to report the same takeover more than once. The database
  unique constraint is authoritative; Redis limits are only the hot-path
  control.
- Do not expose whether another reporter has already reported the message.
- A reporter can report a message regardless of which school they selected in
  their profile. Do not use team affiliation as a trust or vote weight.
- Do not automatically ban reporters. Administrators can investigate and ban
  accounts that abuse the mechanism using the existing user action.

### Closed cases

When an administrator dismisses a case (message approved) or upholds it
(message removed), reporting is closed permanently for that takeover. Further
public submissions receive a generic "This message is no longer accepting
reports" response and are not stored. A separate, audited administrator
reopen action may be added later for a policy change or an obvious review
mistake; reopening is never triggered by a new fan report.

## Target and case model

Reports attach to `BoardTakeover`, because it is the immutable public snapshot
that contains the message, board, author display-name snapshot, represented
school, amount, and occurrence time. Do not attach a report directly to
`Board.current_message`, `Bid.message`, or a display name: those values do not
uniquely identify a public historical message.

Add two moderation models in a new migration. Names below are normative unless
the implementation thread has a strong Django naming reason to change them.

### `MessageReportCase`

One row per takeover that has ever received a report.

```text
id                  BigAutoField
public_id           UUIDField(unique, non-editable)
takeover            OneToOneField(BoardTakeover, PROTECT)
status              open | approved | removed
opened_at           DateTimeField(auto_now_add)
last_reported_at    DateTimeField()
resolved_at         DateTimeField(null=True)
resolved_by         ForeignKey(auth.User, SET_NULL, null=True)
resolution_reason   CharField(max_length=500, blank=False after resolution)
created_at          DateTimeField(auto_now_add)
updated_at          DateTimeField(auto_now=True)
```

`approved` means an administrator reviewed the reports and kept the message
visible. `removed` means the message was upheld as a violation and is redacted
from public rendering. A case with no row has never been reported and is still
reportable. The one-to-one constraint and a row lock prevent two simultaneous
first reports from creating separate cases.

Useful indexes:

- `(status, -last_reported_at)` for the admin queue;
- `takeover` through the one-to-one relation; and
- `(resolved_by, -resolved_at)` for audit review.

Do not denormalize report count into the case initially. Use an aggregate query
from `MessageReport`; add a counter only after measuring an actual queue
performance problem.

### `MessageReport`

One immutable submission by one reporter for one case.

```text
id                  BigAutoField
public_id           UUIDField(unique, non-editable)
case                ForeignKey(MessageReportCase, PROTECT, related_name=reports)
reporter            ForeignKey(UserProfile, SET_NULL, null=True)
category            ChoiceField(max_length=40)
reporter_ip_hash    CharField(max_length=64, blank=True)
created_at          DateTimeField(auto_now_add)
```

Add a database `UniqueConstraint(fields=("case", "reporter"),
name="unique_reporter_per_message_case")`. A deleted reporter may leave a
null foreign key; the endpoint never creates null-reporter rows. The HMAC IP
digest is optional for the first migration, but if stored it must use the
existing `TAKEBOARD_MODERATION_HASH_SECRET` and never store the raw address.

Do not store a copy of the message, email address, user agent, request body, or
Stripe data. The related takeover is the content snapshot. Existing moderation
retention/purge rules continue to govern blocked candidates; a report category
does not extend candidate retention.

### `ModerationPaymentAction`

An upheld case needs a durable, retryable payment operation rather than a
Stripe call hidden inside an admin transaction. Add a one-to-one action for a
paid bid when removal requires cancellation or a refund:

```text
id                  BigAutoField
public_id           UUIDField(unique, non-editable)
case                OneToOneField(MessageReportCase, PROTECT)
bid                 OneToOneField(Bid, PROTECT)
operation           cancel_authorization | refund
status              pending | processing | succeeded | not_required | failed
amount_cents        PositiveIntegerField(null=True)
provider_reference  CharField(max_length=255, blank=True)
attempts            PositiveIntegerField(default=0)
last_error_code     CharField(max_length=80, blank=True)
created_at          DateTimeField(auto_now_add=True)
updated_at          DateTimeField(auto_now=True)
completed_at        DateTimeField(null=True)
```

`last_error_code` may contain a stable Stripe error class/code, but never a raw
Stripe response or payment payload. The idempotency key is derived from the
case public ID, for example `takeboard-moderation-refund-{case.public_id}`.
There must be at most one action per case/bid. A local free-play bid receives
`not_required`; no fake Stripe refund is created.

## Public endpoint and UI

### Endpoint

Add a named route under the boards app:

```text
POST /api/boards/takeovers/<uuid:takeover_public_id>/report/
```

The endpoint must:

1. Require an authenticated, non-banned profile.
2. Apply the shared Redis report rate limits before database work.
3. Validate the category against the server-side allowlist.
4. Lock the target takeover and its case (if present).
5. Reject default/non-public targets and targets that are not visible in the
   public history.
6. If the case is resolved, return the closed generic response without writing.
7. Create the case if needed, then create one report inside the same
   transaction.
8. Treat the unique-constraint collision as an idempotent duplicate, not a
   500. Do not reveal who submitted the earlier report.
9. Update `last_reported_at` and emit a structured metric/log event without
   message text.

Suggested response behavior:

- Success: `Thanks. We’ll review this message.`
- Duplicate, invalid target, or closed case: a generic non-enumerating response
  such as `This message is no longer accepting reports.`
- Rate limit or unavailable service: `Please try again later.`

For HTMX, return a small result fragment and close/disable the modal. For a
normal browser request, redirect back to the school page with a one-time
session flash. Do not return report IDs, reporter counts, case status, or admin
decisions to the browser.

### Report modal

Add a `Report` button beside each user-generated current/history message. The
button should carry only the opaque takeover public UUID needed for the POST;
it must not include internal bid IDs, payment IDs, or moderation metadata.

The modal contains:

- a short explanation that reports are reviewed against the community
  guidelines;
- the seven category radio options;
- a submit button with an in-flight disabled state; and
- a generic success/error region.

The UI is advisory only. The server owns authentication, CSRF, target
visibility, category validation, uniqueness, and rate limiting. Escape the
message and display name everywhere; the report modal does not need to repeat
the candidate text.

## Redis abuse controls

Add configuration entries to `TAKEBOARD_RATE_LIMITS`, not view-level constants.
Initial conservative defaults:

| Surface | Limit | Key dimensions |
| --- | --- | --- |
| Report submissions | 5 per hour | authenticated user, HMAC IP |
| New report cases | 3 per hour | authenticated user, HMAC IP |
| Global report volume | 500 per minute | global |

The per-user report limit is applied to all submissions, including duplicate
attempts. The new-case limit is applied only after the target is locked and
only when no case exists, so a reporter cannot create many cases for one
message. A duplicate unique-constraint result is not counted as a new case.

Use the existing shared Redis `enforce`/`safe_key` helpers. A Redis outage or
global limit must fail closed for the report endpoint, with the generic
retry-later response. Do not fall back to per-process memory. Keep the rate
limit keys HMAC'd and do not log them.

Report volume is a triage signal only. Do not add a count threshold that
automatically hides content. Admins can filter/open cases by total distinct
reporters and category concentration. If coordinated false reporting appears,
admins can ban accounts and tighten limits without changing message state.

## Admin review workflow

Register `MessageReportCase`, `MessageReport`, and
`ModerationPaymentAction` in Django Admin using the existing Unfold admin
classes.

### Queue list

`MessageReportCaseAdmin` should show:

- opened/last-reported time;
- board/school and takeover occurrence time;
- a safe message preview (the existing published snapshot, escaped);
- case status;
- total distinct reporter count; and
- category summary.

Filters: status, board school, category, opened date, resolved date, and
whether the target is currently live. Search: takeover public ID, board school,
controller display-name snapshot, and bid public ID. Do not make IP hashes or
payment intent IDs the primary search UI.

The case detail page should show the message, display-name snapshot, board,
represented school, bid status/amount, current-vs-historical state, prior
takeover link, pending challenger link, category counts, and the immutable
report rows. It may show reporter display names to authorized admins, but not
raw IPs or raw request data.

### Required actions

Actions must be explicit change-view buttons or confirmation forms, not blind
bulk actions. Every resolution requires a non-empty reason of at most 500
characters.

1. **Dismiss / approve message**
   - Lock the case.
   - Set `status=approved`, `resolved_by`, `resolved_at`, and reason.
   - Leave board, bid, and public history unchanged.
   - Close future reports.
   - Write `dismiss_message_reports` to `ModerationActionAudit`.

2. **Remove message and remediate payment**
   - Lock the case, takeover, bid, and board in a deterministic order.
   - Set `status=removed` and resolution fields.
   - Create the durable `ModerationPaymentAction` before releasing the admin
     transaction.
   - Redact the message from public history through the case status; do not
     delete the `BoardTakeover`.
   - If the target is current, restore the most recent prior non-removed
     takeover or the default board state.
   - Cancel any currently pending challenger on that board; it was authorized
     against the removed message and must not be captured as a side effect of
     the rollback. Mark it `AUTH_CANCELED` and release its authorization when
     applicable.
   - Queue a full refund for a captured paid bid. A merely authorized bid is
     canceled and is not refunded. A local demo bid is `not_required`.
   - Write `remove_message`, `restore_previous_takeover` when applicable, and
     `payment_remediation_queued` audit records.

3. **Retry payment remediation**
   - Available only for a failed/pending action.
   - Reuse the same idempotency key and action row.
   - Never create a second refund action by repeating the admin button.

Do not provide a one-click “delete report” action. Reports are immutable audit
inputs. If a report is clearly abusive, an admin can ban its reporter and leave
the case decision unchanged.

## Removal and rollback algorithm

Implement one service boundary, for example
`apps/moderation/services/report_cases.remove_case`, and keep all board/payment
state transitions out of `ModelAdmin` methods.

Inside one database transaction:

1. Lock the case and assert `status=open`.
2. Lock the target `BoardTakeover`, its `Bid`, and its `Board`.
3. Re-check that the target is still the board's `current_bid_id`. Do not
   assume it is current because it was current when the report was created.
4. If current, walk `previous_bid.takeover` backward until the first takeover
   whose case is absent or not `removed`. The chain is bounded by the number of
   historical takeovers; guard against a malformed cycle. If there is no valid
   prior takeover, restore `TAKEBOARD_DEFAULT_BOARD_MESSAGE`, clear controller
   and current bid, set amount to zero, clear pending and guarantee, and bump
   the board version.
5. If a valid prior takeover exists, restore its controller, display message,
   represented-school-independent board amount, and bid pointer. Set
   `guaranteed_until=NULL`: the prior takeover's original guarantee has already
   elapsed before a later takeover could publish, and removal must not grant a
   fresh paid guarantee.
6. If `board.pending_bid` exists, lock it, mark it `AUTH_CANCELED` if it is
   authorized, clear the board pointer, and create a cancellation action when
   it has a Stripe PaymentIntent. A pending challenger is never silently
   promoted during removal.
7. Mark the case removed and create a refund/cancel action for the removed bid
   according to its payment state.
8. Commit. External Stripe calls happen after commit or in the existing worker;
   never hold a database row lock while waiting on Stripe.

The service must be idempotent. Repeating an already removed case returns the
existing disposition and does not mutate board state or create another payment
action. The worker/admin retry path must tolerate Stripe's already-refunded or
already-canceled response.

Historical removal (the target is no longer current) follows the same case and
payment steps but does not alter board state or cancel the current pending
challenger.

## Public rendering and cache behavior

- Current board rendering must never show a removed takeover. The removal
  transaction replaces `Board.current_message` and related current pointers.
- Takeover history queries must select the case status. When `status=removed`,
  render a fixed placeholder such as `Message removed for violating community
  guidelines.` Do not show the removed text, even to the author.
- The placeholder is application text, not user content, and should be escaped
  normally.
- Cache keys or fragment caches that include a board version must be invalidated
  or naturally miss after the board version increment. If another cache exists,
  explicitly invalidate it in the removal service.
- Hide the report button for removed and approved/closed cases. The server
  still enforces closure if an old page submits a stale form.

## Payment and legal-policy boundary

The MVP operational default is:

- no payment change on report submission or dismissal;
- full refund of a captured paid bid when an admin upholds removal;
- authorization cancellation, not refund, for a not-yet-captured challenger;
- no payment operation for local free-play bids; and
- no deletion of historical financial records.

This is simpler and safer for customer support than retaining money after the
platform removes the purchased public placement. Terms and Conditions must
describe the same operational rule and reserve the platform's moderation right;
legal counsel should review any alternative “no refund after removal” policy
before implementation. Do not silently implement a legal policy different from
the refund service and ledger behavior.

Every successful refund must call the existing payment boundary, use a stable
Stripe idempotency key, mark the bid `REFUNDED` only after Stripe confirms it,
and create a `LedgerEntry(type=REFUND)` for the refunded amount. A provider
failure leaves the action visible as failed/pending for retry and never marks
the bid refunded. Do not log Stripe payloads, card data, client secrets, or raw
provider errors.

## Observability and privacy

Emit structured events with only safe fields:

- `message_report_submitted`
- `message_report_duplicate`
- `message_report_rate_limited`
- `message_report_case_opened`
- `message_report_case_resolved`
- `message_report_payment_action_queued`
- `message_report_payment_action_succeeded`
- `message_report_payment_action_failed`

Allowed fields include request ID, opaque user/profile ID, opaque takeover/case
ID, board ID, category, status, rate-limit surface, and duration bucket. Never
log the message, display name, report body (if added later), email, raw IP,
Stripe payload, payment intent, authorization token, Redis key, prompt, or
model output. Report categories are safe operational metadata but must not be
used in public responses to identify the exact matching rule.

Retain report rows and admin resolution records as audit history. If an
optional report note is added later, give it a documented short retention
period and purge it without deleting category/count/audit metadata.

## Implementation order

1. Add `MessageReportCase`, `MessageReport`, and `ModerationPaymentAction`
   models, constraints, indexes, and migrations.
2. Add report category constants, settings, shared Redis limits, and a service
   that creates a case/report transactionally and handles duplicate/closed
   submissions.
3. Add the authenticated CSRF-protected route, HTMX result fragment, report
   modal, and report buttons on current/history messages.
4. Add public-history redaction based on case status.
5. Implement the case resolution service, rollback algorithm, pending
   cancellation, and durable payment-action creation.
6. Extend the worker/payment boundary to process cancellation/refund actions
   idempotently and write ledger entries.
7. Register Django Admin queue/detail views and explicit resolution/retry
   actions backed by the service layer and `ModerationActionAudit`.
8. Add metrics/logging with the safe-field allowlist and document deployment
   settings/retention.

## Required tests

### Reporting endpoint

- unauthenticated and banned users cannot report;
- CSRF is required;
- valid category creates exactly one case and one report;
- two concurrent first reports create one case;
- the same user cannot create two reports for one takeover;
- a user can report two different takeovers;
- invalid category, default message, pending bid, and unknown takeover are
  rejected without writes;
- closed cases accept no further reports;
- user, IP, new-case, and global Redis limits are enforced;
- Redis/global-control failure is fail-closed;
- response does not expose report counts, reporter identity, or case IDs.

### Admin decisions and rendering

- dismissing a case closes it and leaves board/payment/history unchanged;
- removing a historical takeover redacts only that history row;
- removing the current takeover restores the prior valid takeover;
- removing the first takeover restores the default board state;
- a chain with a previously removed takeover skips removed history;
- a pending challenger is canceled and never promoted by rollback;
- stale duplicate resolution is idempotent;
- removed messages are absent from current, school, rivalry, leaderboard, and
  history public surfaces;
- old report buttons cannot bypass server-side closure.

### Payments and audit

- captured Stripe bid queues one refund action and one ledger refund after
  successful provider confirmation;
- authorized-only bid queues cancellation and no refund;
- demo bid requires no provider call;
- provider timeout/error leaves a retryable action and does not mark refunded;
- repeated retries use one idempotency key and create no duplicate action;
- every admin resolution has actor, target, action, reason, and timestamp;
- logs contain no raw message, report note, IP, token, secret, or Stripe
  payload.

## Completion criteria

The reporting MVP is ready for controlled external testing when an
authenticated fan can report any visible user message, duplicate/brigade
attempts are bounded without automatic takedowns, admins can review and close a
case, an upheld current message safely restores the prior valid board state,
public history redacts removed content, and payment remediation is durable,
idempotent, auditable, and covered by the tests above.
