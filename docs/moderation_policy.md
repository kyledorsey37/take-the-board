# Moderation Policy

Implementation detail and rollout order are defined in
`docs/moderation_and_abuse_controls_design.md`.

Moderation is implemented as a deterministic validation, Redis-cost-control, and
optional Bedrock/Nova classifier gate. The Bedrock adapter is isolated to one
service, stores only a normalized decision, and fails closed when the provider is
disabled, unavailable, or returns a malformed response. This document defines
the intended posture for public user-generated board messages.

## Philosophy

Take the Board is a trash-talk product. It should allow rivalry insults, team mockery, conference mockery, and ordinary profanity while blocking genuinely harmful content.

Generally allowed:

- team insults
- fanbase insults
- rivalry trash talk
- ordinary profanity
- sports arguments

Blocked:

- slurs and hate speech
- credible threats
- doxxing or personal information
- phone numbers, addresses, and email addresses
- targeted sexual harassment
- severe harassment of private individuals
- impersonation of official entities, admins, schools, coaches, athletes, or famous people
- illegal content
- spam and URLs

## Validation Order

Deterministic checks run before any Bedrock/Nova call. Reject empty messages, messages longer than the configured limit, control characters, excessive Unicode abuse, URLs, email addresses, phone numbers, and obvious personal information.

Only after deterministic checks pass should the configured Nova classifier run.
When Bedrock is disabled or unconfigured, validation returns a temporary busy
outcome and the message cannot proceed to payment. This keeps the application
from accepting unclassified paid content.

## User-Facing Rejection

Do not expose classifier category internals. Use a general rejection such as:

```text
That message doesn't meet the trash-talk guidelines.
Rivalry insults and profanity are fine, but slurs, threats, personal attacks, and personal information aren't allowed.
```

## Records And Retention

Each validation creates a `MessageValidation` or `DisplayNameValidation` record
with the user, policy version, classifier version, normalized decision, and
expiration time. The expiration controls whether the approval can be reused for
checkout; it is not a general database-deletion timer.

Blocked and review candidates receive a `content_retention_until` timestamp
(currently 30 days). The `purge_moderation_content` management command clears
their stored raw message or display-name text after that timestamp while
retaining decision metadata. Allowed validation records remain linked to the
checkout and publication audit trail; historical public messages are preserved
as part of takeover evidence. The MVP still needs an owned production schedule
and monitoring for the purge command, plus a documented account-deletion/privacy
request procedure.

Raw Bedrock responses are not persisted or logged. Application logs should use
validation type, user ID, decision, and timing/error metadata only; they must not
include candidate text, prompts, or provider payloads.

## Admin Operations

Django Admin supports reviewing validation and report records, removing current
messages, resolving reports, disabling bidding on a board, banning users, and
preserving an audit trail of who acted and when. Captured paid-message removals
create retryable, idempotent cancellation/refund actions; refunds use the
recorded Stripe fee rather than estimating one.

Message removal creates one durable customer-resolution email intent. For a
paid removal, delivery waits until the fee-deducted refund succeeds, then the
same email explains the removal and the amount paid, actual Stripe processing
fee, and net refund issued. The email templates omit the removed message text
and payment-provider identifiers; delivery is asynchronous and disabled until
the configured provider and sender identity are ready.

Before launch, the operator still needs to configure the moderation provider in
dev/staging, run provider failure and allowed/blocked smoke tests, define who
reviews reports, and monitor the purge and moderation-failure paths. See
`docs/launch_readiness.md` for the consolidated launch status.
