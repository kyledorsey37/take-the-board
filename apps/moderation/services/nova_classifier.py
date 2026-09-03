"""Amazon Bedrock/Nova moderation adapter.

Only this module talks to AWS. Callers receive a small normalized result and no
raw provider response is persisted or logged.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings


class ClassifierUnavailable(Exception):
    pass


class ClassifierMalformedResponse(Exception):
    pass


@dataclass(frozen=True)
class Classification:
    decision: str
    category: str
    confidence: float


ALLOWED_DECISIONS = frozenset({"allow", "block", "review"})
ALLOWED_CATEGORIES = frozenset(
    {"safe", "hate", "threat", "personal_info", "sexual_harassment", "illegal", "spam", "other"}
)


def _prompt(*, content_type: str, policy_version: str, candidate: str) -> str:
    return (
        "You are the conservative safety classifier for a public college-football rivalry board. "
        f"Classify this {content_type} under policy version {policy_version}. "
        "Allow ordinary sports trash talk, team or fanbase insults, rivalry slogans, and ordinary profanity. "
        "A standalone first name, public athlete or coach reference, team, mascot, school, tradition, "
        "jersey phrase, cheer, or other public sports reference is not personal information and must not "
        "be blocked merely because it names a person or institution. Personal information means contact "
        "details or uniquely identifying private-person information, such as a phone number, email, home "
        "address, account credential, or private-person doxxing; it does not mean a public figure's name "
        "or a public sports reference. If this is a display name, apply the separate impersonation rule "
        "without relabeling a public sports reference as personal information. Block slurs, hate speech, "
        "credible threats, true doxxing or contact data, targeted sexual harassment, illegal content, spam, "
        "URLs, and deceptive impersonation of an official entity. Any expressed intent to kill, shoot, stab, "
        "attack, assault, hurt, burn, or otherwise physically harm a person, group, team, venue, or property "
        "is a threat and must be blocked even when framed as rivalry talk. Block operational instructions or "
        "solicitations for weapons, explosives, drugs, theft, credential abuse, malware, fraud, or breaking "
        "into a venue as illegal content. Block prize claims, guaranteed winnings, commercial solicitations, "
        "repeated advertising, and calls to click or reply as spam. When uncertain, use review. Return only "
        "one JSON object with decision (allow, block, review), category (safe, hate, threat, personal_info, "
        "sexual_harassment, illegal, spam, other), and confidence (0 to 1). Candidate follows:\n"
        + candidate
    )


def _parse(text: str) -> Classification:
    candidate_text = text.strip()
    if not candidate_text.startswith("{"):
        fenced = re.fullmatch(r".*?```(?:json)?\s*(\{.*?\})\s*```.*", candidate_text, flags=re.IGNORECASE | re.DOTALL)
        if not fenced:
            raise ClassifierMalformedResponse
        candidate_text = fenced.group(1)
    try:
        payload = json.loads(candidate_text)
        decision = payload["decision"]
        category = payload["category"]
        confidence = float(payload["confidence"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ClassifierMalformedResponse from error
    if decision not in ALLOWED_DECISIONS or category not in ALLOWED_CATEGORIES or not 0 <= confidence <= 1:
        raise ClassifierMalformedResponse
    return Classification(decision=decision, category=category, confidence=confidence)


def classify_message(*, content_type: str, policy_version: str, candidate: str) -> Classification:
    if not settings.TAKEBOARD_BEDROCK_ENABLED or not settings.TAKEBOARD_BEDROCK_MODEL_ID:
        raise ClassifierUnavailable
    client = boto3.client(
        "bedrock-runtime",
        region_name=settings.TAKEBOARD_BEDROCK_REGION,
        config=Config(connect_timeout=2, read_timeout=settings.TAKEBOARD_BEDROCK_TIMEOUT_SECONDS),
    )
    try:
        response = client.converse(
            modelId=settings.TAKEBOARD_BEDROCK_MODEL_ID,
            messages=[{"role": "user", "content": [{"text": _prompt(
                content_type=content_type, policy_version=policy_version, candidate=candidate
            )}]}],
            inferenceConfig={"maxTokens": 120, "temperature": 0, "topP": 0.1},
        )
        text = response["output"]["message"]["content"][0]["text"]
    except (BotoCoreError, ClientError, KeyError, IndexError, TypeError) as error:
        raise ClassifierUnavailable from error
    return _parse(text)
