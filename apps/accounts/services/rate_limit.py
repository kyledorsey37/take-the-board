"""Small cache-backed limits for authentication endpoints."""

import hashlib

from django.core.cache import cache


class RateLimitExceeded(Exception):
    pass


def _key(*parts: str) -> str:
    digest = hashlib.sha256(":".join(parts).encode()).hexdigest()
    return f"takeboard:auth-rate:{digest}"


def enforce_auth_rate_limit(*, action: str, remote_addr: str, email: str = "") -> None:
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
