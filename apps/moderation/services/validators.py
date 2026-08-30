"""Deterministic, no-cost validation for public content."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from django.conf import settings


class DeterministicReject(Exception):
    pass


URL_RE = re.compile(r"(?:https?://|www\.|\b[a-z0-9-]+\.(?:com|net|org|edu|io)\b)", re.I)
EMAIL_RE = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
PHONE_RE = re.compile(r"(?:\+?1[ .-]?)?(?:\(?\d{3}\)?[ .-]?)\d{3}[ .-]\d{4}\b")
ADDRESS_RE = re.compile(r"\b\d{1,5}\s+[a-z][a-z .'-]{2,30}\s(?:street|st|avenue|ave|road|rd|lane|ln)\b", re.I)
CONTACT_RE = re.compile(r"\b(?:call|text|dm|message)\s+me\b", re.I)
THREAT_RE = re.compile(r"\b(?:i(?:'ll| will)?\s+(?:kill|shoot|stab|hurt)|(?:kill|shoot|stab)\s+you)\b", re.I)
REPEATED_RE = re.compile(r"(.)\1{7,}")
PUNCTUATION_RE = re.compile(r"[^\w\s]{7,}")

# Kept server-side only. The normal form below catches separator and common leetspeak bypasses.
PROHIBITED_NORMAL_FORMS = frozenset({"nigger", "faggot", "kike", "spic", "chink", "tranny"})
RESERVED_DISPLAY_NAMES = frozenset(
    {
        "taketheboard",
        "takeboard",
        "admin",
        "administrator",
        "support",
        "official",
        "moderator",
        "staff",
        "coach",
        "ncaa",
        "espn",
    }
)
IMPERSONATION_TERMS = frozenset({"official", "admin", "support", "coach", "athlete", "team", "school"})


@dataclass(frozen=True)
class Candidate:
    original: str
    canonical: str


def canonicalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    ascii_value = decomposed.encode("ascii", "ignore").decode("ascii")
    translated = ascii_value.translate(str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "@": "a", "$": "s"}))
    return "".join(char for char in translated if char.isalnum())


def _contains_disallowed_unicode(value: str) -> bool:
    return any(unicodedata.category(char).startswith("C") for char in value)


def _validate_common(value: str, *, maximum_length: int) -> Candidate:
    trimmed = value.strip()
    if not trimmed or len(trimmed) > maximum_length or _contains_disallowed_unicode(trimmed):
        raise DeterministicReject
    if any(pattern.search(trimmed) for pattern in (URL_RE, EMAIL_RE, PHONE_RE, ADDRESS_RE, CONTACT_RE)):
        raise DeterministicReject
    if REPEATED_RE.search(trimmed) or PUNCTUATION_RE.search(trimmed) or THREAT_RE.search(trimmed):
        raise DeterministicReject
    canonical = canonicalize(trimmed)
    if not canonical or any(term in canonical for term in PROHIBITED_NORMAL_FORMS):
        raise DeterministicReject
    return Candidate(original=trimmed, canonical=canonical)


def validate_message_deterministically(value: str) -> Candidate:
    return _validate_common(value, maximum_length=settings.TAKEBOARD_MESSAGE_MAX_LENGTH)


def validate_display_name_deterministically(
    value: str, *, reserved_names: set[str] | None = None
) -> Candidate:
    candidate = _validate_common(value, maximum_length=40)
    if len(candidate.original) < 3 or not re.fullmatch(r"[A-Za-z0-9 _-]+", candidate.original):
        raise DeterministicReject
    if not re.fullmatch(r"[A-Za-z0-9].*[A-Za-z0-9]", candidate.original):
        raise DeterministicReject
    if re.search(r"[ _-]{2,}", candidate.original):
        raise DeterministicReject
    if candidate.canonical in RESERVED_DISPLAY_NAMES | (reserved_names or set()):
        raise DeterministicReject
    words = {word for word in re.split(r"[ _-]", candidate.original.casefold()) if word}
    if words & IMPERSONATION_TERMS:
        raise DeterministicReject
    return candidate
