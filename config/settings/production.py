from django.core.exceptions import ImproperlyConfigured
import re

from .base import *  # noqa: F403
from .base import database_from_url, env_list
import os


DEBUG = False

try:
    import django_otp  # noqa: F401
except ImportError as exc:
    raise ImproperlyConfigured("django-otp is required outside local development.") from exc

if os.environ.get("TAKEBOARD_ENVIRONMENT", "").strip().lower() != "production":
    raise ImproperlyConfigured("TAKEBOARD_ENVIRONMENT=production is required for production settings.")


def _require_strong_secret(name: str, value: str) -> None:
    weak = {"unsafe-local-dev-key-change-me", "changeme", "secret", "password"}
    if not value or value.lower() in weak or len(value) < 32 or len(set(value)) < 12:
        raise ImproperlyConfigured(f"{name} must be a unique secret of at least 32 characters.")

if not os.environ.get("DJANGO_SECRET_KEY"):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY is required in production.")

if not os.environ.get("MODERATION_HASH_SECRET"):
    raise ImproperlyConfigured("MODERATION_HASH_SECRET is required in production.")

if not os.environ.get("DATABASE_URL"):
    raise ImproperlyConfigured("DATABASE_URL is required in production.")

_require_strong_secret("DJANGO_SECRET_KEY", os.environ.get("DJANGO_SECRET_KEY", ""))
_require_strong_secret("MODERATION_HASH_SECRET", os.environ.get("MODERATION_HASH_SECRET", ""))
DATABASES = {"default": database_from_url(os.environ["DATABASE_URL"])}
if DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
    raise ImproperlyConfigured("Production requires a PostgreSQL DATABASE_URL.")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS is required in production.")
if "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Wildcard DJANGO_ALLOWED_HOSTS is not allowed in production.")
if TAKEBOARD_RATE_LIMITING_ENABLED and not REDIS_URL:
    raise ImproperlyConfigured("REDIS_URL is required when rate limiting is enabled in production.")
if TAKEBOARD_BEDROCK_ENABLED and (not TAKEBOARD_BEDROCK_MODEL_ID or not TAKEBOARD_BEDROCK_REGION):
    raise ImproperlyConfigured("Bedrock model and region are required when moderation is enabled.")

if TAKEBOARD_COGNITO_AUTH_ENABLED and not all(
    [COGNITO_REGION, COGNITO_USER_POOL_ID, COGNITO_CLIENT_ID]
):
    raise ImproperlyConfigured(
        "COGNITO_REGION, COGNITO_USER_POOL_ID, and COGNITO_CLIENT_ID are required when Cognito auth is enabled."
    )
if TAKEBOARD_COGNITO_AUTH_ENABLED and (not COGNITO_DOMAIN or not COGNITO_REDIRECT_URI):
    raise ImproperlyConfigured("COGNITO_DOMAIN and COGNITO_REDIRECT_URI are required when auth is enabled.")

if TAKEBOARD_COGNITO_AUTH_ENABLED and not REDIS_URL:
    raise ImproperlyConfigured("REDIS_URL is required when Cognito auth is enabled in production.")

if TAKEBOARD_STRIPE_ENABLED and not all(
    [STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY, STRIPE_WEBHOOK_SECRET]
):
    raise ImproperlyConfigured(
        "Stripe secret, publishable, and webhook secrets are required when Stripe is enabled."
    )
if TAKEBOARD_STRIPE_ENABLED and (not STRIPE_SECRET_KEY.startswith(("sk_live_", "sk_test_")) or not STRIPE_WEBHOOK_SECRET.startswith("whsec_")):
    raise ImproperlyConfigured("Stripe keys have invalid formats.")
if TAKEBOARD_STRIPE_ENABLED and not STRIPE_PUBLISHABLE_KEY.startswith(("pk_live_", "pk_test_")):
    raise ImproperlyConfigured("Stripe publishable key has an invalid format.")
if TAKEBOARD_EMAIL_PROVIDER not in {"noop", "resend"}:
    raise ImproperlyConfigured("TAKEBOARD_EMAIL_PROVIDER must be noop or resend.")
