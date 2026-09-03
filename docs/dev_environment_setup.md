# Dev Environment Setup

This document defines the first hosted development environment for Take the Board.
The goal is to keep dev cheap while proving the same image, settings, auth,
payment, webhook, and worker loop that production will use.

## Security and dependency checks

The application image and local launcher install the generated
`requirements.lock`, not the unconstrained input file. Regenerate it after an
intentional dependency update with the pinned security tools:

```bash
python3.12 -m venv .security-venv
.security-venv/bin/python -m pip install -r requirements-security.txt
.security-venv/bin/pip-compile --output-file=requirements.lock requirements.txt
```

Install the repository-managed pre-commit hook after creating the environment:

```bash
.security-venv/bin/python -m pre_commit install
```

The hook is used by Git regardless of whether a commit is created from VS Code
or a terminal. It invokes the pinned Gitleaks container declared in
`.pre-commit-config.yaml`, mounts the repository read-only, and does not scan
untracked local `.env` files. Docker Desktop must be running for the hook.
Use the following command for an explicit all-files check:

```bash
.security-venv/bin/python -m pre_commit run --all-files
```

Review the resulting diff, run the application tests, and commit the lock file
with the compatible range change in `requirements.txt` when one is needed.
Never put credentials in a requirements file or command-line argument.
Validate an existing lock without changing the environment with
`python3.12 -m pip install --dry-run -r requirements.lock`.

Run the safe, current-worktree checks locally or from CI:

```bash
./scripts/scan_secrets.sh
./scripts/audit_dependencies.sh
```

GitHub Actions runs these same checks on every pull request and every push to
the default branch. The workflow uses only read permission, immutable action
SHAs, a digest-pinned public Gitleaks image, redacted scanner output, and no
repository secrets or uploaded findings. Treat the local hook as convenience
and the GitHub status check as the merge backstop; configure that check as
required in branch protection or a repository ruleset.

Gitleaks is a separate binary; install it from the official Gitleaks release or
package manager before running the scanner. The committed `.gitleaks.toml`
excludes generated/vendor paths, ignored local secret files, and exact
non-secret local/build placeholders; the scanner separately fails if an env or
local key file is tracked. Findings should be investigated and removed, not
broadly allowlisted.

Before the first public launch, make a separate, read-only history scan from a
fresh clone after fetching all refs:

```bash
git fetch --all --tags --prune
gitleaks git --config .gitleaks.toml --redact --no-banner --log-opts="--all"
```

If history contains a real credential, stop the launch, revoke or rotate it at
the provider, preserve only safe incident metadata, remove the current-tree
copy, and follow the repository's approved history-remediation process. Do not
rewrite Git history casually or treat a history scan as a substitute for
credential rotation. Configure repository dependency alerts (for example,
Dependabot or an equivalent hosted service) separately; no cloud credential is
needed by the local audit command.

## One-off Resend test

To test Resend without changing Django settings or the worker, put one
development API key in the ignored `.resend-dev-key` file at the repository
root. Do not commit it or pass it as a command-line argument. Then run:

```bash
chmod 600 .resend-dev-key
python3 scripts/test_resend_email.py \
  --key-file .resend-dev-key \
  --from "Take the Board <notifications@taketheboard.com>" \
  --to your-email@example.com
```

The script sends exactly one labeled test email and prints only the Resend
provider ID or a generic HTTP/network error. The sender domain must be
verified in Resend.

## Target Shape

Use separate AWS accounts from the start:

```text
ttb-management
  ttb-dev
  ttb-prod
```

The management account owns AWS Organizations, consolidated billing, IAM
Identity Center, and optionally the root Route 53 hosted zone. Do not run app
infrastructure, databases, app secrets, or payment-adjacent resources in the
management account.

The dev account starts with:

```text
Local deploy script
  -> build Docker image
  -> push to dev ECR
  -> deploy git SHA tag to EC2

EC2
  -> Caddy HTTPS reverse proxy
  -> Django web container
  -> Django worker container
  -> PostgreSQL container
  -> Redis container

Cognito dev user pool
Stripe test-mode webhook endpoint
Structured application logs (CloudWatch-ready)
CloudWatch logs
```

Production can later use the same Docker image and environment contracts behind
ECS/Fargate, an ALB, WAF, RDS PostgreSQL, S3/CloudFront static assets, managed
Redis, and production-grade alarms.

## Account Baseline

Create these accounts in AWS Organizations:

- `ttb-management`
- `ttb-dev`
- `ttb-prod`

Recommended IAM Identity Center permission sets:

- `AdministratorAccess-Dev`
- `AdministratorAccess-Prod`
- `ReadOnly-Prod`
- `Billing`

