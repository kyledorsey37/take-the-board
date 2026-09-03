# Friday Production Smoke Test

Use this runbook after the production image, ECS services, DNS, secrets, and
external providers are deployed. It is the release gate for the production
environment; passing the Django test suite or a local Docker check is not a
substitute for this run.

## Goals

- Confirm the deployed image is the intended release and the web service is
  healthy behind the public HTTPS endpoint.
- Confirm production settings, secrets, Redis, database migrations, and
  CloudWatch logging are operating.
- Confirm Sentry receives one intentional production exception through the
  production-only SDK and quota gate.
- Confirm public error behavior is safe and expected traffic does not create
  Sentry events.
- Avoid creating a live payment, refund, moderation case, or public test
  message unless the release owner explicitly approves a separate provider
  drill.

## Required access and evidence

Before starting, have:

- AWS access for ECS, CloudFormation, CloudWatch Logs, Secrets Manager, and
  the production task definition.
- Sentry project access and the production project/environment selected.
- The deployed image tag or immutable image digest and git SHA.
- The production hostname and a test browser/account only if the auth flow is
  included in this release.

Record the following in the release ticket:

```text
Date/time (UTC):
Release SHA/image digest:
ECS cluster:
Web service/task:
Worker service/task:
Production URL:
Operator:
Sentry issue URL:
CloudWatch log stream(s):
Result: PASS / HOLD / ROLLBACK
Notes:
```

## Stop conditions

Stop the smoke test and hold the release if any of these occur:

- The public site returns a 5xx, the health check fails, or ECS repeatedly
  replaces tasks.
- The task is not running with `TAKEBOARD_ENVIRONMENT=production`, or the
  deployed image/release is not the intended SHA.
- `SENTRY_DSN` is missing from the production task or appears in logs.
- Redis or the database is unavailable, migrations fail, or the worker is
  repeatedly failing.
- A test action creates an unexpected charge, authorization, refund, public
  message, or moderation side effect.
- The intentional Sentry event does not appear after checking the task logs,
  Sentry environment, release, and Redis connectivity.

## 1. Deployment and ECS preflight

1. Confirm the CloudFormation stacks and services use the intended image.
   The production compute template names the relevant resources using the
   `prod` environment, including `takeboard-prod`,
   `takeboard-prod-web`, and `takeboard-prod-worker`.
2. Confirm the web and worker task definitions contain:
   - `TAKEBOARD_ENVIRONMENT=production`;
   - `DJANGO_SETTINGS_MODULE=config.settings.production`;
   - `DJANGO_DEBUG=false`;
   - `SENTRY_DSN` sourced from Secrets Manager, never a plaintext environment
     value or command-line argument;
   - the production `DATABASE_URL` and shared `REDIS_URL` secrets.
3. Confirm the web task is healthy and the worker is intentionally enabled or
   disabled according to the release plan. A dormant worker is expected for a
   no-paid-bidding preview, but not after paid bidding is enabled.
4. Check the web and worker CloudWatch streams for startup errors, migration
   failures, repeated restarts, secret-resolution errors, or Redis connection
   errors. Do not paste raw log payloads, tokens, headers, or payment-provider
   responses into the release ticket.

Example read-only commands:

```sh
aws ecs describe-services \
  --cluster takeboard-prod \
  --services takeboard-prod-web takeboard-prod-worker \
  --query 'services[].{service:serviceName,desired:desiredCount,running:runningCount,pending:pendingCount}'

aws logs tail /ecs/takeboard/prod/web --since 15m
aws logs tail /ecs/takeboard/prod/worker --since 15m
```

## 2. Public HTTPS smoke test

Run these against the real public hostname, not `localhost` or the ALB's raw
DNS name:

```sh
curl --fail --silent --show-error --location \
  --output /dev/null --write-out 'home_http=%{http_code}\n' \
  https://taketheboard.com/

curl --fail --silent --show-error --location \
  --output /dev/null --write-out 'health_http=%{http_code}\n' \
  https://taketheboard.com/healthz/

curl --fail --silent --show-error --location \
  --output /dev/null --write-out 'alabama_board_http=%{http_code}\n' \
  https://taketheboard.com/schools/alabama/

curl --silent --show-error \
  --output /dev/null --write-out 'unknown_path_http=%{http_code}\n' \
  https://taketheboard.com/this-path-does-not-exist/

curl --silent --show-error --output /dev/null --write-out 'retired_debug_route_http=%{http_code}\n' \
  https://taketheboard.com/sentry-debug/
```

Expected results:

- Home, health, and the Alabama board return `200`.
- The unknown path returns the branded `404` page.
- `/sentry-debug/` returns `404`; there is no intentional public error route.
- The 404 and retired debug route do not create Sentry issues.

