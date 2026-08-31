# Launch Readiness

This is the consolidated operational checklist for taking Take the Board from
the current MVP implementation to a public, real-money launch. It is a status
document, not legal advice and not a replacement for the detailed source-of-
truth documents linked below.

Last reviewed: 2026-08-31

## Status legend

- **Done** — implemented and covered by tests or a documented manual check.
- **Verify/configure** — the application path exists, but an environment,
  provider, schedule, runbook, or production-like test is still required.
- **Build** — the production capability is not wired yet.
- **Deferred** — reasonable post-launch work only if the product owner accepts
  the risk.

## Who needs to act

Use these labels when working remotely:

- **Codex can start** — Codex can implement, test, document, and wire the
  feature using placeholders or mocks. No account access is required to begin.
- **You provide/decide** — Codex cannot safely invent the account, credential,
  brand choice, recipient, policy decision, or risk acceptance.
- **Joint** — Codex can do the application work, but you must create or approve
  the external service configuration and help with production verification.

### Codex can start independently

These are good remote handoffs that do not need your credentials first:

- Review the implemented first-paid-bid 18+ checkbox, server-side enforcement,
  and purchase evidence in staging.
- Build the board-level X/Twitter button and its analytics markers.
- Build the automatic takeover-posting workflow with an outbox/idempotency
  boundary, retry behavior, disable controls, and a mocked X provider.
- Build Resend email templates and the refund/message-removal notification
  service behind an environment-based provider interface.
- Build the board reset countdown from the server-provided reset timestamp and
  add the public weekly-reset explanation.
- Build the authenticated account history/support surface: active and historical
  takeovers, bid/payment status, safe receipt or transaction references,
  refund/dispute state, and clear failed, delayed, and outbid outcomes.
- Add logo/favicons/social-card integration once the chosen asset is supplied;
  prepare SEO metadata and verification checks.
- Add Sentry filtering, PII scrubbing, structured operational metrics, and
  CloudWatch/SNS integration points using placeholders.
- Write runbooks, tests, staging checks, and documentation for any of the above.

### You provide or decide

These require an account, a secret, an external approval, or a product decision
from you:

- The final logo/brand assets, preferred brand treatment, and production domain.
- The X/Twitter account, X developer/app access, API credentials, tweet copy,
  posting frequency, and whether every successful takeover should be posted.
- The Resend account/API key, verified sender domain, sender address, and email
  copy. Later, decide whether to stay on Resend or move to SES.
- The Sentry project/DSN, alert recipients, free-tier volume budget, and which
  expected errors should be filtered versus retained.
- The AWS account/permissions, SNS email recipients, and thresholds for signup,
  successful-bid, payment, worker, reset, moderation, and reconciliation alerts.
- The support mailbox owner, moderation operator, response expectations, and
  the practical MVP privacy/deletion process.
- Production Stripe, Cognito, Bedrock, SQS, EventBridge, WAF, backup, and
  hosting-account access, plus any explicit risk acceptance for deferred items.

### Joint completion

Codex can implement the application side, tests, and deployment instructions;
you then complete or approve the external setup and production verification:

- Resend/SES domain authentication and deliverability testing.
- Sentry DSN wiring, alert rules, error-volume review, and free-tier tuning.
- X/Twitter credentials, account authorization, post preview, rate-limit test,
  and operational retry/disable verification.
- SQS FIFO queues, dead-letter handling, worker deployment, and staging smoke
  tests.
- EventBridge reset scheduling, IAM permissions, manual reset test, and failure
  alerts.
- Bedrock/Nova IAM/model enablement and provider outage/quality tests.
- Stripe live-mode configuration and refund/dispute/reconciliation drills.
- CloudWatch metrics, SNS subscriptions, WAF, backups/restore, and external
  smoke tests.
- Manual SEO, accessibility, responsive, support, and moderation-operations
  review.

## Current summary

The MVP has public policy pages, lightweight analytics consent, Cognito-based
authentication, Stripe manual-capture flows, moderation and reporting records,
refund/dispute/ledger services, and an idempotent weekly reset command.

The primary launch gaps are production wiring and operations rather than missing
core domain models: SQS FIFO finalization, EventBridge reset scheduling,
Bedrock/Nova configuration, support and moderation operations,
reconciliation/alerting, and the security gates listed in
`docs/security_todo.md`.

## Product and public surface

