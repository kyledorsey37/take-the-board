# Security Baseline

This document is the source of truth for the initial Take the Board security posture. Attached design docs are reference material; current user requests and this repo's committed docs govern implementation.

## Application Shape

- Django monolith running behind an ALB in production.
- Django sessions and CSRF protection for browser-originating mutation endpoints.
- Django Admin for MVP operations.
- PostgreSQL for core app state.
- Cognito Hosted UI later for authentication; Django must validate OAuth `state` and Cognito tokens before trusting identity.

## Secrets

- No secrets are committed.
- `.env*` files are excluded from Git and Docker build context.
- Production secrets belong in AWS Secrets Manager or SSM Parameter Store.
- ECS task roles should be used for AWS service access instead of static AWS credentials.
- Expected production secrets include `DJANGO_SECRET_KEY`, `DATABASE_URL`, Cognito configuration, Stripe keys, Sentry DSN, and Bedrock configuration.

## Django Defaults

Security middleware, CSRF middleware, session middleware, auth middleware, and clickjacking protection are enabled in `config/settings/base.py`.

Production settings require:

- `DEBUG = False`
- strict `DJANGO_ALLOWED_HOSTS`
- `SECURE_SSL_REDIRECT = True`
- `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`
- secure session and CSRF cookies
- HSTS with preload and subdomains
- `SECURE_CONTENT_TYPE_NOSNIFF = True`
- `SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"`
- `X_FRAME_OPTIONS = "DENY"`

## CSRF And Webhooks

Use CSRF protection for browser mutation endpoints, including message validation, checkout creation, profile updates, and future bid interactions.

Only verified third-party webhooks may be CSRF-exempt. Stripe webhooks must verify the Stripe signature against the raw request body, store the event idempotently, and return quickly.

## Logging

Structured JSON logging is enabled with request IDs. Logs may include IDs, booleans, status codes, endpoint names, and state transitions.

Do not log:

- secrets or tokens
- raw authorization headers
- raw Stripe payloads
- payment method data
- sensitive free-form user text
- full moderation prompts or raw model responses unless a future retention policy explicitly permits it

Payment and moderation work should log named state-transition events such as `message_validation_started`, `checkout_created`, `payment_authorized`, `payment_capture_success`, `payment_capture_failure`, `refund_created`, and `dispute_created`.

## Rate Limiting

Shared Redis rate-limit state protects message and display-name validation,
checkout creation, bid-status polling, and failed moderation attempts. Limits use
HMAC-derived user, IP, and candidate keys plus a global moderation cap and
concurrency circuit breaker. Use AWS WAF for edge/path/IP protection and
app-level limits for user-aware behavior.

## Error Monitoring

Server-side Sentry is wired by `SENTRY_DSN`. Browser-side Sentry should be added before public launch. Alerts should cover webhook failures, capture/cancel/refund failures, SQS worker failures, moderation failures, weekly reset failures, and database integrity errors.

## Public Error Pages

With `DEBUG = False`, Django uses branded standalone pages for 400, 403, 404, and 500 responses. They provide a route back to the product and may show the safe request ID for support follow-up, but never expose tracebacks, SQL, filesystem paths, secrets, tokens, or user content. Local development keeps `DEBUG = True` so developers can use Django's technical traceback page; that page must never be enabled in staging or production.
