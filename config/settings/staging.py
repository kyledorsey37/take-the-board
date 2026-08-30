from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import database_from_url, env_list
import os


DEBUG = False

if not os.environ.get("DJANGO_SECRET_KEY"):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY is required in staging.")

if not os.environ.get("MODERATION_HASH_SECRET"):
    raise ImproperlyConfigured("MODERATION_HASH_SECRET is required in staging.")

if not os.environ.get("DATABASE_URL"):
    raise ImproperlyConfigured("DATABASE_URL is required in staging.")

DATABASES = {"default": database_from_url(os.environ["DATABASE_URL"])}
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS is required in staging.")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
