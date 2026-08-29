from .base import *  # noqa: F403
from .base import BASE_DIR, database_from_url, env_bool
import os


DEBUG = env_bool("DJANGO_DEBUG", True)
TAKEBOARD_DEMO_BIDDING_ENABLED = env_bool("TAKEBOARD_DEMO_BIDDING_ENABLED", True)
# Show the sign-in experience locally before the Cognito pool is available.
TAKEBOARD_AUTH_MODAL_PREVIEW = env_bool("TAKEBOARD_AUTH_MODAL_PREVIEW", True)

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]

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
