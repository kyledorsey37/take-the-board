# Take the Board

Take the Board is a Django monolith for a college-football fan rivalry game where users pay to temporarily control one public message on a school's board.

## Local Development

Start Postgres and Django:

```bash
docker compose up --build
```

Run Django checks with the local settings module:

```bash
python manage.py check
```

The local `runserver` command includes Django's `--insecure` option so production-style (`DEBUG=False`) previews can still serve local static assets. This option is only for the development Compose service; production static assets are intended for S3 and CloudFront.

If the database schema is behind the code after pulling changes, apply pending migrations inside the web container:

```bash
docker compose exec web python manage.py migrate --noinput
```

The local settings use `DATABASE_URL` when provided. Docker Compose supplies a PostgreSQL URL for the app container; a SQLite fallback exists only so framework checks can run before local services are available.

## Architecture Guardrails

- Django monolith.
- Django templates, HTMX, and minimal JavaScript.
- PostgreSQL for core game state.
- Cognito email-code authentication and the Stripe sandbox path are wired for local end-to-end testing. Stripe Embedded Checkout creates one-time manual-capture authorizations, verified webhooks are stored idempotently, and the local worker processes authorization, cancellation, and capture transitions. Bedrock/Nova moderation, SQS FIFO finalization, and EventBridge reset jobs remain future production work.
- Django Admin is the MVP operational interface.
