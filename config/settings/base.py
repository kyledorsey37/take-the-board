from pathlib import Path
from typing import List, Optional
from urllib.parse import parse_qs, unquote, urlparse
import logging
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
TAKEBOARD_ENVIRONMENT = os.environ.get("TAKEBOARD_ENVIRONMENT", "local").strip().lower()

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
    "apps.notifications",
    "apps.moderation",
    "apps.rivalries",
    "apps.leaderboard",
    "apps.core",
]
try:
    import django_otp  # noqa: F401
except ImportError:
    pass
else:
    INSTALLED_APPS[6:6] = ["django_otp", "django_otp.plugins.otp_totp"]

UNFOLD = {
    "SITE_TITLE": "Take the Board operations",
    "SITE_HEADER": "Take the Board",
    "SITE_SYMBOL": "stadium",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
}

MIDDLEWARE = [
    "apps.core.middleware.health_check.HealthCheckHostMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "apps.core.middleware.request_id.RequestIDMiddleware",
    "apps.core.middleware.security.SecurityHeadersMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.admin_security.AdminSecurityMiddleware",
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
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
PERMISSIONS_POLICY = "accelerometer=(), autoplay=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(self \"https://js.stripe.com\"), usb=()"
CSP_REPORT_ONLY = "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; script-src 'self' 'unsafe-inline' https://js.stripe.com https://unpkg.com https://www.googletagmanager.com; connect-src 'self' https://api.stripe.com https://www.google-analytics.com https://region1.google-analytics.com; frame-src 'self' https://js.stripe.com https://hooks.stripe.com; img-src 'self' data: https://www.google-analytics.com; style-src 'self' 'unsafe-inline'; font-src 'self'; form-action 'self'"

TAKEBOARD_DEFAULT_BOARD_MESSAGE = "THIS BOARD IS OPEN."
TAKEBOARD_DEFAULT_COMPETITION_SLUG = os.environ.get(
    "TAKEBOARD_DEFAULT_COMPETITION_SLUG",
    "college-football",
)
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
TAKEBOARD_BID_TERMS_VERSION = os.environ.get("TAKEBOARD_BID_TERMS_VERSION", "bid-terms-v1")
TAKEBOARD_AGE_ACKNOWLEDGEMENT_VERSION = os.environ.get(
    "TAKEBOARD_AGE_ACKNOWLEDGEMENT_VERSION", "18-plus-v1"
)
TAKEBOARD_SUPPORT_EMAIL = os.environ.get("TAKEBOARD_SUPPORT_EMAIL", "support@taketheboard.com")
TAKEBOARD_POLICY_LAST_UPDATED = os.environ.get("TAKEBOARD_POLICY_LAST_UPDATED", "August 31, 2026")
TAKEBOARD_EMAIL_ENABLED = env_bool("TAKEBOARD_EMAIL_ENABLED", False)
TAKEBOARD_EMAIL_PROVIDER = os.environ.get("TAKEBOARD_EMAIL_PROVIDER", "noop").strip().lower()
TAKEBOARD_EMAIL_FROM = os.environ.get("TAKEBOARD_EMAIL_FROM", "Take the Board <notifications@taketheboard.com>")
TAKEBOARD_EMAIL_PUBLIC_BASE_URL = os.environ.get(
    "TAKEBOARD_EMAIL_PUBLIC_BASE_URL", "http://localhost:8000"
).rstrip("/")
TAKEBOARD_EMAIL_RESEND_API_KEY = os.environ.get("TAKEBOARD_EMAIL_RESEND_API_KEY", "")
TAKEBOARD_EMAIL_RESEND_API_URL = os.environ.get(
    "TAKEBOARD_EMAIL_RESEND_API_URL", "https://api.resend.com/emails"
)
TAKEBOARD_EMAIL_PROVIDER_TIMEOUT_SECONDS = int(
    os.environ.get("TAKEBOARD_EMAIL_PROVIDER_TIMEOUT_SECONDS", "10")
)
TAKEBOARD_EMAIL_PROCESSING_TIMEOUT_SECONDS = int(
    os.environ.get("TAKEBOARD_EMAIL_PROCESSING_TIMEOUT_SECONDS", "900")
)
TAKEBOARD_EMAIL_RETRY_BASE_SECONDS = int(
    os.environ.get("TAKEBOARD_EMAIL_RETRY_BASE_SECONDS", "60")
)
TAKEBOARD_EMAIL_RETRY_MAX_SECONDS = int(
    os.environ.get("TAKEBOARD_EMAIL_RETRY_MAX_SECONDS", "3600")
)
TAKEBOARD_STRIPE_STATEMENT_DESCRIPTOR = os.environ.get(
    "TAKEBOARD_STRIPE_STATEMENT_DESCRIPTOR", "TAKETHEBOARD"
)
TAKEBOARD_MODERATION_POLICY_VERSION = os.environ.get("TAKEBOARD_MODERATION_POLICY_VERSION", "2026-09-3")
TAKEBOARD_MODERATION_CLASSIFIER_MODEL_VERSION = os.environ.get(
    "TAKEBOARD_MODERATION_CLASSIFIER_MODEL_VERSION", "nova-lite-v1"
)
TAKEBOARD_MODERATION_HASH_SECRET = os.environ.get("MODERATION_HASH_SECRET", SECRET_KEY)
TAKEBOARD_BEDROCK_ENABLED = env_bool("TAKEBOARD_BEDROCK_ENABLED", False)
TAKEBOARD_BEDROCK_MODEL_ID = os.environ.get("TAKEBOARD_BEDROCK_MODEL_ID", "")
TAKEBOARD_BEDROCK_REGION = os.environ.get("TAKEBOARD_BEDROCK_REGION", "us-east-1")
TAKEBOARD_BEDROCK_TIMEOUT_SECONDS = int(os.environ.get("TAKEBOARD_BEDROCK_TIMEOUT_SECONDS", "5"))
TAKEBOARD_MODERATION_CACHE_ALLOW_SECONDS = int(
    os.environ.get("TAKEBOARD_MODERATION_CACHE_ALLOW_SECONDS", "86400")
)
TAKEBOARD_MODERATION_CACHE_REVIEW_SECONDS = int(
    os.environ.get("TAKEBOARD_MODERATION_CACHE_REVIEW_SECONDS", "300")
)
TAKEBOARD_MODERATION_CIRCUIT_SECONDS = int(
    os.environ.get("TAKEBOARD_MODERATION_CIRCUIT_SECONDS", "60")
)
TAKEBOARD_MODERATION_CONCURRENCY = int(os.environ.get("TAKEBOARD_MODERATION_CONCURRENCY", "3"))
TAKEBOARD_MODERATION_REJECTION_COOLDOWN_SECONDS = int(
    os.environ.get("TAKEBOARD_MODERATION_REJECTION_COOLDOWN_SECONDS", "60")
)
TAKEBOARD_RATE_LIMITING_ENABLED = env_bool("TAKEBOARD_RATE_LIMITING_ENABLED", True)
TAKEBOARD_AUTO_MIGRATE_ON_RUNSERVER = env_bool("TAKEBOARD_AUTO_MIGRATE_ON_RUNSERVER", False)
DATA_UPLOAD_MAX_MEMORY_SIZE = int(os.environ.get("DJANGO_DATA_UPLOAD_MAX_MEMORY_SIZE", "16384"))
TAKEBOARD_RATE_LIMITS = {
    "message_request": (20, 600),
    "message_user_uncached": (5, 600),
    "message_ip_uncached": (15, 600),
    "display_name_request": (12, 3600),
    "display_name_user_uncached": (3, 3600),
    "display_name_ip_uncached": (10, 3600),
    "candidate_uncached": (10, 600),
    "moderation_global_uncached": (30, 60),
    "checkout_user": (3, 600),
    "checkout_ip": (10, 600),
    "checkout_global": (50, 60),
    "bid_status_user": (30, 60),
    "bid_status_ip": (60, 60),
    "bid_status_global": (500, 60),
    "report_user": (5, 3600),
    "report_ip": (5, 3600),
    "report_new_case_user": (3, 3600),
    "report_new_case_ip": (3, 3600),
    "report_global": (500, 60),
}
# Free-play takeovers are local-development mechanics only. They create no
# payment records and must remain disabled outside local development.
TAKEBOARD_DEMO_BIDDING_ENABLED = env_bool("TAKEBOARD_DEMO_BIDDING_ENABLED", False)
TAKEBOARD_COGNITO_AUTH_ENABLED = env_bool("TAKEBOARD_COGNITO_AUTH_ENABLED", False)
TAKEBOARD_STRIPE_ENABLED = env_bool("TAKEBOARD_STRIPE_ENABLED", False)
TAKEBOARD_BID_FINALIZATION_MODE = os.environ.get(
    "TAKEBOARD_BID_FINALIZATION_MODE", "polling"
).strip().lower()
TAKEBOARD_SQS_BID_FINALIZATION_QUEUE_URL = os.environ.get(
    "TAKEBOARD_SQS_BID_FINALIZATION_QUEUE_URL",
    os.environ.get("SQS_BID_FINALIZATION_QUEUE_URL", ""),
)
# Backwards-compatible name retained for deployment manifests that already use
# the original placeholder variable.
SQS_BID_FINALIZATION_QUEUE_URL = os.environ.get("SQS_BID_FINALIZATION_QUEUE_URL", "")
TAKEBOARD_SQS_BID_FINALIZATION_REGION = os.environ.get(
    "TAKEBOARD_SQS_BID_FINALIZATION_REGION",
    os.environ.get("AWS_REGION", ""),
)
TAKEBOARD_SQS_BID_FINALIZATION_WAIT_SECONDS = int(
    os.environ.get("TAKEBOARD_SQS_BID_FINALIZATION_WAIT_SECONDS", "20")
)
TAKEBOARD_SQS_BID_FINALIZATION_VISIBILITY_TIMEOUT_SECONDS = int(
    os.environ.get("TAKEBOARD_SQS_BID_FINALIZATION_VISIBILITY_TIMEOUT_SECONDS", "120")
)
TAKEBOARD_SQS_BID_FINALIZATION_RETRY_VISIBILITY_SECONDS = int(
    os.environ.get("TAKEBOARD_SQS_BID_FINALIZATION_RETRY_VISIBILITY_SECONDS", "30")
)
TAKEBOARD_SQS_BID_FINALIZATION_MAX_RECEIVE_COUNT = int(
    os.environ.get("TAKEBOARD_SQS_BID_FINALIZATION_MAX_RECEIVE_COUNT", "5")
)
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
TAKEBOARD_ANALYTICS_CONSENT_PREVIEW = env_bool(
    "TAKEBOARD_ANALYTICS_CONSENT_PREVIEW", False
)

# Sentry is reserved for production incidents. Local and staging environments
# keep structured JSON logs on stdout for Docker and CloudWatch collection.
SENTRY_DSN = os.environ.get("SENTRY_DSN", "") if TAKEBOARD_ENVIRONMENT == "production" else ""
SENTRY_RELEASE = os.environ.get("SENTRY_RELEASE", "")
if SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration

        from apps.core.sentry import before_send

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            environment="production",
            release=SENTRY_RELEASE or None,
            send_default_pii=False,
            include_local_variables=False,
            max_breadcrumbs=0,
            enable_logs=False,
            traces_sample_rate=0.0,
            profiles_sample_rate=0.0,
            integrations=[
                # Keep application logs in stdout/CloudWatch.  Error-level log
                # records must never become Sentry events automatically.
                LoggingIntegration(
                    level=logging.INFO,
                    event_level=None,
                    sentry_logs_level=None,
                ),
            ],
            before_send=before_send,
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