if TAKEBOARD_EMAIL_ENABLED and TAKEBOARD_EMAIL_PROVIDER == "resend" and not TAKEBOARD_EMAIL_RESEND_API_KEY:
    raise ImproperlyConfigured(
        "TAKEBOARD_EMAIL_RESEND_API_KEY is required when Resend email is enabled."
    )
if TAKEBOARD_EMAIL_ENABLED and not TAKEBOARD_EMAIL_FROM:
    raise ImproperlyConfigured("TAKEBOARD_EMAIL_FROM is required when email is enabled.")
if REDIS_URL and not REDIS_URL.startswith(("redis://", "rediss://")):
    raise ImproperlyConfigured("REDIS_URL must use redis:// or rediss://.")

if TAKEBOARD_STRIPE_ENABLED and TAKEBOARD_BID_FINALIZATION_MODE != "sqs_fifo":
    raise ImproperlyConfigured(
        "TAKEBOARD_BID_FINALIZATION_MODE=sqs_fifo is required for Stripe production bidding."
    )

if TAKEBOARD_BID_FINALIZATION_MODE not in {"polling", "sqs_fifo"}:
    raise ImproperlyConfigured("TAKEBOARD_BID_FINALIZATION_MODE must be polling or sqs_fifo.")

if TAKEBOARD_BID_FINALIZATION_MODE == "sqs_fifo":
    if not TAKEBOARD_SQS_BID_FINALIZATION_QUEUE_URL:
        raise ImproperlyConfigured(
            "TAKEBOARD_SQS_BID_FINALIZATION_QUEUE_URL is required when SQS FIFO finalization is enabled."
        )
    if not TAKEBOARD_SQS_BID_FINALIZATION_QUEUE_URL.endswith(".fifo"):
        raise ImproperlyConfigured("The bid finalization queue must be an SQS FIFO queue (.fifo).")
    if not TAKEBOARD_SQS_BID_FINALIZATION_QUEUE_URL.startswith("https://"):
        raise ImproperlyConfigured("The SQS FIFO queue URL must use HTTPS.")
    if not TAKEBOARD_SQS_BID_FINALIZATION_REGION:
        raise ImproperlyConfigured(
            "TAKEBOARD_SQS_BID_FINALIZATION_REGION is required when SQS FIFO finalization is enabled."
        )
    if not 0 <= TAKEBOARD_SQS_BID_FINALIZATION_WAIT_SECONDS <= 20:
        raise ImproperlyConfigured("SQS bid finalization long-poll wait must be between 0 and 20 seconds.")
    if not 1 <= TAKEBOARD_SQS_BID_FINALIZATION_VISIBILITY_TIMEOUT_SECONDS <= 43200:
        raise ImproperlyConfigured("SQS bid finalization visibility timeout is out of bounds.")
    if not 1 <= TAKEBOARD_SQS_BID_FINALIZATION_RETRY_VISIBILITY_SECONDS <= 900:
        raise ImproperlyConfigured("SQS bid finalization retry visibility is out of bounds.")
    if not 1 <= TAKEBOARD_SQS_BID_FINALIZATION_MAX_RECEIVE_COUNT <= 1000:
        raise ImproperlyConfigured("SQS bid finalization receive count is out of bounds.")
    if TAKEBOARD_GUARANTEED_DISPLAY_SECONDS > 43200:
        raise ImproperlyConfigured(
            "TAKEBOARD_GUARANTEED_DISPLAY_SECONDS cannot exceed SQS visibility's 12-hour limit."
        )

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

GOOGLE_ANALYTICS_MEASUREMENT_ID = os.environ.get("GOOGLE_ANALYTICS_MEASUREMENT_ID", "")
if GOOGLE_ANALYTICS_MEASUREMENT_ID and not re.fullmatch(
    r"G-[A-Z0-9]+", GOOGLE_ANALYTICS_MEASUREMENT_ID
):
    raise ImproperlyConfigured("GOOGLE_ANALYTICS_MEASUREMENT_ID must be a GA4 ID starting with G-.")
