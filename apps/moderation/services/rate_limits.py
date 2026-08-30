"""Shared, privacy-preserving Redis/cache controls for expensive public actions."""

from __future__ import annotations

import hashlib
import hmac
from contextlib import contextmanager
from typing import Iterator

from django.conf import settings
from django.core.cache import cache


class RateLimitExceeded(Exception):
    """The caller exhausted a normal action quota."""


class ValidationBusy(Exception):
    """The circuit breaker, global cap, or concurrency limit is active."""


def safe_key(kind: str, value: str) -> str:
    """Return a server-only digest so cache keys never reveal submitted content or IPs."""
    secret = settings.TAKEBOARD_MODERATION_HASH_SECRET.encode("utf-8")
    message = f"{kind}:{value}".encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def candidate_hash(content_type: str, canonical_candidate: str) -> str:
    return safe_key(f"candidate:{content_type}", canonical_candidate)


def _cache_key(surface: str, identity: str) -> str:
    return f"takeboard:limit:{surface}:{safe_key(surface, identity)}"


def _increment(key: str, timeout: int) -> int:
    """Use Redis INCR when configured; Django's cache backend is atomic for Redis."""
    if cache.add(key, 1, timeout=timeout):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        # A just-expired key can disappear between add and incr.
        cache.set(key, 1, timeout=timeout)
        return 1


def enforce(surface: str, identity: str, limit: int, window_seconds: int) -> None:
    if _increment(_cache_key(surface, identity), window_seconds) > limit:
        raise RateLimitExceeded


def _limit(name: str) -> tuple[int, int]:
    return settings.TAKEBOARD_RATE_LIMITS[name]


def enforce_basic_moderation_limit(*, content_type: str, user_id: int, remote_addr: str) -> None:
    prefix = "message" if content_type == "message" else "display_name"
    if cache.get(_cache_key("moderation-cooldown", f"user:{user_id}")):
        raise RateLimitExceeded
    if cache.get(_cache_key("moderation-cooldown", f"ip:{safe_key('ip', remote_addr)}")):
        raise RateLimitExceeded
    limit, window = _limit(f"{prefix}_request")
    enforce(f"{prefix}-request", f"user:{user_id}", limit, window)
    enforce(f"{prefix}-request", f"ip:{safe_key('ip', remote_addr)}", limit, window)


def enforce_uncached_moderation_limits(
    *, content_type: str, user_id: int, remote_addr: str, candidate_digest: str
) -> None:
    prefix = "message" if content_type == "message" else "display_name"
    checks = (
        (f"{prefix}-user-uncached", f"user:{user_id}", f"{prefix}_user_uncached"),
        (f"{prefix}-ip-uncached", f"ip:{safe_key('ip', remote_addr)}", f"{prefix}_ip_uncached"),
        ("candidate-uncached", candidate_digest, "candidate_uncached"),
        ("moderation-global-uncached", "all", "moderation_global_uncached"),
    )
    for surface, identity, setting_name in checks:
        limit, window = _limit(setting_name)
        try:
            enforce(surface, identity, limit, window)
        except RateLimitExceeded as error:
            if setting_name == "moderation_global_uncached":
                raise ValidationBusy from error
            raise


def record_rejection(*, user_id: int, remote_addr: str) -> None:
    """Back off repeated blocks without retaining a raw rejected candidate."""
    count = _increment(_cache_key("moderation-rejections", f"user:{user_id}"), 3600)
    if count < 3:
        return
    cooldown = min(settings.TAKEBOARD_MODERATION_REJECTION_COOLDOWN_SECONDS * (2 ** (count - 3)), 900)
    cache.set(_cache_key("moderation-cooldown", f"user:{user_id}"), True, timeout=cooldown)
    cache.set(
        _cache_key("moderation-cooldown", f"ip:{safe_key('ip', remote_addr)}"),
        True,
        timeout=cooldown,
    )


def enforce_checkout_limits(*, user_id: int, remote_addr: str) -> None:
    for surface, identity, setting_name in (
        ("checkout-user", f"user:{user_id}", "checkout_user"),
        ("checkout-ip", f"ip:{safe_key('ip', remote_addr)}", "checkout_ip"),
        ("checkout-global", "all", "checkout_global"),
    ):
        limit, window = _limit(setting_name)
        try:
            enforce(surface, identity, limit, window)
        except RateLimitExceeded as error:
            if setting_name == "checkout_global":
                raise ValidationBusy from error
            raise


def enforce_bid_status_limits(*, user_id: int, remote_addr: str) -> None:
    for surface, identity, setting_name in (
        ("bid-status-user", f"user:{user_id}", "bid_status_user"),
        ("bid-status-ip", f"ip:{safe_key('ip', remote_addr)}", "bid_status_ip"),
        ("bid-status-global", "all", "bid_status_global"),
    ):
        limit, window = _limit(setting_name)
        enforce(surface, identity, limit, window)


def circuit_is_open() -> bool:
    return bool(cache.get("takeboard:moderation:circuit-open"))


def open_circuit() -> None:
    cache.set(
        "takeboard:moderation:circuit-open",
        True,
        timeout=settings.TAKEBOARD_MODERATION_CIRCUIT_SECONDS,
    )


@contextmanager
def classifier_semaphore() -> Iterator[None]:
    """A small Redis-backed counter lease; its TTL releases a dead worker's slot."""
    if circuit_is_open():
        raise ValidationBusy
    key = "takeboard:moderation:concurrent"
    count = _increment(key, settings.TAKEBOARD_BEDROCK_TIMEOUT_SECONDS + 2)
    if count > settings.TAKEBOARD_MODERATION_CONCURRENCY:
        try:
            cache.decr(key)
        except ValueError:
            pass
        raise ValidationBusy
    try:
        yield
    finally:
        try:
            cache.decr(key)
        except ValueError:
            pass
