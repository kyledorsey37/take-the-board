"""Validation orchestration: local checks, cache, quota, classifier, durable proof."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.moderation.models import DisplayNameValidation, MessageValidation
from apps.schools.models import Entity

from .nova_classifier import (
    Classification,
    ClassifierMalformedResponse,
    ClassifierUnavailable,
    classify_message,
)
from .rate_limits import (
    RateLimitExceeded,
    ValidationBusy,
    candidate_hash,
    classifier_semaphore,
    record_rejection,
    open_circuit,
    safe_key,
    enforce_basic_moderation_limit,
    enforce_uncached_moderation_limits,
)
from .validators import (
    DeterministicReject,
    canonicalize,
    validate_display_name_deterministically,
    validate_message_deterministically,
)


logger = logging.getLogger(__name__)
POLICY_REJECTION = "That does not meet the Take the Board community guidelines."
RATE_LIMIT_REJECTION = "You’ve reached the limit for this action. Please wait before trying again."
BUSY_REJECTION = "Validation is temporarily busy. Please try again shortly."


def _cache_key(content_type: str, digest: str) -> str:
    context = f"{content_type}:{digest}:{settings.TAKEBOARD_MODERATION_POLICY_VERSION}:"
    context += settings.TAKEBOARD_MODERATION_CLASSIFIER_MODEL_VERSION
    return f"takeboard:moderation:decision:{safe_key('decision', context)}"


def _cache_result(key: str) -> Classification | None:
    cached = cache.get(key)
    if not cached:
        return None
    try:
        result = Classification(**json.loads(cached))
    except (TypeError, ValueError, json.JSONDecodeError):
        cache.delete(key)
        return None
    if result.decision not in {"allow", "block", "review"}:
        cache.delete(key)
        return None
    return result


def _store_result(key: str, result: Classification) -> None:
    ttl = (
        settings.TAKEBOARD_MODERATION_CACHE_ALLOW_SECONDS
        if result.decision in {"allow", "block"}
        else settings.TAKEBOARD_MODERATION_CACHE_REVIEW_SECONDS
    )
    cache.set(key, json.dumps(result.__dict__), timeout=ttl)


def _classify(*, content_type: str, original: str, canonical: str, user_id: int, remote_addr: str) -> Classification:
    digest = candidate_hash(content_type, canonical)
    key = _cache_key(content_type, digest)
    cached = _cache_result(key)
    if cached:
        logger.info(
            "moderation_cache_hit",
            extra={"validation_type": content_type, "user_id": user_id, "cached": True},
        )
        return cached
    enforce_uncached_moderation_limits(
        content_type=content_type,
        user_id=user_id,
        remote_addr=remote_addr,
        candidate_digest=digest,
    )
    try:
        with classifier_semaphore():
            result = classify_message(
                content_type=content_type,
                policy_version=settings.TAKEBOARD_MODERATION_POLICY_VERSION,
                candidate=original,
            )
    except (ClassifierUnavailable, ClassifierMalformedResponse):
        open_circuit()
        logger.warning("moderation_provider_failure", extra={"validation_type": content_type, "user_id": user_id})
        raise ValidationBusy
    _store_result(key, result)
    logger.info(
        "moderation_model_result",
        extra={"validation_type": content_type, "user_id": user_id, "decision": result.decision},
    )
    return result


def _retention_until(decision: str):
    return timezone.now() + timedelta(days=30) if decision in {"block", "review"} else None


def validate_message(*, user, board, represented_entity, message: str, remote_addr: str) -> MessageValidation:
    if user.is_banned:
        raise ValidationBusy
    try:
        enforce_basic_moderation_limit(content_type="message", user_id=user.id, remote_addr=remote_addr)
    except RateLimitExceeded:
        logger.info("moderation_rate_limited", extra={"validation_type": "message", "user_id": user.id})
        raise
    try:
        candidate = validate_message_deterministically(message)
    except DeterministicReject:
        logger.info("moderation_deterministic_reject", extra={"validation_type": "message", "user_id": user.id})
        candidate = None
    if candidate is None:
        # Store only a short-retention audit record; no failure detail is exposed to callers.
        record_rejection(user_id=user.id, remote_addr=remote_addr)
        return MessageValidation.objects.create(
            user=user, board=board, represented_entity=represented_entity, message=message[:80],
            message_hash=candidate_hash("message", "invalid"), decision=MessageValidation.Decision.BLOCK,
            category="policy", policy_version=settings.TAKEBOARD_MODERATION_POLICY_VERSION,
            classifier_version=settings.TAKEBOARD_MODERATION_CLASSIFIER_MODEL_VERSION,
            expires_at=timezone.now(), content_retention_until=_retention_until("block"),
        )
    try:
        result = _classify(
            content_type="message", original=candidate.original, canonical=candidate.canonical,
            user_id=user.id, remote_addr=remote_addr,
        )
    except RateLimitExceeded:
        logger.info("moderation_rate_limited", extra={"validation_type": "message", "user_id": user.id})
        raise
    validation = MessageValidation.objects.create(
        user=user, board=board, represented_entity=represented_entity, message=candidate.original,
        message_hash=safe_key("message-value", candidate.original), decision=result.decision,
        category=result.category, confidence=Decimal(str(result.confidence)),
        policy_version=settings.TAKEBOARD_MODERATION_POLICY_VERSION,
        classifier_version=settings.TAKEBOARD_MODERATION_CLASSIFIER_MODEL_VERSION,
        expires_at=timezone.now() + timedelta(minutes=settings.TAKEBOARD_VALIDATION_EXPIRATION_MINUTES),
        content_retention_until=_retention_until(result.decision),
    )
    if result.decision != MessageValidation.Decision.ALLOW:
        record_rejection(user_id=user.id, remote_addr=remote_addr)
    return validation


def validate_display_name(*, user, display_name: str, remote_addr: str) -> DisplayNameValidation:
    if user.is_banned:
        raise ValidationBusy
    try:
        enforce_basic_moderation_limit(content_type="display_name", user_id=user.id, remote_addr=remote_addr)
    except RateLimitExceeded:
        logger.info("moderation_rate_limited", extra={"validation_type": "display_name", "user_id": user.id})
        raise
    try:
        school_names = {
            value
            for entity in Entity.objects.filter(active=True).only("name", "short_name", "slug")
            for value in (entity.name, entity.short_name, entity.slug)
        }
        candidate = validate_display_name_deterministically(
            display_name,
            reserved_names={canonicalize(name) for name in school_names},
        )
    except DeterministicReject:
        logger.info("moderation_deterministic_reject", extra={"validation_type": "display_name", "user_id": user.id})
        candidate = None
    if candidate is None:
        record_rejection(user_id=user.id, remote_addr=remote_addr)
        return DisplayNameValidation.objects.create(
            user=user, display_name=display_name[:40], candidate_hash=candidate_hash("display_name", "invalid"),
            decision=DisplayNameValidation.Decision.BLOCK, category="policy",
            policy_version=settings.TAKEBOARD_MODERATION_POLICY_VERSION,
            classifier_version=settings.TAKEBOARD_MODERATION_CLASSIFIER_MODEL_VERSION,
            expires_at=timezone.now(), content_retention_until=_retention_until("block"),
        )
    try:
        result = _classify(
            content_type="display_name", original=candidate.original, canonical=candidate.canonical,
            user_id=user.id, remote_addr=remote_addr,
        )
    except RateLimitExceeded:
        logger.info("moderation_rate_limited", extra={"validation_type": "display_name", "user_id": user.id})
        raise
    validation = DisplayNameValidation.objects.create(
        user=user, display_name=candidate.original,
        candidate_hash=candidate_hash("display_name", candidate.canonical), decision=result.decision,
        category=result.category, confidence=Decimal(str(result.confidence)),
        policy_version=settings.TAKEBOARD_MODERATION_POLICY_VERSION,
        classifier_version=settings.TAKEBOARD_MODERATION_CLASSIFIER_MODEL_VERSION,
        expires_at=timezone.now() + timedelta(minutes=settings.TAKEBOARD_VALIDATION_EXPIRATION_MINUTES),
        content_retention_until=_retention_until(result.decision),
    )
    if result.decision != DisplayNameValidation.Decision.ALLOW:
        record_rejection(user_id=user.id, remote_addr=remote_addr)
    return validation
