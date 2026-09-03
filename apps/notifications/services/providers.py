"""Provider boundary for transactional customer email.

The default provider is deliberately inert. Resend is implemented behind this
boundary but is only called when the environment explicitly enables email and
supplies a Resend key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings


@dataclass(frozen=True)
class EmailMessage:
    subject: str
    text_body: str
    html_body: str
    recipient_email: str


@dataclass(frozen=True)
class DeliveryResult:
    provider_message_id: str | None = None
    suppressed: bool = False


class EmailProviderError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class EmailProvider(Protocol):
    def send(self, message: EmailMessage, *, idempotency_key: str) -> DeliveryResult:
        ...


class NoopEmailProvider:
    """Make an explicitly selected no-op safe for development and tests."""

    def send(self, message: EmailMessage, *, idempotency_key: str) -> DeliveryResult:
        return DeliveryResult(suppressed=True)


class ResendEmailProvider:
    def __init__(self, *, api_key: str, api_url: str, timeout_seconds: int):
        self.api_key = api_key
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds

    def send(self, message: EmailMessage, *, idempotency_key: str) -> DeliveryResult:
        payload = json.dumps(
            {
                "from": settings.TAKEBOARD_EMAIL_FROM,
                "to": [message.recipient_email],
                "subject": message.subject,
                "text": message.text_body,
                "html": message.html_body,
            }
        ).encode("utf-8")
        request = Request(
            self.api_url,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Idempotency-Key": idempotency_key,
                "User-Agent": "take-the-board/1.0",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                response_body = response.read(4096)
                if not 200 <= response.status < 300:
                    raise EmailProviderError("provider_http_error")
        except EmailProviderError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise EmailProviderError("provider_request_failed") from error

        try:
            response_data = json.loads(response_body.decode("utf-8"))
            provider_message_id = str(response_data.get("id") or "")
        except (AttributeError, UnicodeDecodeError, ValueError, TypeError) as error:
            raise EmailProviderError("provider_response_invalid") from error
        if not provider_message_id:
            raise EmailProviderError("provider_response_missing_id")
        return DeliveryResult(provider_message_id=provider_message_id)


def get_email_provider() -> EmailProvider:
    provider = str(settings.TAKEBOARD_EMAIL_PROVIDER).strip().lower()
    if provider == "noop":
        return NoopEmailProvider()
    if provider == "resend":
        api_key = str(settings.TAKEBOARD_EMAIL_RESEND_API_KEY or "").strip()
        if not api_key:
            raise EmailProviderError("provider_not_configured")
        return ResendEmailProvider(
            api_key=api_key,
            api_url=settings.TAKEBOARD_EMAIL_RESEND_API_URL,
            timeout_seconds=settings.TAKEBOARD_EMAIL_PROVIDER_TIMEOUT_SECONDS,
        )
    raise EmailProviderError("provider_invalid")
