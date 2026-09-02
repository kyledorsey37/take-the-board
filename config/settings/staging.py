from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import database_from_url, env_list
import os


DEBUG = False

try:
    import django_otp  # noqa: F401
except ImportError as exc:
    raise ImproperlyConfigured("django-otp is required outside local development.") from exc

if os.environ.get("TAKEBOARD_ENVIRONMENT", "").strip().lower() != "staging":
    raise ImproperlyConfigured("TAKEBOARD_ENVIRONMENT=staging is required for staging settings.")

if not os.environ.get("DJANGO_SECRET_KEY"):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY is required in staging.")

if not os.environ.get("MODERATION_HASH_SECRET"):
    raise ImproperlyConfigured("MODERATION_HASH_SECRET is required in staging.")
for _name in ("DJANGO_SECRET_KEY", "MODERATION_HASH_SECRET"):
    if os.environ[_name].lower() in {"unsafe-local-dev-key-change-me", "changeme", "secret", "password"} or len(os.environ[_name]) < 32 or len(set(os.environ[_name])) < 12:
        raise ImproperlyConfigured(f"{_name} must be a unique secret of at least 32 characters.")

if not os.environ.get("DATABASE_URL"):
    raise ImproperlyConfigured("DATABASE_URL is required in staging.")

DATABASES = {"default": database_from_url(os.environ["DATABASE_URL"])}
if DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
    raise ImproperlyConfigured("Staging requires a PostgreSQL DATABASE_URL.")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS is required in staging.")
if "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Wildcard DJANGO_ALLOWED_HOSTS is not allowed in staging.")
if TAKEBOARD_RATE_LIMITING_ENABLED and not REDIS_URL:
    raise ImproperlyConfigured("REDIS_URL is required when rate limiting is enabled in staging.")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
