# Take the Board

Take the Board is a Django monolith for a college-football fan rivalry game where users pay to temporarily control one public message on a school's board.

## Local Development

Start Postgres and Django:

```bash
docker compose up --build
```

The local web container runs Django on `0.0.0.0:8000`, and Compose maps port
`8000` on all host interfaces so another device on the same Wi-Fi network can
reach it. To run the current checkout directly on the Mac, use the launcher
script. It creates or reuses `.venv`, installs dependencies if needed, applies
migrations, seeds demo data, and starts Django on the LAN:

```bash
./scripts/start_local.sh
```

The launcher loads the ignored `.env` file before starting Django, so the Mac
and any phone on the LAN use the same local Cognito, Stripe, and bidding
settings and the same host-mapped Postgres database as Docker. If the copied
`.env` still contains Docker's `@postgres:5432` hostname, the launcher
automatically normalizes it to `127.0.0.1:5433`. Set `LOCAL_DATABASE_URL` only
when you intentionally need a different database. Preview mode is only enabled when
`TAKEBOARD_AUTH_MODAL_PREVIEW=true` is set in `.env`.

The local settings also auto-apply pending migrations whenever `manage.py
runserver` starts. The launcher is still preferred because it checks the port,
seeds demo data, and provides the shared database defaults. If you run Django
manually, this explicit migration remains useful for clarity:

```bash
python manage.py migrate --noinput
DJANGO_SETTINGS_MODULE=config.settings.local python manage.py runserver 0.0.0.0:8000 --insecure
```

Find the Mac's current Wi-Fi address with:

```bash
ipconfig getifaddr en0
```

Then open the returned address on your iPhone, for example:
`http://192.168.1.42:8000`. The local settings allow LAN host headers and keep
CSRF protection enabled; the phone is using the same origin it loaded, so no
production security settings are changed. If macOS asks whether Docker or
Python may accept incoming connections, allow it for your private network.

You can override the Compose bind address or host port when needed:

```bash
WEB_BIND_ADDRESS=0.0.0.0 WEB_PORT=8000 docker compose up --build
```

If the launcher reports that port `8000` is already in use, inspect the process
before stopping it:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

For a temporary alternate port, run `DJANGO_BIND_ADDRESS=0.0.0.0:8002
./scripts/start_local.sh` and use that port in the laptop and phone URLs.

Run Django checks with the local settings module:

```bash
python manage.py check
```

The local `runserver` command includes Django's `--insecure` option so production-style (`DEBUG=False`) previews can still serve local static assets. This option is only for the development Compose service; production static assets are intended for S3 and CloudFront.

If the database schema is behind the code after pulling changes, apply pending migrations inside the web container:

```bash
docker compose exec web python manage.py migrate --noinput
```

The local settings use `DATABASE_URL` when provided. The canonical LAN and Docker
development paths both use PostgreSQL; SQLite is retained only as a fallback for
isolated framework checks when no database service is available.

## Architecture Guardrails

- Django monolith.
- Django templates, HTMX, and minimal JavaScript.
- PostgreSQL for core game state.
- Cognito email-code authentication and the Stripe sandbox path are wired for local end-to-end testing. Stripe Embedded Checkout creates one-time manual-capture authorizations, verified webhooks are stored idempotently, and the local worker processes authorization, cancellation, and capture transitions. Bedrock/Nova moderation, SQS FIFO finalization, and EventBridge reset jobs remain future production work.
- Django Admin is the MVP operational interface.
