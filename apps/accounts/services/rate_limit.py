"""Small cache-backed limits for authentication endpoints."""

import hashlib

from django.conf import settings
from django.core.cache import cache


class RateLimitExceeded(Exception):
    pass


class RateLimitUnavailable(Exception):
    pass


def _key(*parts: str) -> str:
    digest = hashlib.sha256(":".join(parts).encode()).hexdigest()
    return f"takeboard:auth-rate:{digest}"


def enforce_auth_rate_limit(*, action: str, remote_addr: str, email: str = "") -> None:
    if not settings.TAKEBOARD_RATE_LIMITING_ENABLED:
        return
    limits = {"start": 5, "verify": 10, "resend": 3}
    limit = limits[action]
    identities = [f"ip:{remote_addr}"]
    if email:
        identities.append(f"email:{email}")

    for identity in identities:
        key = _key(action, identity)
        if cache.add(key, 1, timeout=60):
            continue
        count = cache.incr(key)
        if count > limit:
            raise RateLimitExceeded


def enforce_admin_login_rate_limit(remote_addr: str) -> None:
    try:
        key = _key("admin-login", f"ip:{remote_addr}")
        if cache.add(key, 1, timeout=300):
            return
        if cache.incr(key) > 10:
            raise RateLimitExceeded
    except RateLimitExceeded:
        raise
    except Exception as exc:
        if settings.TAKEBOARD_ENVIRONMENT != "local":
            raise RateLimitUnavailable from exc