| Item | Status | Notes |
| --- | --- | --- |
| Terms of Service | Done | Public page is linked from the site footer. Keep the copy aligned with actual payment, moderation, refund, and age rules. |
| Privacy Policy | Done | Public page describes the current MVP data and analytics-consent behavior. |
| Refund policy | Done | Public page describes the current operational refund behavior. |
| Community Guidelines | Done | Public page matches deterministic and classifier moderation categories. |
| Contact page | Done | The published support address must be monitored before enabling live payments. |
| Analytics consent | Done | GA4 is gated by the browser consent cookie; no analytics-consent row is written to the database. See [analytics tracking](analytics_tracking.md). |
| Brand asset package | Build | Turn the existing basic logo into the approved SVG/PNG set, favicon and browser/app icons, social-card mark, light/dark variants if needed, and accessible alt text. Keep it independent from official school marks. |
| SEO and branded social metadata | Verify/configure | Apply the logo and final brand name consistently to site metadata, Open Graph/X cards, default share images, favicon links, and any structured data; then verify previews on public board pages. |
| Automatic takeover posts | Build | Connect the Take the Board X/Twitter account so a successfully captured and published takeover can generate one automatic public post. Trigger only from the server-side published outcome, make delivery idempotent, keep posting failures from blocking the game, and provide an operational retry/disable path. |
| Post-purchase account history and support | Done | Authenticated `/account/` shows active and historical takeovers, bid/payment status, safe account references, refund/dispute state, and plain-language failed, delayed, and outbid outcomes. The bidder-owned status endpoint remains checkout polling only. |
| 18+ acknowledgement for paid bidding | Done | The first paid-bid form collects a versioned 18+ acknowledgement, the confirmation and Checkout service boundaries enforce it, and captured purchase evidence preserves the timestamp and version. |

## Payments and money movement

| Item | Status | Notes |
| --- | --- | --- |
| Stripe Checkout/manual capture | Done | Embedded Checkout, signature-verified webhooks, idempotent event storage, authorization, cancellation, and capture are implemented and tested in sandbox flows. See [payment flow](payment_flow.md). |
| Ledger and capture snapshots | Done | Successful captures, refunds, chargebacks, and adjustments have durable ledger records; capture fee data can arrive later. |
| Refunds for moderated paid messages | Done | Admin actions create retryable, idempotent cancellation/refund work and use actual recorded Stripe fees. |
| Dispute intake | Done | `charge.dispute.created` is stored idempotently, records a chargeback entry, and suspends paid bidding while open. A live/test-mode operational response runbook is still needed. |
| Transactional customer email | Build | Set up Resend for the initial narrow scope: refund confirmations and notices when a published message is removed. Add templates, sender identity, delivery/error logging without message or payment-sensitive payloads, and links back to support/policy pages. |
| Email delivery foundation | Verify/configure | Follow up with SES setup or a deliberate decision to stay on Resend. Configure domain verification, SPF/DKIM/DMARC, bounce/complaint handling, and a monitored sender address. Do not operate two providers casually. |
| Reconciliation command | Verify/configure | `python manage.py reconcile_payment_captures` exists and is idempotent. Schedule it, alert on failures or unresolved fee snapshots, and assign an owner. |
| Stripe production configuration | Verify/configure | Configure live keys and webhook endpoint only after staging/test-mode smoke tests, support coverage, and the security checklist are complete. |

## Moderation and community operations

| Item | Status | Notes |
| --- | --- | --- |
| Deterministic validation | Done | Runs before any provider call and blocks URLs, contact information, control-character abuse, and other configured policy violations. |
| Bedrock/Nova adapter | Verify/configure | Adapter, normalized response parsing, caching, rate limits, and fail-closed behavior are implemented. Configure scoped dev/staging IAM and model access, then run allowed, blocked, malformed-response, timeout, and provider-outage tests. See [moderation policy](moderation_policy.md). |
| Reporting and admin review | Done | Reports, cases, resolution actions, moderation audits, board controls, bans, and payment remediation actions exist. Assign an operator and response expectations before public traffic. |
| Moderation raw-content purge | Verify/configure | `python manage.py purge_moderation_content` clears expired blocked/review text after the current 30-day retention window. Put it on a monitored production schedule and document the owner. |
| Moderation privacy procedure | Verify/configure | Document the practical MVP account-deletion and privacy-request process; it can be manual, but someone must own and execute it. |

## Workers, scheduling, and infrastructure