Create a local AWS CLI profile for the dev account, for example:

```bash
aws configure sso --profile ttb-dev
aws sts get-caller-identity --profile ttb-dev
```

Use one primary region for MVP infrastructure. `us-east-1` is a practical
default unless there is a strong reason to choose another region.

## Dev Resources

Create these resources in `ttb-dev`.

### ECR

Create one private ECR repository:

```text
ttb-dev
```

Tag images with the git SHA. Optionally also maintain a moving `dev-latest`
tag, but deploy by immutable SHA when testing specific releases.

### Network

For the cheapest first pass, use the default VPC or a small custom VPC with:

- one public subnet for the EC2 host
- outbound internet access from EC2 so it can pull from ECR

Security groups:

- `ttb-dev-web`
  - inbound `80/tcp` from `0.0.0.0/0`
  - inbound `443/tcp` from `0.0.0.0/0`
  - no SSH inbound if using SSM Session Manager

Prefer SSM Session Manager over SSH. If SSH is temporarily needed, restrict it
to a trusted source IP and remove it when done.

### EC2

Use one small Amazon Linux instance with:

- Docker
- Docker Compose plugin
- AWS CLI
- SSM agent
- an Elastic IP
- an instance profile that can read dev ECR and dev secrets

The EC2 instance hosts the files in `deploy/dev/` under `/opt/ttb`.

### PostgreSQL

Run PostgreSQL as a Docker container on the EC2 host for dev. This keeps the
environment cheap while still proving migrations, transactions, `DATABASE_URL`,
and persistence across app container restarts.

Use a named Docker volume for the database data and do not expose port `5432` to
the public internet.

The application and PostgreSQL containers use separate environment files:

```text
/opt/ttb/.env
/opt/ttb/.postgres.env
```

The application file is the Compose interpolation file and the `env_file` for
`web` and `worker`. It contains `DATABASE_URL` and the Django, auth, payment,
moderation, email, and other application settings. It must not be used as the
PostgreSQL container's `env_file`.

The PostgreSQL file is used only by `postgres` and must contain exactly these
three non-empty settings (comments and blank lines are allowed):

```text
POSTGRES_DB=ttb
POSTGRES_USER=ttb
POSTGRES_PASSWORD=<password>
```

Keep the password in `DATABASE_URL` synchronized with `POSTGRES_PASSWORD`, but
do not copy `DATABASE_URL` into the PostgreSQL file.

### Redis

Run Redis as a Docker container on EC2 for dev. This gives the app shared
cache/session/rate-limit state on the dev host without paying for ElastiCache.

Use:

```text
REDIS_URL=redis://redis:6379/0
```

### Cognito

Create a dev-only Cognito user pool and app client.

Required behavior:

- email-only sign-in identifier
- self-registration enabled
- passwordless email OTP support
- Hosted UI callback URL for the dev domain
- app execution role can call `cognito-idp:ListUsers`
- when Bedrock moderation is enabled, the EC2 instance profile can call only
  `bedrock:Converse` for the configured Nova model ARN; do not grant broad
  Bedrock administration or static AWS credentials to the container

For a dev domain of `https://dev.taketheboard.com`, configure:

```text
COGNITO_REDIRECT_URI=https://dev.taketheboard.com/auth/callback/
```

Use the actual callback path implemented by the app if it differs.

### Stripe

Use Stripe test mode only.

Create a webhook endpoint:

```text
https://dev.taketheboard.com/webhooks/stripe/
```

Store the test secret keys and webhook signing secret in the dev environment.

### DNS And TLS

Create a Route 53 record:

```text
dev.taketheboard.com -> EC2 Elastic IP
```

Caddy obtains and renews TLS certificates automatically for the dev domain.

## Dev Secrets And Environment

For the first manual pass, place a locked-down `.env` file on the EC2 host:

```text
/opt/ttb/.env
```

Move these values to SSM Parameter Store or Secrets Manager once the EC2 deploy
loop is proven.

Required variables:

```env
TAKEBOARD_DEV_DOMAIN=dev.taketheboard.com
TAKEBOARD_IMAGE=<dev-account-id>.dkr.ecr.us-east-1.amazonaws.com/ttb-dev:initial-tag
TAKEBOARD_ENV_FILE=.env
TAKEBOARD_POSTGRES_ENV_FILE=.postgres.env

DJANGO_SETTINGS_MODULE=config.settings.staging
DJANGO_SECRET_KEY=<dev-secret-key>
DJANGO_ALLOWED_HOSTS=dev.taketheboard.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://dev.taketheboard.com
DATABASE_URL=postgres://ttb:<password>@postgres:5432/ttb
REDIS_URL=redis://redis:6379/0

TAKEBOARD_DEMO_BIDDING_ENABLED=false
TAKEBOARD_COGNITO_AUTH_ENABLED=true
TAKEBOARD_AUTH_MODAL_PREVIEW=false
TAKEBOARD_REQUIRE_AUTH_FOR_BIDDING=true
TAKEBOARD_STRIPE_ENABLED=true
MODERATION_HASH_SECRET=<distinct-dev-secret>
TAKEBOARD_BEDROCK_ENABLED=false
TAKEBOARD_BEDROCK_REGION=us-east-1
TAKEBOARD_BEDROCK_MODEL_ID=
TAKEBOARD_BEDROCK_TIMEOUT_SECONDS=5

COGNITO_REGION=us-east-1
COGNITO_USER_POOL_ID=<dev-pool-id>
COGNITO_CLIENT_ID=<dev-client-id>
COGNITO_CLIENT_SECRET=
COGNITO_DOMAIN=https://<dev-cognito-domain>
COGNITO_REDIRECT_URI=https://dev.taketheboard.com/auth/callback/

STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

DJANGO_LOG_LEVEL=INFO
```

Use a confidential Cognito client secret only if the app client is created with
one.

Enable Bedrock only after the instance profile has the scoped `bedrock:Converse`
permission and the selected model has been enabled in the dev account. Until
then the moderation gate intentionally fails closed with a temporary validation
response; it never creates Checkout Sessions without a matching approval.

When the four `TAKEBOARD_BEDROCK_*` settings are present in the local `.env`,
`deploy/dev/deploy_dev.sh` synchronizes those settings to `/opt/ttb/.env` during
deployment. It does not copy the local secrets file to the host.

## EC2 File Layout

Recommended layout:

```text
/opt/ttb/
  .env
  .postgres.env
  Caddyfile
  docker-compose.yml
  staticfiles/
```

Copy the templates from:

```text
deploy/dev/Caddyfile
deploy/dev/docker-compose.yml
deploy/dev/env.example
deploy/dev/postgres.env.example
```

Use `deploy/dev/env.example` as the starting point for `/opt/ttb/.env` and
`deploy/dev/postgres.env.example` as the starting point for
`/opt/ttb/.postgres.env`. Do not commit real secret values. Both files must be
owner-readable only:

```bash
chmod 600 /opt/ttb/.env /opt/ttb/.postgres.env
```

`TAKEBOARD_POSTGRES_ENV_FILE` is resolved relative to `/opt/ttb` by the remote
deployment script and by Compose, defaulting to `.postgres.env`. An absolute
path is also supported when the host has already provisioned that file. A
relative path must remain under the deployment directory. If the application
file is stored somewhere else, set `TTB_APPLICATION_ENV_FILE` when invoking
`remote_deploy.sh`; the default remains `/opt/ttb/.env`. For the one-command
deploy, use `TTB_REMOTE_APPLICATION_ENV_FILE=/opt/ttb/application.env`.
When using a custom application path, set `TAKEBOARD_ENV_FILE` in that file to
the same relative path from `/opt/ttb` (or an absolute path) so Compose gives
`web` and `worker` the same file.

### Migrating an existing combined `.env`

The next `deploy/dev/deploy_dev.sh` run (or a direct `remote_deploy.sh` run)
performs a safe one-time split:

1. It validates an existing dedicated file, or extracts the three PostgreSQL
   settings from the legacy application file into a new `.postgres.env`.
2. It sets both files to mode `0600` and removes only the three legacy
   `POSTGRES_*` lines from the application file.
3. It refuses to continue if a required setting is missing, duplicated,
   malformed, or differs between the two files. No database credentials or
   environment values are printed.
4. It then runs the normal migration and image rollout.

This migration never initializes, renames, deletes, or rebuilds the database
volume or database. The existing Compose named volume is reattached unchanged;
only the app containers are recreated by the normal deploy path. The existing
`POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` values are preserved.
If the dedicated file is missing or malformed, fix it from the operator's
secret store or an approved backup and rerun the deployment; the script fails
before Compose starts. Do not use `docker compose down -v`, remove
`postgres_data`, or change the database settings during recovery.

If a pre-split image must be rolled back after a successful split, restore the
three settings to the application file from the dedicated file using a
credential-safe editor or deployment secret store, set `TAKEBOARD_IMAGE` to the
previous image tag, and redeploy. The previous image will still reattach the
same `postgres_data` volume. After the rollback, restore the split contract
before deploying a split-aware image again.