Check headers and the response body manually for HTTPS redirect behavior,
security headers, no traceback/SQL/path disclosure, correct canonical host,
escaped public board content, and a visible support/request ID only where the
public error template intentionally provides one.

## 3. Production Sentry verification

This is the only intentional failure in this runbook. It uses a disposable
one-off ECS task with the deployed production web task definition, the same
private subnets/security group, the same task role, and the same Secrets
Manager values. It does not run through the public web service and does not
touch the database or payment providers.

The current ECS template does not enable ECS Exec, so use the ECS console's
“Run new task” flow from the current `takeboard-prod-web` task definition:

1. Select the same VPC, private subnets, security group, task role, and
   `AssignPublicIp=DISABLED` settings as the web service.
2. Override the `web` container command with these five command-array values:

   ```text
   python
   manage.py
   shell
   -c
   raise RuntimeError("Friday production Sentry smoke test")
   ```

3. Start the one-off task and expect the task to stop with a non-zero exit
   code. That failure is intentional and must not affect the running web
   service.
4. Wait up to two minutes, then search the Sentry project with:

   ```text
   environment:production takeboard_sentry_source:unhandled_5xx
   ```

   The event should show the deployed release and the redacted exception
   value. The event should not contain request headers, user data, raw URLs,
   breadcrumbs, local variables, or payment data.
5. Confirm the event arrived in the `production` environment and is visible in
   Sentry Issues. Record its URL in the release ticket, then resolve or ignore
   this intentional test issue.

This consumes one unhandled-event slot. Do not repeatedly rerun the command
while troubleshooting: the shared gate deduplicates the same exception type
for six hours and limits unhandled events to one per hour. Check CloudWatch
and the Sentry project configuration before attempting another test.

If ECS Exec is enabled in a future deployment, the equivalent command inside
an existing production web task is:

```sh
python manage.py shell -c 'raise RuntimeError("Friday production Sentry smoke test")'
```

Never use a public URL, a real checkout, a live card, or a production user
action to force this error.

## 4. Confirm the quota guardrails

In Sentry and CloudWatch, verify the following implementation contract:

- Sentry environment is `production`; development and staging are absent.
- Application logger errors are present only in structured CloudWatch-ready
  logs and do not automatically create Sentry events.
- The production gate allows at most three critical incidents and one
  unhandled exception event per hour.
- Repeated events of the same admitted type are suppressed for six hours.
- A Redis/cache failure fails closed for Sentry and produces a structured
  `sentry_event_suppressed_cache_unavailable` log.
- Expected 4xxs, unknown paths, validation/moderation outcomes, rate limits,
  duplicate messages, payment declines, and ordinary provider retries do not
  create Sentry events.

Do not clear production Redis keys to force a second test. That can interfere
with rate limits and incident deduplication for the live application.

## 5. Optional no-money application checks

Run only the checks enabled by the release plan:

- Open the home page, board directory, Alabama board, rivalry page, and
  leaderboard in a browser.
- Verify the cookie-consent behavior and confirm GA4 is loaded only after
  consent, if analytics is enabled for production.
- Verify Cognito login/logout with a designated test account if authentication
  is enabled.
- Verify an unauthenticated bid attempt is rejected without creating a bid or
  payment record.
- Verify the admin login/MFA path only with the designated operator and test
  device.
- Verify a safe moderation rejection only in a test/staging environment. Do
  not publish a production test message merely to exercise moderation.

Do not run a live Stripe Checkout, authorization, capture, refund, dispute,
or payment-remediation test as part of this smoke test. Use the documented
Stripe test-mode flow in staging, or obtain explicit release-owner approval
for a separately controlled production provider drill.

## 6. Final review and rollback

The release is **PASS** only when the public checks, ECS/CloudWatch checks, and
the Sentry verification all pass. If the app is healthy but Sentry is missing,
mark the release **HOLD** and keep paid bidding disabled until the Sentry
secret, network path, Redis connectivity, and Sentry project filters are
resolved.

If a web or worker regression is found, follow the deployment rollback plan to
restore the last known-good immutable image. Do not remove Sentry or disable
the shared cache as a workaround. Preserve the release SHA, task stop reason,
request IDs, CloudWatch stream names, and Sentry issue URL for investigation;
never preserve raw secrets, headers, payment payloads, or user message text.

## Completion record

After the run, update [launch readiness](launch_readiness.md) with the date,
release SHA, Sentry issue URL, and result. The Sentry implementation may be
marked **Done** after code review and automated tests; this manual production
smoke test remains a required Friday release check until recorded as passed.