| Item | Status | Notes |
| --- | --- | --- |
| Local bid finalization worker | Done | `run_bid_worker` processes the local Postgres polling path and preserves the board lock and pending-challenger invariants. |
| SQS FIFO bid finalization | Build | The queue URL placeholder exists, but the producer/consumer are not wired. Implement board ID message-grouping, retry/visibility behavior, dead-letter handling, idempotent consumption, and a dev/staging smoke test before production. |
| Weekly reset service/command | Done | `reset_boards` is idempotent, preserves historical bids/takeovers/ledger entries, rebuilds period stats, and was manually verified against the local Docker database on 2026-08-31. |
| EventBridge reset schedule | Verify/configure | Configure Sunday 11:59 PM `America/New_York` invocation, permissions, failure alerts, and a manual invocation procedure. Test the schedule in dev/staging before relying on it. |
| Public weekly-reset explanation | Verify/configure | Make the Sunday-to-Sunday reset, preservation of all-time history, and weekly leaderboard behavior explicit in the public explainer and policy copy. |
| Board reset countdown | Build | Show the server-derived time until the next weekly reset on board/leaderboard surfaces. The timer is explanatory UX only; the server-side reset command remains authoritative and must handle schedule delays safely. |
| Shared Redis | Verify/configure | Required for sessions, moderation limits, checkout limits, and abuse controls across instances. Verify outage behavior fails closed for sensitive writes. |
| Sentry error monitoring | Verify/configure | Server-side Sentry is wired when `SENTRY_DSN` is set. Add/verify browser-side coverage and alerts for webhook, capture/cancel/refund, worker, moderation, reset, reconciliation, and database-integrity failures. |
| Sentry free-tier hygiene | Verify/configure | Set environments/releases, scrub PII, filter expected 4xx/user-validation noise, keep real payment/provider/worker failures visible, tune alert thresholds, and review event volume before enabling the free-tier project in production. |
| AWS operational notifications | Build | Create low-cost CloudWatch metrics/log filters or application counters for signups, successful bids, payment failures, moderation/provider failures, worker failures, reset failures, and reconciliation drift. Route actionable alarms through an SNS email topic; decide whether signup/success notifications are immediate or batched so they do not become alert spam. |
| Backups and restore | Verify/configure | Confirm automated database backups, retention, restore testing, and an owner. |

## Web quality and release verification

| Item | Status | Notes |
| --- | --- | --- |
| Public SEO review | Verify/configure | Verify titles, descriptions, canonical URLs, sitemap/robots behavior, internal links, and that admin, payment, auth, and transient workflow pages are not indexable. |
| Accessibility and responsive UX | Verify/configure | Run keyboard, focus, dialog, form-error, mobile, and reduced-motion checks across the public board, bidding, policy, contact, and consent flows. |
| Board sharing | Build | Keep the existing native-share/clipboard control and add a separate board-level X/Twitter intent button. Use the canonical URL and safe, escaped share text; track it with the existing low-cardinality share events. The post-takeover X/Twitter link already exists. |
| Browser consent behavior | Done | Accept/Decline and Cookie settings are implemented, stored only in the browser, and tested in the local preview mode. |
| Automated application tests | Verify/configure | The implementation has coverage for payment state, idempotency, moderation, reporting, and reset behavior. Run the full suite and record the result for the release candidate. |
| External HTTP smoke tests | Verify/configure | Run the checks in [security TODOs](security_todo.md) from outside the server/network, including HTTPS, invalid hosts, sensitive-file paths, error responses, XSS rendering, and unauthorized object access. |

## Security and deployment gate

`docs/security_todo.md` is the detailed security gate. Its unchecked items are
still launch work unless the operator records a documented risk acceptance.
The highest-priority items are:

- staging verification of the first-paid-bid 18+ acknowledgement and server-side evidence;
- Admin protection, MFA, login throttling, and audit coverage;
- immutable payment/history records in Admin;
- fail-closed production settings, secret handling, dependency scanning, and
  production-like integration checks;
- CSP, security headers, authentication response caching, and request-ID
  validation;
- authorization, OAuth state, CSRF, rate-limit, webhook, idempotency, XSS, and
  external smoke tests;
- AWS WAF rules and review of logs, Sentry, analytics, and public responses for
  data leakage.

Do not mark the site production-ready solely because the application test suite
passes. Keep the command output, smoke-test results, staging verification, and
production configuration evidence with the launch review.

## Release sequence

1. Verify the 18+ paid-bid acknowledgement and updated public terms in staging.
2. Create a dev/staging environment that exercises SQS FIFO, Bedrock/Nova,
   Stripe test mode, the reset command, reconciliation, and moderation purge.
3. Configure schedules, alerts, support coverage, backups, WAF, Sentry, and
   production access controls.
4. Run the detailed payment, reporting, moderation, reset, reconciliation, and
   external smoke-test plans.
5. Complete the applicable items in [security TODOs](security_todo.md), record
   any explicit risk acceptance, and only then enable live payment credentials.

## Source documents

- [Backend overview](backend_overview.md)
- [Payment flow](payment_flow.md)
- [Moderation policy](moderation_policy.md)
- [Security TODOs](security_todo.md)
- [Post-implementation checklist](post_implementation_checklist.md)
- [Analytics tracking](analytics_tracking.md)
- [Development environment setup](dev_environment_setup.md)
- [Content reporting UI test plan](content_reporting_ui_test_plan.md)

When a launch item changes, update this document and the detailed source
document that owns the behavior. Remove or change a status only when the
implementation, configuration, or verification evidence exists.