To validate or perform the split on a host without pulling up containers, run
the image's script with the validation flag. It still makes only the
owner-readable environment-file migration described above, then exits before
any Docker deployment action:

```bash
TTB_VALIDATE_DEPLOYMENT_ENV_ONLY=1 /opt/ttb/remote_deploy.sh ignored-image-reference
```

Keep `TAKEBOARD_DEV_DOMAIN=dev.taketheboard.com` and an initial
`TAKEBOARD_IMAGE` in `/opt/ttb/.env`. The deployment script updates the image
value on every deploy. Do not export either variable in the SSM shell session.

## One-Command Deploy Flow

Once the EC2 bootstrap is complete, deploy from the repository root with:

```bash
./deploy/dev/deploy_dev.sh
```

The script builds and pushes a uniquely tagged `linux/amd64` image, finds the
running dev instance tagged `Name=ttb-dev-ec2`, and uses SSM Run Command to pull
the image, refresh Compose and static files, run migrations, and recreate only
the web and Caddy services. PostgreSQL and Redis remain running with their
named volumes untouched. The remote bootstrap creates or validates the
PostgreSQL-only environment file before Compose starts. It starts the worker
when Stripe or demo bidding is enabled, and stops it when both are disabled.

If the instance has a different `Name` tag, run:

```bash
TTB_DEV_INSTANCE_NAME=<actual-name-tag> ./deploy/dev/deploy_dev.sh
```

Alternatively, pin an exact instance:

```bash
TTB_DEV_INSTANCE_ID=<instance-id> ./deploy/dev/deploy_dev.sh
```

Required local permissions are ECR push, `ec2:DescribeInstances`,
`ssm:SendCommand`, `ssm:GetCommandInvocation`, and SSM command status access.

## Manual Deploy Flow

Build and push from a trusted machine:

```bash
aws ecr get-login-password --region us-east-1 --profile ttb-dev \
  | docker login --username AWS --password-stdin <dev-account-id>.dkr.ecr.us-east-1.amazonaws.com

docker build -t ttb-dev:<git-sha> .
docker tag ttb-dev:<git-sha> <dev-account-id>.dkr.ecr.us-east-1.amazonaws.com/ttb-dev:<git-sha>
docker push <dev-account-id>.dkr.ecr.us-east-1.amazonaws.com/ttb-dev:<git-sha>
```

Deploy on the EC2 host:

This manual flow assumes the split files already exist. On a legacy host, run
the one-command deploy or the validation-only migration above before this
flow; do not start PostgreSQL from the combined `.env` contract.

```bash
cd /opt/ttb

aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin <dev-account-id>.dkr.ecr.us-east-1.amazonaws.com

docker pull "$TAKEBOARD_IMAGE"
docker run --rm "$TAKEBOARD_IMAGE" tar -C /app/staticfiles -cf - . \
  | tar -C /opt/ttb/staticfiles -xf -

chmod 600 /opt/ttb/.env /opt/ttb/.postgres.env
# The one-command deploy performs the legacy combined-.env migration when needed.
docker compose pull
docker compose run --rm web python manage.py migrate --noinput
docker compose run --rm web python manage.py seed_demo_data
docker compose up -d
```

The `seed_demo_data` command is acceptable in dev. Do not run it in production
unless a future production-safe seed command is created.

## Validation Checklist

The first dev environment is done when:

- `https://dev.taketheboard.com` serves the app over HTTPS.
- CSS and JavaScript load from `/static/`.
- Django runs with `DEBUG=False`.
- Two separate accounts can sign in through the dev Cognito user pool.
- Each account can choose and keep a stable display name.
- A user can create a Stripe test Checkout manual authorization.
- Stripe sends a signed webhook to the dev endpoint.
- Duplicate Stripe webhook delivery is stored idempotently.
- The worker processes the authorization and finalization path.
- Outbidding cancels the losing pending authorization.
- A winning takeover publishes and survives container restart.
- Database state survives app container restart and full `docker compose down && docker compose up -d`.
- PostgreSQL receives only `POSTGRES_DB`, `POSTGRES_USER`, and
  `POSTGRES_PASSWORD`; existing users, content, and database state remain on
  the unchanged `postgres_data` volume after the split and a container
  recreation.
- Dev does not send errors to Sentry.
- Structured JSON logs are visible through `docker compose logs` and can be
  forwarded to CloudWatch when that integration is configured.

## What Dev Intentionally Skips

Dev does not need:

- ALB
- WAF
- ECS/Fargate
- ElastiCache
- CloudFront
- multi-AZ RDS
- any RDS instance
- production Stripe keys
- production Cognito users

Those belong in the production account once the hosted app loop is proven.
