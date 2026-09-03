# Implementation impact checklist

Use this checklist for every implementation task, feature, bug fix, migration,
or meaningful UI change. Review it once when work starts and again before the
work is considered complete. Mark an item `N/A` when the change genuinely does
not affect that area.

The checklist is a review prompt, not a replacement for the source-of-truth
documents linked below.
For the current consolidated launch status, see [launch readiness](launch_readiness.md).

## Start-of-work review

Record a short note in the task or PR for each applicable area:

- [ ] Scope and product behavior: identify the affected user journey, business
      rule, data model, and public/private surfaces.
- [ ] Analytics: inspect every new page, CTA, button, form, modal, HTMX swap,
      redirect, and meaningful success/error state. Decide whether an existing
      GA4 event covers it or a new marker is needed. Check the event and
      parameter against [analytics tracking](analytics_tracking.md).
- [ ] Security: inspect authentication, authorization, sessions, CSRF, input
      validation, UGC escaping, rate limits, secrets, logs, webhooks, external
      calls, and error responses against [security baseline](security_baseline.md).
- [ ] SEO: identify whether public discoverable content changed. Check title,
      meta description, canonical URL, indexability, internal links, Open Graph/
      X metadata, structured data, sitemap/robots behavior, redirects, and
      duplicate or user-generated content exposure.
- [ ] Accessibility and UX: check semantic HTML, keyboard operation, focus
      behavior, dialog behavior, labels, error messaging, reduced motion,
      responsive layouts, and loading/empty/error states.
- [ ] Operations: identify migrations, worker changes, cache behavior, rate
      limits, monitoring, rollback needs, environment variables, and deployment
      sequencing.

## Before-completion review

- [ ] Analytics markers exist for newly introduced meaningful interactions and
      outcomes, including modal open, modal close/abandon, validation errors,
      async success, and async failure where those states matter.
- [ ] Analytics payloads contain only approved low-cardinality values. They do
      not contain messages, report text, emails, names, tokens, payment IDs,
      bid IDs, raw URLs, or other sensitive free-form data.
- [ ] Analytics is production-only and consent/privacy requirements are known
      before enabling collection. Confirm new events are documented and any
      needed GA4 custom dimensions are listed.
- [ ] Security behavior is tested or manually verified. Confirm no new secret,
      token, raw payment payload, raw auth header, or sensitive UGC is logged or
      returned to the browser.
- [ ] Public SEO behavior is verified when applicable. Confirm no staging,
      admin, private, payment, or transient workflow page became indexable.
- [ ] Tests cover the changed behavior, including relevant race conditions,
      idempotency, authorization, public rendering, and error paths.
- [ ] Documentation and environment examples are updated for durable behavior,
      business rules, security posture, analytics contracts, or deployment work.
- [ ] Run the appropriate checks. For changes affecting the running app, make
      the required migrations available to the running Docker web container and
      run a real HTTP `curl` against a school board such as
      `/schools/alabama/`.
- [ ] Record any deferred follow-up in the task and, if it is durable, add it to
      [security TODOs](security_todo.md), the relevant source-of-truth document,
      or the open follow-ups section below.

## High-risk change prompts

Use these additional prompts when applicable:

- Payments: verify server-authoritative state, idempotency, manual capture,
  webhook verification, refunds/disputes, and that GA4 never becomes the source
  of payment truth. See [payment flow](payment_flow.md).
- Authentication: verify OAuth `state`, token handling, session rotation,
  logout, CSRF, rate limits, and that tokens/emails do not enter analytics. See
  [authentication](authentication.md).
- Moderation/reporting: verify fail-closed behavior, UGC handling, report
  privacy, abuse controls, admin auditability, and safe public outcomes. See
  [moderation policy](moderation_policy.md).
- Public content: verify escaping, metadata safety, trademark-conscious naming,
  canonical URLs, sharing text, and whether the content should be indexed.

## Open follow-ups

Keep only durable, actionable items here. Remove an item once it is completed.

- [ ] Before enabling live payments, configure and monitor the published support
      mailbox, and keep public policy copy aligned with payment, moderation,
      privacy, retention, and analytics behavior.

## Review log

Add an entry only when a review produces a durable decision or follow-up that
future implementation work should know about.

| Date | Change | Decision or follow-up |
| --- | --- | --- |
| 2026-09-02 | Production preview bootstrap | Provisioned the low-scale AWS foundation/edge/compute path, added a narrowly scoped ALB health-check middleware/probe, and created the idempotent `seed_production_roster` command. Preview remains no-bid until DNS, provider credentials, worker permissions, and external launch checks are complete. |
| 2026-08-31 | Added checklist | Every implementation reviews analytics, security, SEO, accessibility, operations, tests, and documentation at start and completion. |
| 2026-09-02 | Overnight security hardening | Added fail-closed deployment settings, browser headers/request-ID validation, immutable Admin records, shared-cache Admin throttling, and django-otp staff MFA. No new GA4 markers; edge access controls, alerting, and live deployment verification remain external. |
| 2026-09-02 | Initial Sentry wiring | Added environment-backed server-side Sentry tags and production ECS secret wiring. |
| 2026-09-02 | Production-only Sentry | Disabled Sentry outside production, removed the local error trigger, and retained structured stdout logs for local/dev Docker and future CloudWatch collection. |
| 2026-09-03 | Admin operations home | Added a staff-permission-aware Django Admin landing page with moderation/payment action queues, 30-day operational charts, and mobile-responsive inline SVG visuals. No GA4 markers or public SEO surface; existing Admin MFA and edge-access follow-ups remain in force. |
| 2026-09-02 | Sentry free-tier admission control | Disabled automatic logging events and tracing; added redaction, an allowlist, six-hour deduplication, and a shared-cache four-event/hour production cap. Sentry project alert rules and inbound filters remain a launch configuration task. |
| 2026-09-02 | Friday Sentry smoke test | Marked the production Sentry implementation done in code; the one-off ECS exception test and hosted-project verification remain a required Friday release gate documented in `production_friday_smoke_test.md`. |
| 2026-09-02 | Mobile cookie consent | Replaced the tall mobile consent card with a compact first-load cookie bar so the first board CTA remains visible. Analytics still remains off until explicit acceptance; local preview renders the prompt without loading GA4. |
| 2026-09-02 | Refund email foundation | Added disabled-by-default transactional email templates, provider abstraction, unique refund/removal outbox intents, retry-safe delivery leases, and worker integration. No new GA4 markers; Resend/SES sender verification and deliverability operations remain external launch work. |
| 2026-09-03 | Refund email consolidation | Consolidated paid-message removal and fee-deducted refund messaging into one deferred, idempotent customer email; added outbox gating and coverage for the no-duplicate-email path. No new GA4 markers; email remains operationally monitored through outbox status and provider error logs. |
| 2026-09-02 | Queued paid-bid checkout | An authorized manual-capture bid is presented as the next challenger, with explicit server-observed win/delayed states, cancellable ten-second return behavior, and no browser-authoritative payment outcome. See `queued_paid_bid_checkout_ux_design.md`. |
| 2026-09-03 | Open-board paid authorization | An authorized bid on a board without an active protected takeover is captured and published in the worker transaction; only bids behind an active guarantee use the queued challenger state. |
| 2026-09-03 | Bedrock/Nova moderation evaluation | Added a synthetic 250-case uncached live evaluator and versioned the Nova prompt/policy for public sports references versus private information. No new GA4 marker; evaluator output excludes raw candidates and persistent moderation records. Launch gates and dev evidence are recorded in `moderation_bedrock_evaluation.md`. |
