"""Server-side Django session helpers for Cognito-authenticated users."""

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone

from apps.accounts.models import UserProfile


AUTH_SESSION_KEY = "takeboard.auth"
PENDING_AUTH_SESSION_KEY = "takeboard.auth.pending"


def set_pending_auth(request: HttpRequest, pending: dict[str, Any]) -> None:
    pending["expires_at"] = (timezone.now() + timedelta(seconds=settings.COGNITO_AUTH_PENDING_TTL_SECONDS)).timestamp()
    request.session[PENDING_AUTH_SESSION_KEY] = pending


def get_pending_auth(request: HttpRequest) -> dict[str, Any] | None:
    pending = request.session.get(PENDING_AUTH_SESSION_KEY)
    if not pending or pending.get("expires_at", 0) <= timezone.now().timestamp():
        request.session.pop(PENDING_AUTH_SESSION_KEY, None)
        return None
    return pending


def clear_pending_auth(request: HttpRequest) -> None:
    request.session.pop(PENDING_AUTH_SESSION_KEY, None)


def set_authenticated_session(
    request: HttpRequest,
    *,
    profile: UserProfile,
    expires_in: int,
) -> None:
    request.session.cycle_key()
    request.session[AUTH_SESSION_KEY] = {
        "profile_id": profile.id,
        "cognito_sub": str(profile.cognito_sub),
        "expires_at": (timezone.now() + timedelta(seconds=int(expires_in))).timestamp(),
    }
    clear_pending_auth(request)


def get_authenticated_profile(request: HttpRequest) -> UserProfile | None:
    auth = request.session.get(AUTH_SESSION_KEY)
    if not auth or auth.get("expires_at", 0) <= timezone.now().timestamp():
        request.session.pop(AUTH_SESSION_KEY, None)
        return None

    # Remove fields written by older releases. Cognito bearer tokens are only
    # needed during the sign-in exchange and must not remain in app sessions.
    legacy_token_fields = ("access_token", "id_token", "refresh_token")
    if any(field in auth for field in legacy_token_fields):
        for field in legacy_token_fields:
            auth.pop(field, None)
        request.session[AUTH_SESSION_KEY] = auth

    try:
        profile = UserProfile.objects.get(
            pk=auth["profile_id"],
            cognito_sub=auth["cognito_sub"],
        )
    except (KeyError, UserProfile.DoesNotExist):
        request.session.pop(AUTH_SESSION_KEY, None)
        return None

    return profile


def clear_authenticated_session(request: HttpRequest) -> None:
    request.session.pop(AUTH_SESSION_KEY, None)
    clear_pending_auth(request)
