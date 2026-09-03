"""Production Sentry admission control for high-signal operational incidents.

Sentry is intentionally not a copy of the application log.  The structured
stdout log remains the complete diagnostic record; this module admits only a
small, redacted sample of production incidents to Sentry.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from django.conf import settings
from django.core.cache import cache


logger = logging.getLogger(__name__)

CRITICAL_INCIDENTS = frozenset(
    {
        "bid_finalization_retry_exhausted",
        "payment_capture_integrity_mismatch",
        "payment_capture_recording_failure",
        "payment_refund_integrity_mismatch",
        "scheduled_board_reset_failure",
        "worker_provider_outage",
    }
)

_SOURCE_TAG = "takeboard_sentry_source"
_INCIDENT_TAG = "takeboard_sentry_incident"
_CRITICAL_SOURCE = "critical"
_UNHANDLED_SOURCE = "unhandled_5xx"
_DEDUPLICATION_SECONDS = 6 * 60 * 60
_CRITICAL_HOURLY_LIMIT = 3
_UNHANDLED_HOURLY_LIMIT = 1


def _cache_key(*parts: str) -> str:
    digest = hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()
    return f"takeboard:sentry:{digest}"


def _exception_type(event: dict[str, Any]) -> str:
    values = (event.get("exception") or {}).get("values") or []
    if not values:
        return "unknown"
    return str(values[-1].get("type") or "unknown")


def _reserve_slot(*, source: str, signature: str) -> bool:
    """Reserve one event without leaking an arbitrary error value into Redis.

    Each cache slot is atomically claimed.  This avoids a read/increment race
    when several web or worker containers report the same outage at once.
    """
    try:
        dedupe_key = _cache_key("dedupe", source, signature)
        if not cache.add(dedupe_key, True, timeout=_DEDUPLICATION_SECONDS):
            return False

        limit = _CRITICAL_HOURLY_LIMIT if source == _CRITICAL_SOURCE else _UNHANDLED_HOURLY_LIMIT
        hour = str(int(time.time() // 3600))
        for slot in range(limit):
            budget_key = _cache_key("budget", source, hour, str(slot))
            if cache.add(budget_key, True, timeout=60 * 60 + 60):
                return True

        # The event did not use a quota slot, so permit it to be reconsidered
        # in the next hour rather than suppressing it for six hours.
        cache.delete(dedupe_key)
        return False
    except Exception:
        # A cache outage must never turn into unbounded third-party reporting.
        logger.warning("sentry_event_suppressed_cache_unavailable", extra={"source": source})
        return False


def _failure_threshold_met(*, incident: str, minimum_occurrences: int, window_seconds: int) -> bool:
    if minimum_occurrences <= 1:
        return True
    try:
        key = _cache_key("failure-threshold", incident)
        if cache.add(key, 1, timeout=window_seconds):
            return False
        return cache.incr(key) >= minimum_occurrences
    except Exception:
        logger.warning(
            "sentry_event_suppressed_cache_unavailable",
            extra={"source": _CRITICAL_SOURCE},
        )
        return False


def _scrub_event(event: dict[str, Any], *, source: str, signature: str) -> dict[str, Any]:
    """Remove request, identity, breadcrumb, and exception-value data."""
    event.pop("request", None)
    event.pop("user", None)
    event.pop("contexts", None)
    event.pop("breadcrumbs", None)
    event.pop("extra", None)
    event.pop("transaction", None)
    event.pop("server_name", None)

    for value in (event.get("exception") or {}).get("values") or []:
        value["value"] = "redacted"
        stacktrace = value.get("stacktrace") or {}
        for frame in stacktrace.get("frames") or []:
            frame.pop("vars", None)

    incident = signature if source == _CRITICAL_SOURCE else "unexpected_server_error"
    event["tags"] = {
        _SOURCE_TAG: source,
        _INCIDENT_TAG: incident,
    }
    event["fingerprint"] = ["takeboard", source, signature]
    return event


def before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Allow only deduplicated, budgeted critical events and unexpected 5xxs."""
    del hint
    tags = event.get("tags") or {}
    incident = tags.get(_INCIDENT_TAG)
    source = tags.get(_SOURCE_TAG)

    if source == _CRITICAL_SOURCE:
        if incident not in CRITICAL_INCIDENTS:
            logger.warning("sentry_event_suppressed_unknown_incident")
            return None
        signature = str(incident)
    elif event.get("exception"):
        source = _UNHANDLED_SOURCE
        signature = _exception_type(event)
    else:
        # Logging events and messages are never admitted implicitly.
        return None

    if not _reserve_slot(source=source, signature=signature):
        logger.warning("sentry_event_suppressed", extra={"source": source, "incident": signature})
        return None
    return _scrub_event(event, source=source, signature=signature)


def capture_critical_exception(
    incident: str,
    error: BaseException,
    *,
    minimum_occurrences: int = 1,
    window_seconds: int = 60,
) -> None:
    """Report a vetted exception through the production quota gate."""
    if incident not in CRITICAL_INCIDENTS:
        raise ValueError(f"Unknown Sentry incident: {incident}")
    if not settings.SENTRY_DSN or not _failure_threshold_met(
        incident=incident,
        minimum_occurrences=minimum_occurrences,
        window_seconds=window_seconds,
    ):
        return

    import sentry_sdk

    with sentry_sdk.push_scope() as scope:
        scope.set_tag(_SOURCE_TAG, _CRITICAL_SOURCE)
        scope.set_tag(_INCIDENT_TAG, incident)
        sentry_sdk.capture_exception(error)


def capture_critical_message(incident: str) -> None:
    """Report a vetted invariant violation without attaching object identifiers."""
    if incident not in CRITICAL_INCIDENTS:
        raise ValueError(f"Unknown Sentry incident: {incident}")
    if not settings.SENTRY_DSN:
        return

    import sentry_sdk

    with sentry_sdk.push_scope() as scope:
        scope.set_tag(_SOURCE_TAG, _CRITICAL_SOURCE)
        scope.set_tag(_INCIDENT_TAG, incident)
        sentry_sdk.capture_message(incident, level="error")
