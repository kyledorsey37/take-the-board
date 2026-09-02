from django.core.exceptions import ImproperlyConfigured
import re

from .base import *  # noqa: F403
from .base import database_from_url, env_list
import os


DEBUG = False

if not os.environ.get("DJANGO_SECRET_KEY"):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY is required in production.")

if not os.environ.get("MODERATION_HASH_SECRET"):
    raise ImproperlyConfigured("MODERATION_HASH_SECRET is required in production.")

if not os.environ.get("DATABASE_URL"):
    raise ImproperlyConfigured("DATABASE_URL is required in production.")

DATABASES = {"default": database_from_url(os.environ["DATABASE_URL"])}
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS is required in production.")

if TAKEBOARD_COGNITO_AUTH_ENABLED and not all(
    [COGNITO_REGION, COGNITO_USER_POOL_ID, COGNITO_CLIENT_ID]
):
    raise ImproperlyConfigured(
        "COGNITO_REGION, COGNITO_USER_POOL_ID, and COGNITO_CLIENT_ID are required when Cognito auth is enabled."
    )

if TAKEBOARD_COGNITO_AUTH_ENABLED and not REDIS_URL:
    raise ImproperlyConfigured("REDIS_URL is required when Cognito auth is enabled in production.")

if TAKEBOARD_STRIPE_ENABLED and not all(
    [STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY, STRIPE_WEBHOOK_SECRET]
):
    raise ImproperlyConfigured(
        "Stripe secret, publishable, and webhook secrets are required when Stripe is enabled."
    )

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
    if TAKEBOARD_GUARANTEED_DISPLAY_SECONDS > 900:
        raise ImproperlyConfigured(
            "TAKEBOARD_GUARANTEED_DISPLAY_SECONDS cannot exceed SQS FIFO's 15-minute delay limit."
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
