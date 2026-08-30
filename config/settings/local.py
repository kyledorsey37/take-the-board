from .base import *  # noqa: F403
from .base import BASE_DIR, database_from_url, env_bool, env_list
import os


DEBUG = env_bool("DJANGO_DEBUG", True)
TAKEBOARD_DEMO_BIDDING_ENABLED = env_bool("TAKEBOARD_DEMO_BIDDING_ENABLED", True)
# Preview mode is opt-in. The normal local launcher loads `.env`, which should
# contain the same Cognito/Stripe settings used by the local end-to-end path.
TAKEBOARD_AUTH_MODAL_PREVIEW = env_bool("TAKEBOARD_AUTH_MODAL_PREVIEW", False)

# Local development may be opened from another device on the same LAN. Host
# validation is intentionally permissive here; staging and production override
# this with required, explicit DJANGO_ALLOWED_HOSTS values.
ALLOWED_HOSTS = ["*"]

# Same-origin requests from the phone's LAN URL are accepted by Django's CSRF
# middleware. Keep the common local origins explicit for redirects and tooling.
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://0.0.0.0:8000",
] + env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

database_url = os.environ.get("DATABASE_URL")
if database_url:
    DATABASES = {"default": database_from_url(database_url)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
