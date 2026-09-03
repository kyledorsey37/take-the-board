# Security To-Do List

Use this checklist before opening Take the Board to significant public traffic or real-money users.
For the consolidated status of product, payment, moderation, infrastructure,
release-validation, and security work, see [launch readiness](launch_readiness.md).

## Critical before public launch

- [x] Add a first-paid-bid acknowledgement that the user is 18 or older, enforce
      it server-side, and preserve the acknowledgement with purchase evidence.
- [ ] Protect Django Admin at `/admin/` with an edge allowlist, VPN, or SSO.
- [x] Require MFA for every staff/admin account in non-local deployments using django-otp TOTP; enrollment and external access controls remain deployment tasks.
- [x] Add shared-cache admin login throttling with safe outage behavior; alert routing remains an external deployment task.
- [ ] Split deployment environment files so Postgres receives only `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD`.
- [x] Remove Cognito access, ID, and refresh tokens from Django sessions unless they are genuinely needed. Profile hydration is the only post-exchange token use; the session now stores only local identity and expiry, and legacy token fields are scrubbed on read.
- [x] If tokens must remain in sessions, encrypt the session values and document the key-rotation procedure. Not applicable: no Cognito tokens remain in Django sessions.
- [x] Make payment and historical records view-only in Admin: `StripeEvent`, `LedgerEntry`, `Bid`, `BoardTakeover`, `BidConfirmation`, `PaymentCapture`, and `PurchaseEvidence`.
- [x] Disable Admin add/change/delete permissions and bulk actions for immutable records.
- [x] Audit administrative state changes for user controls, board controls, moderation remediation, and game configuration.

## Deployment fail-closed checks

- [x] Reject known/default Django and moderation secret keys outside local development, with length and diversity checks.
- [x] Reject `DJANGO_ALLOWED_HOSTS=*` in staging and production.
- [x] Require explicit `TAKEBOARD_ENVIRONMENT` and prevent accidental use of local settings outside local development.
- [ ] Apply the same required integration checks in staging and production for Cognito, Stripe, Redis, and database configuration.
- [ ] Ensure production and staging use Gunicorn, never `runserver` or `--insecure`.
- [ ] Set secret files to owner-readable only: `chmod 600 .env` and equivalent server files.
- [ ] Keep `.env*`, database dumps, backups, private keys, and cloud credentials excluded from Git and Docker build contexts.
- [x] Add a secret scanner to pre-commit/CI. `scripts/scan_secrets.sh` runs Gitleaks against the current worktree; `.pre-commit-config.yaml` provides the local hook and `.github/workflows/security.yml` runs the redacted, read-only checks on pull requests and pushes to `main`.
- [ ] Run the one-time Git-history secret scan before the first public launch, using the process in `docs/dev_environment_setup.md`.
- [x] Pin dependencies with a lock file or hashes and add dependency vulnerability checking. `requirements.lock` is generated from `requirements.txt`; `scripts/audit_dependencies.sh` runs pip-audit without credentials.
- [ ] Enable hosted repository dependency alerts as an operator configuration gate.

## Browser and HTTP hardening

- [x] Add a tight Content Security Policy in report-only mode.
- [ ] Self-host or integrity-pin third-party frontend assets where practical, especially HTMX.
- [ ] Keep Stripe.js loaded only from Stripe's official origin.
- [x] Add application-owned `Permissions-Policy` and baseline security headers; edge headers remain external.
- [x] Add `Cache-Control: no-store` to authentication start, verify, resend, and OAuth callback responses.
- [x] Validate or replace malformed/oversized client-supplied `X-Request-ID` values.

## Authentication and authorization tests

- [ ] Verify user A cannot read user B's bid status.
- [ ] Verify user A cannot submit confirmation for user B's confirmation UUID.
- [ ] Verify expired, consumed, and replayed confirmations fail safely.
- [ ] Verify OAuth `state` is one-time, session-bound, and rejects mismatches.
- [ ] Verify `next` redirects cannot leave the site.
- [ ] Verify OTP start, verify, and resend limits work across multiple app instances through shared Redis.
- [ ] Verify expired Django sessions and Cognito access tokens lose access immediately.
- [ ] Verify logout clears authentication state and rotates/invalidates the session as appropriate.

## Public data and privacy review

- [ ] Confirm that board names, public display names, takeover messages, and spending totals are intentionally public.
- [ ] Confirm that no public template or JSON response exposes email addresses, Cognito subjects, payment identifiers, request headers, or raw provider payloads.
- [ ] Restrict access to raw Stripe webhook payloads and purchase evidence to the smallest staff group.
- [ ] Define retention and deletion rules for emails, IP addresses, user agents, moderation text, and Stripe payloads.
- [ ] Ensure moderation purge jobs run on a schedule and are monitored.
- [ ] Review Sentry, application logs, reverse-proxy logs, and analytics for message text, tokens, emails, payment data, and query-string leaks.

## Abuse, payment, and webhook checks

- [ ] Verify every real-money bid is authenticated, moderation-approved, risk-checked, and rechecked at checkout.
- [ ] Verify Stripe webhook signatures against the raw request body.
- [ ] Verify duplicate and out-of-order webhooks are harmless.
- [ ] Verify browser success redirects never publish or authorize a takeover by themselves.
- [ ] Verify Stripe idempotency keys are stable across retries.
- [ ] Verify authorization cancellation, capture, refund, dispute, and ledger transitions are idempotent.
- [ ] Verify Redis/rate-limit outages fail closed for moderation, checkout, reporting, and other abuse-sensitive writes.
- [ ] Add AWS WAF rules for admin, auth, webhook, checkout, and high-volume polling paths.

## External smoke tests before launch

From outside the server/network, verify:

- [ ] `/.env` and `/.env.dev` are unavailable.
- [ ] `/.git/HEAD` is unavailable.
- [ ] `/db.sqlite3`, dumps, backups, and server files are unavailable.
- [ ] `/admin/` is blocked or protected by the intended access control.
- [ ] Invalid Host headers are rejected.
- [ ] HTTP redirects to HTTPS without serving application content first.
- [ ] 400, 403, 404, and 500 responses contain no traceback, SQL, filesystem path, secret, token, or user content.
- [ ] Public pages render a message containing HTML/script characters as text, never as markup.
- [ ] Unauthorized API requests return generic errors without revealing whether another user's object exists.

## Evidence to keep with the launch review

- [ ] Output from `python manage.py check --deploy` using production-like settings.
- [ ] Results of the external smoke-test commands above.
- [ ] Results of authentication, authorization, XSS, payment, webhook, and race-condition tests.
- [ ] Confirmation that production secrets were rotated after any local/shared testing.
- [ ] A named owner and review date for Admin access, secret rotation, dependency updates, WAF rules, backups, and monitoring alerts.
