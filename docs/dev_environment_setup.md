# Dev Environment Setup

This document defines the first hosted development environment for Take the Board.
The goal is to keep dev cheap while proving the same image, settings, auth,
payment, webhook, and worker loop that production will use.

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
Sentry dev environment
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

Use:

```text
DATABASE_URL=postgres://ttb:<password>@postgres:5432/ttb
POSTGRES_DB=ttb
POSTGRES_USER=ttb
POSTGRES_PASSWORD=<password>
```

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

DJANGO_SETTINGS_MODULE=config.settings.staging
DJANGO_SECRET_KEY=<dev-secret-key>
DJANGO_ALLOWED_HOSTS=dev.taketheboard.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://dev.taketheboard.com
DATABASE_URL=postgres://ttb:<password>@postgres:5432/ttb
POSTGRES_DB=ttb
POSTGRES_USER=ttb
POSTGRES_PASSWORD=<same-password-used-in-DATABASE_URL>
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

SENTRY_DSN=<dev-sentry-dsn>
SENTRY_ENVIRONMENT=dev
SENTRY_RELEASE=<git-sha>
DJANGO_LOG_LEVEL=INFO
```

Use a confidential Cognito client secret only if the app client is created with
one.

Enable Bedrock only after the instance profile has the scoped `bedrock:Converse`
permission and the selected model has been enabled in the dev account. Until
then the moderation gate intentionally fails closed with a temporary validation
response; it never creates Checkout Sessions without a matching approval.

## EC2 File Layout

Recommended layout:

```text
/opt/ttb/
  .env
  Caddyfile
  docker-compose.yml
  staticfiles/
```

Copy the templates from:

```text
deploy/dev/Caddyfile
deploy/dev/docker-compose.yml
deploy/dev/env.example
```

Use `deploy/dev/env.example` as the starting point for `/opt/ttb/.env`.
Do not commit real secret values.

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
named volumes untouched. It starts the worker when Stripe or demo bidding is
enabled, and stops it when both are disabled.

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

```bash
cd /opt/ttb

aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin <dev-account-id>.dkr.ecr.us-east-1.amazonaws.com

docker pull "$TAKEBOARD_IMAGE"
docker run --rm "$TAKEBOARD_IMAGE" tar -C /app/staticfiles -cf - . \
  | tar -C /opt/ttb/staticfiles -xf -

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
- Basic errors reach Sentry with `SENTRY_ENVIRONMENT=dev`.
- Logs are visible through `docker compose logs` and, once configured, CloudWatch.

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
