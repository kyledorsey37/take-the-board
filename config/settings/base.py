from pathlib import Path
from typing import List, Optional
from urllib.parse import parse_qs, unquote, urlparse
import os


BASE_DIR = Path(__file__).resolve().parents[2]


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: Optional[List[str]] = None) -> List[str]:
    value = os.environ.get(name)
    if not value:
        return default or []
    return [item.strip() for item in value.split(",") if item.strip()]


def database_from_url(url: str) -> dict[str, object]:
    parsed = urlparse(url)
    scheme = parsed.scheme

    if scheme in {"postgres", "postgresql"}:
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(parsed.path.lstrip("/")),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or 5432),
            "OPTIONS": {
                key: values[-1] for key, values in parse_qs(parsed.query).items()
            },
        }

    if scheme == "sqlite":
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": unquote(parsed.path),
        }

    raise ValueError(f"Unsupported DATABASE_URL scheme: {scheme}")


SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "unsafe-local-dev-key-change-me",
)

DEBUG = env_bool("DJANGO_DEBUG", False)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "unfold",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts",
    "apps.schools",
    "apps.boards",
    "apps.bidding",
    "apps.payments",
    "apps.moderation",
    "apps.rivalries",
    "apps.leaderboard",
    "apps.core",
]

UNFOLD = {
    "SITE_TITLE": "Take the Board operations",
    "SITE_HEADER": "Take the Board",
    "SITE_SYMBOL": "stadium",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
}

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.core.middleware.request_id.RequestIDMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.analytics",
                "apps.accounts.context_processors.auth",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/New_York"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"

TAKEBOARD_DEFAULT_BOARD_MESSAGE = "THIS BOARD IS OPEN."
TAKEBOARD_MINIMUM_BID_INCREMENT_CENTS = int(
    os.environ.get("TAKEBOARD_MINIMUM_BID_INCREMENT_CENTS", "100")
)
TAKEBOARD_MAXIMUM_BID_CENTS = int(os.environ.get("TAKEBOARD_MAXIMUM_BID_CENTS", "50000"))
TAKEBOARD_GUARANTEED_DISPLAY_SECONDS = int(
    os.environ.get("TAKEBOARD_GUARANTEED_DISPLAY_SECONDS", "30")
)
TAKEBOARD_MESSAGE_MAX_LENGTH = int(os.environ.get("TAKEBOARD_MESSAGE_MAX_LENGTH", "80"))
TAKEBOARD_VALIDATION_EXPIRATION_MINUTES = int(
    os.environ.get("TAKEBOARD_VALIDATION_EXPIRATION_MINUTES", "10")
)
# Free-play takeovers are local-development mechanics only. They create no
# payment records and must remain disabled outside local development.
TAKEBOARD_DEMO_BIDDING_ENABLED = env_bool("TAKEBOARD_DEMO_BIDDING_ENABLED", False)
TAKEBOARD_COGNITO_AUTH_ENABLED = env_bool("TAKEBOARD_COGNITO_AUTH_ENABLED", False)
TAKEBOARD_STRIPE_ENABLED = env_bool("TAKEBOARD_STRIPE_ENABLED", False)
TAKEBOARD_AUTH_MODAL_PREVIEW = env_bool("TAKEBOARD_AUTH_MODAL_PREVIEW", False)
TAKEBOARD_REQUIRE_AUTH_FOR_BIDDING = env_bool(
    "TAKEBOARD_REQUIRE_AUTH_FOR_BIDDING",
    TAKEBOARD_COGNITO_AUTH_ENABLED or TAKEBOARD_STRIPE_ENABLED,
)
COGNITO_REGION = os.environ.get("COGNITO_REGION", "")
COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "")
COGNITO_CLIENT_ID = os.environ.get("COGNITO_CLIENT_ID", "")
COGNITO_CLIENT_SECRET = os.environ.get("COGNITO_CLIENT_SECRET", "")
COGNITO_DOMAIN = os.environ.get("COGNITO_DOMAIN", "").rstrip("/")
COGNITO_REDIRECT_URI = os.environ.get("COGNITO_REDIRECT_URI", "")
COGNITO_AUTH_PENDING_TTL_SECONDS = int(
    os.environ.get("COGNITO_AUTH_PENDING_TTL_SECONDS", "600")
)
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
REDIS_URL = os.environ.get("REDIS_URL", "")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "take-the-board-local",
        }
    }

# This remains empty outside production, even if a developer happens to have a
# measurement ID in a local environment file.
GOOGLE_ANALYTICS_MEASUREMENT_ID = ""

SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN:
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            environment=os.environ.get("SENTRY_ENVIRONMENT", "local"),
            release=os.environ.get("SENTRY_RELEASE", ""),
            send_default_pii=False,
        )
    except ImportError:
        pass

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_context": {
            "()": "apps.core.logging.RequestContextFilter",
        },
    },
    "formatters": {
        "structured": {
            "()": "apps.core.logging.JsonFormatter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["request_context"],
            "formatter": "structured",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
    },
}
