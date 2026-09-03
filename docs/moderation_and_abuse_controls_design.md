# Moderation And Abuse Controls Design

## Status

Proposed implementation design for the MVP. This document operationalizes the
product rules in `docs/moderation_policy.md` and the security requirements in
`docs/security_baseline.md`. It does not authorize public launch or live Stripe
payments until the required controls and tests are complete.

## Goals

- Prevent harmful public board messages and display names.
- Allow normal college-football rivalry trash talk and ordinary profanity.
- Prevent a caller from turning moderation into an unbounded Bedrock expense.
- Require an approved moderation result before a Stripe Checkout Session is
  created.
- Make moderation decisions auditable without logging sensitive free-form text.
- Provide clear, generic user feedback and actionable Django Admin operations.

## Non-Goals

- Perfectly classify every euphemism, coded phrase, or novel abuse pattern.
- Make AWS WAF the source of truth for application-level abuse prevention.
- Build a custom operations dashboard. Django Admin is sufficient for MVP.
- Support public display-name changes. Display names remain immutable for users
  after approval; an administrator can correct a name when necessary.

## Terms

- **Display name**: the public board name attached to a Cognito-authenticated
  user. It is not the Cognito username, which is the user's email in the
  current flow.
- **Candidate**: a message or display name submitted for validation.
- **Canonical form**: a safety-only normalized representation used for policy
  matching and cache keys. It is not what is shown to users.
- **Uncached classifier call**: a request that reaches Bedrock after all local
  validation and decision-cache checks.
- **Validation token**: a short-lived, server-side `MessageValidation` record
  proving that one exact candidate was approved for one exact action.

## Product Decisions

### Public Board Messages

Board messages can include ordinary profanity, team and fanbase insults, and
ordinary rivalry arguments. They cannot include slurs, hate speech, credible
threats, doxxing, personal contact information, targeted sexual harassment,
illegal content, spam, or URLs.

The current message limit remains the configured 80 characters. No inference is
performed during typing. A candidate is validated only after the user submits a
bid.

### Public Display Names

Display names require a separate policy and validation record. They appear in
board history, leaderboards, and other public surfaces, so they must not be
treated as a less important board message.

For MVP, a display name must:

- be 3 to 40 characters after trimming;
- use only ASCII letters, digits, single spaces, `_`, and `-`;
- begin and end with a letter or digit;
- avoid repeated separators or whitespace;
- not contain a slur, threat, sexual content, URL, contact information, or
  prohibited phrase;
- not impersonate Take the Board, an administrator, support, a school, a team,
  an official entity, a coach, an athlete, or another notable person; and
- not use reserved product, school, team, or operational names.

The original approved display value is stored and rendered unchanged. The
canonical form is only for safety checks. For example, `BoomerSooner` and
`boomer_sooner` can both be valid display names if each passes policy. They do
not become the same stored value merely because their canonical safety forms
are similar.

### Display-Name Uniqueness

`UserProfile.display_name` is already protected by both a database uniqueness
constraint and a case-insensitive database uniqueness constraint. Therefore,
`BoardBoss` and `boardboss` cannot coexist, including under a concurrent race.

Do not replace this with application-only checks. The application pre-check is
for a friendly response; the database remains the authoritative race-safe
guarantee. The MVP intentionally does not treat every punctuation variation as
a uniqueness collision.

Legacy display names created before this design must be audited. Administrators
should rename, remove, or ban any name that the new policy would reject before
external testing begins.

## Threat Model

The implementation must address:

- repeated candidate submissions intended to create Bedrock cost;
- distributed traffic using many IP addresses or accounts;
- repeated variants of the same disallowed phrase;
- checkout creation attempts that bypass moderation;
- duplicate browser submits and stale approval reuse;
- public-name impersonation and Unicode/lookalike bypasses;
- accidental logging of candidate text, prompts, model outputs, email addresses,
  OTPs, tokens, or payment data; and
- a moderation provider outage or slow response.

An authenticated account is useful friction but is not a sufficient control.
The system must limit by user, IP, candidate, and a global budget.

## Architecture

```text
Browser POST
  -> Django authentication and CSRF
  -> inexpensive request rate limit
  -> deterministic validation
  -> decision cache lookup
  -> uncached-call rate limits and global circuit breaker
  -> Bedrock classifier, only if necessary
  -> durable validation record
  -> transactionally consume validation and create bid/Checkout
```

Redis is the shared store for all rate limits, cache entries, counters, and
short-lived concurrency locks. The development EC2 Redis container is adequate
for this purpose. Production moves the same contract to managed Redis.

PostgreSQL stores durable validation and moderation-review records. It is never
used as the hot-path rate limiter.

## Validation Layers

### Layer 0: Request And Identity Gate

Before processing a candidate:

- require a valid Django session, a Cognito-authenticated `UserProfile`, and a
  non-banned user for any paid or moderation-protected action;
- require CSRF on every browser mutation request;
- enforce body-size limits before parsing candidate text;
- derive the client IP only from a trusted proxy configuration in production;
  never trust a browser-supplied forwarding header on the EC2 host; and
- enforce a cheap endpoint rate limit before any normalization or model work.

### Layer 1: Deterministic Validation

Deterministic checks have no Bedrock cost and run before all model calls. They
must reject:

- empty or over-limit content;
- control characters, invisible separators, and excessive Unicode abuse;
- URLs, email addresses, phone numbers, street-address patterns, and direct
  contact requests;
- spam-like repetition and excessive punctuation;
- obvious slurs, threat patterns, prohibited terms, and reserved names;
- malformed display-name characters and separator rules; and
- candidates that match a locally maintained prohibited-pattern list after
  safety normalization.

The prohibited-pattern list is versioned application data, reviewed in code,
and covered by tests. It must not be emitted to public responses or client-side
JavaScript.

### Layer 2: Decision Cache

After deterministic validation, look for a prior decision with a key derived
from:

```text
content type + canonical candidate + policy version + classifier model version
```

The key is an HMAC using a server-only `MODERATION_HASH_SECRET`, not a raw
candidate or an unsalted SHA-256 hash. This prevents Redis keys and logs from
becoming a dictionary of submitted content.

Cached allowed decisions may be reused only when the candidate and relevant
policy context exactly match. A message approval also remains bound to the
authenticated user, board, represented school, and expiration window before it
can unlock Checkout.

Cache allowed and blocked model decisions. Use a shorter TTL for ambiguous or
review decisions. A policy/model version change naturally invalidates stale
cache entries.

### Layer 3: Bedrock Classification

Call Bedrock only for candidates that passed deterministic checks and do not
have a reusable cache decision. The classifier receives the minimum necessary
context: content type, policy version, and candidate. Do not send account
email, Cognito identifiers, payment information, IP address, or unrelated board
history.

The classifier contract must return strict structured data:

```json
{
  "decision": "allow | block | review",
  "category": "safe_category_name",
  "confidence": 0.0
}
```

Use a fixed prompt, low-variance generation settings, a short timeout, and an
allowlist of expected categories. Treat malformed model output, timeout,
throttling, or an unavailable Bedrock service as a temporary rejection. Do not
create Checkout and do not default to allow.

The first implementation should use a model interface in
`apps/moderation/services/`, keeping AWS SDK calls inside a Bedrock adapter. The
current `nova_classifier.py` placeholder is the intended boundary.

The prompt must explicitly treat a standalone first name, public athlete or
coach reference, team, mascot, school tradition, cheer, or rivalry slogan as a
public sports reference rather than personal information. Personal information
means contact details or uniquely identifying private-person information. A
prompt or policy change must bump `TAKEBOARD_MODERATION_POLICY_VERSION` so the
decision cache cannot reuse a result produced under older semantics.

The explicit developer command `python manage.py evaluate_bedrock_moderation`
runs the 250-case synthetic regression suite described in
`docs/moderation_bedrock_evaluation.md`. It bypasses deterministic validation
and the decision cache, persists no moderation records, and reports only
aggregate/per-case-ID normalized results.

### Layer 4: Durable Decision And Action Binding

An allowed message creates a short-lived `MessageValidation` record. The record
must include the existing user, board, represented school, candidate hash,
decision, category, confidence, expiration, and consumed time. Add policy and
classifier version fields if they are not otherwise available in the audit
trail.

Add a foreign key from `Bid` to the validation record. Checkout creation must
verify, in the same database transaction, that the validation:

- belongs to the current user;
- matches the board, represented school, and exact candidate;
- is allowed and unexpired;
- has not already been consumed; and
- was approved under the active moderation policy.

The transaction consumes the validation before creating the bid. A duplicate
browser submit must not reuse a validation to create multiple Checkout Sessions.
If Checkout setup fails before a payment session is created, define an explicit
retry policy rather than silently leaving an unusable validation consumed.

Display-name approval uses a separate `DisplayNameValidation` record because it
is not board- or checkout-specific. It records the user, original value as
needed for review, canonical HMAC, decision, category, policy/model version,
and timestamps. A successful display-name write occurs only after its approval
and the existing database uniqueness constraint both succeed.

## Rate Limiting And Cost Controls

All limits are configuration values, not magic constants embedded in views.
These values leave room for normal trial-and-error while retaining a hard global
cap on uncached model calls.

| Surface | User limit | IP limit | Global protection |
| --- | --- | --- | --- |
| Auth email start | Existing 5/minute | Existing 5/minute | Existing Redis availability |
| Display-name validation | 10 uncached/hour | 30 uncached/hour | 30 uncached/minute |
| Message moderation | 20 uncached/10 minutes | 60 uncached/10 minutes | 30 uncached/minute |
| Rejected message/name attempts | escalating cooldown after 8 failures | escalating cooldown | counted in alert metric |
| Checkout creation | 3/10 minutes | 10/10 minutes | 50/minute |
| Bid-status polling | 30/minute | 60/minute | 500/minute |

The basic moderation endpoint quota is 60 message requests per user and IP per
10 minutes, and 30 display-name requests per user and IP per hour. Rejection
backoff starts at 30 seconds after the eighth rejection and doubles only up to
five minutes. These controls are intentionally separate from the uncached model
quota, so a user can correct a rejected message without immediately exhausting
the Bedrock budget.

Cached moderation decisions do not consume an uncached Bedrock-call quota, but
they still pass through a basic HTTP endpoint rate limit. This prevents a cache
hit from becoming an application resource-exhaustion route.

Implement each expensive action with all of these controls:

- per-user counter keyed by immutable user ID;
- per-IP counter keyed by a privacy-preserving HMAC;
- candidate counter keyed by the canonical candidate HMAC;
- global rolling counter for uncached model calls;
- small Redis semaphore for concurrent Bedrock calls; and
- a circuit breaker that rejects new uncached work when the global allowance is
  exhausted or Bedrock is unhealthy.

The user-facing circuit-breaker response is generic: "Validation is busy. Try
again shortly." It must not say whether a request would have passed moderation.

Set an AWS Budget and CloudWatch alert for Bedrock spend and invocation errors,
but treat alerts as notification, not prevention. The Redis global cap is the
hard application-side bound on request volume.

## WAF Role

AWS WAF is defense in depth, not a replacement for Redis limits.

The current development topology is EC2 plus Caddy. A WAF cannot attach directly
to that EC2 instance. Do not add an ALB or CloudFront solely to unblock this
work. The application-level controls above protect dev and carry forward to
production.

In production, attach WAF to the ALB or CloudFront distribution and add:

- AWS managed baseline rules;
- rate-based rules scoped to auth, moderation, checkout, and polling paths;
- a separate stricter rule for expensive POST endpoints;
- IP reputation and bot controls if public traffic justifies their cost; and
- CloudWatch metrics and sampled-request review.

WAF is effective against obvious floods from one source or network. A distributed
attack with many IPs and accounts can remain under an edge threshold, which is
why user-aware and global limits must still run inside Django.

## User Experience

Use one generic policy rejection for public messages and names. Do not disclose
the model category, matching rule, or exact term that caused a failure.

Suggested message:

```text
That does not meet the Take the Board community guidelines.
```

For a temporary limit or provider outage, distinguish only the action to take:

```text
Validation is busy. Try again shortly.
```

The browser may show character and formatting guidance for display names, but
must not implement authoritative moderation or expose prohibited patterns.

## Data Retention And Privacy

- Never log raw candidate text, normalized content, prompts, model outputs,
  email addresses, OTPs, Cognito tokens, Stripe payloads, or payment data.
- Structured logs may include request ID, user ID, validation type, cached flag,
  decision, category, policy/model version, latency bucket, and rate-limit
  outcome.
- An approved board message is retained as part of the bid and takeover history.
- Retain raw blocked or review candidates only when required for Django Admin
  review, for a documented short retention period of 30 days. Purge them with a
  scheduled job while retaining decision metadata and HMAC for abuse analysis.
- Do not persist full Bedrock responses. Persist only the normalized decision,
  allowed category, confidence when useful, and model/policy version.
- Restrict Django Admin access to moderation records and audit all destructive
  moderation actions.

## Django Admin Operations

MVP Admin must support:

- filtering message and display-name validations by decision, category, board,
  user, date, and expiration;
- reviewing the limited-retention candidate text where permitted;
- banning a user and disabling bidding on a board;
- removing a current board message through an audited action;
- correcting or clearing a prohibited display name;
- refund/dispute handoff without deleting historical records; and
- an immutable action audit with actor, target, reason, and timestamp.

## Implementation Plan

### Phase 1: Shared Foundations

1. Add a shared Redis-backed rate-limit module with atomic increment, TTL,
   cooldown, concurrency-semaphore, and global-circuit-breaker helpers.
2. Add safe identity-key helpers that HMAC user IDs, IPs, and canonical content.
3. Add structured event names for validation start, cache hit, deterministic
   reject, model result, rate limit, provider failure, and checkout gate result.
4. Add settings for limits, policy version, Bedrock model ID, timeout, and the
   moderation HMAC secret.

### Phase 2: Deterministic Validators

1. Implement shared text normalization for policy evaluation.
2. Implement a message validator and a stricter display-name validator.
3. Add versioned reserved-name and prohibited-pattern data.
4. Wire display-name validation into `accounts:set_display_name` before the
   existing uniqueness pre-check and database save.

### Phase 3: Durable Validation And Checkout Gate

1. Add the required migrations for validation metadata and `Bid` linkage.
2. Implement message-validation creation, expiration, and one-time consumption.
3. Require a valid approved validation in the Stripe Checkout creation path.
4. Add a cleanup job for expired validations and expired raw blocked/review
   content.

### Phase 4: Bedrock Adapter

1. Implement the Nova/Bedrock adapter behind the existing classifier boundary.
2. Add a minimal IAM permission for the dev EC2 role and, later, the production
   ECS task role.
3. Add provider timeout, malformed-response, throttle, and outage behavior.
4. Enable Bedrock only after deterministic and Redis controls pass tests.

### Phase 5: Operations And Edge Protection

1. Add Django Admin actions and audit records.
2. Configure Budgets, CloudWatch alerts, and Sentry alerts for classifier errors
   and circuit-breaker trips.
3. Add path-scoped WAF controls when the production ALB/CloudFront deployment is
   created.
4. Run a display-name audit and controlled abuse test before inviting outside
   testers.

## Required Tests

- deterministic message rejection for URLs, contact information, threats,
  slurs, separator bypasses, control characters, and oversized input;
- allowed normal rivalry trash talk and ordinary profanity;
- display-name format, reserved-name, impersonation, and separator-bypass tests;
- case-insensitive display-name uniqueness and concurrent save race tests;
- cache-hit behavior that does not call Bedrock or consume uncached quota;
- user, IP, candidate, global, cooldown, and concurrency rate-limit tests;
- provider timeout, throttling, malformed response, and unavailable-provider
  fail-closed tests;
- no Checkout Session when moderation is absent, blocked, stale, mismatched, or
  already consumed;
- exactly-one Checkout Session under duplicate concurrent submission;
- no raw candidate, prompt, token, or Stripe payload in captured logs; and
- admin authorization and retention-purge tests.

## Completion Criteria

This work is complete for controlled external testing when:

- both messages and display names follow their policies;
- all expensive moderation calls have shared Redis limits and a global cap;
- repeated candidate attempts are served from a safe decision cache;
- Checkout cannot be created without a fresh, matching approval;
- the classifier fails closed;
- names are uniquely enforced by the database case-insensitively;
- blocked/review content follows the documented retention policy;
- administrators can review, ban, remove, and audit; and
- the required abuse, concurrency, payment-gate, and logging tests pass.
