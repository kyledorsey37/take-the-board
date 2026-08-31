import hmac
from urllib.parse import quote

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import DisplayNameForm, EmailStartForm, EmailVerifyForm
from .models import UserProfile
from .services.cognito import (
    CognitoConfigurationError,
    CognitoError,
    exchange_authorization_code,
    hosted_login_url,
    hydrate_profile,
    new_oauth_state,
    resend_email_code,
    start_email_auth,
    verify_email_code,
)
from .services.rate_limit import RateLimitExceeded, enforce_auth_rate_limit
from .services.session import (
    clear_authenticated_session,
    get_authenticated_profile,
    get_pending_auth,
    set_authenticated_session,
    set_pending_auth,
)
from apps.moderation.models import DisplayNameValidation
from apps.moderation.services.rate_limits import RateLimitExceeded as ModerationRateLimitExceeded, ValidationBusy
from apps.moderation.services.validation import BUSY_REJECTION, RATE_LIMIT_REJECTION, validate_display_name

from .services.history import build_account_history


OAUTH_STATE_SESSION_KEY = "takeboard.auth.oauth_state"
OAUTH_NEXT_SESSION_KEY = "takeboard.auth.oauth_next"
AUTH_RATE_LIMIT_REJECTION = "You’ve reached the sign-in limit. Please wait before trying again."


def _auth_enabled_response() -> JsonResponse | None:
    if settings.TAKEBOARD_COGNITO_AUTH_ENABLED:
        return None
    return JsonResponse({"ok": False, "error": "Sign in is not configured."}, status=503)


def _remote_addr(request: HttpRequest) -> str:
    # EC2/Caddy is not a trusted forwarding-header environment. Production must
    # configure trusted proxies before using a forwarding header here.
    return request.META.get("REMOTE_ADDR", "unknown")


def _safe_next(request: HttpRequest, value: str | None) -> str:
    if value and url_has_allowed_host_and_scheme(value, {request.get_host()}):
        return value
    return reverse("core:home")


@require_POST
def email_start(request: HttpRequest) -> JsonResponse:
    if response := _auth_enabled_response():
        return response
    form = EmailStartForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"ok": False, "error": "Enter a valid email address."}, status=400)

    email = form.cleaned_data["email"]
    try:
        enforce_auth_rate_limit(action="start", remote_addr=_remote_addr(request), email=email)
        pending = start_email_auth(email)
    except RateLimitExceeded:
        return JsonResponse({"ok": False, "error": AUTH_RATE_LIMIT_REJECTION}, status=429)
    except (CognitoConfigurationError, CognitoError):
        return JsonResponse(
            {"ok": False, "error": "We could not send a code. Please try again."},
            status=400,
        )

    set_pending_auth(request, pending)
    return JsonResponse({"ok": True, "message": "Check your email for a code."})


@require_POST
def email_verify(request: HttpRequest) -> JsonResponse:
    if response := _auth_enabled_response():
        return response
    pending = get_pending_auth(request)
    if not pending:
        return JsonResponse({"ok": False, "error": "Start again to get a new code."}, status=400)

    form = EmailVerifyForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"ok": False, "error": "Enter the code."}, status=400)

    try:
        enforce_auth_rate_limit(
            action="verify",
            remote_addr=_remote_addr(request),
            email=pending.get("email", ""),
        )
        next_pending, tokens = verify_email_code(pending, form.cleaned_data["code"])
    except RateLimitExceeded:
        return JsonResponse({"ok": False, "error": AUTH_RATE_LIMIT_REJECTION}, status=429)
    except CognitoError:
        return JsonResponse({"ok": False, "error": "That code could not be verified."}, status=400)

    if next_pending:
        set_pending_auth(request, next_pending)
        return JsonResponse({"ok": True, "message": "Check your email for a sign-in code."})

    try:
        profile = hydrate_profile(tokens)
    except CognitoError:
        return JsonResponse({"ok": False, "error": "We could not finish sign-in. Please try again."}, status=400)

    set_authenticated_session(
        request,
        profile=profile,
        tokens={
            "access_token": tokens.access_token,
            "id_token": tokens.id_token,
            "refresh_token": tokens.refresh_token,
            "expires_in": tokens.expires_in,
        },
    )
    return JsonResponse(
        {
            "ok": True,
            "signed_in": True,
            "needs_display_name": not bool(profile.display_name),
        }
    )


@require_POST
def set_display_name(request: HttpRequest) -> JsonResponse:
    profile = get_authenticated_profile(request)
    if not profile:
        return JsonResponse({"ok": False, "error": "Sign in to choose a board name."}, status=401)
    if profile.display_name:
        return JsonResponse({"ok": False, "error": "Your board name is already set."}, status=409)

    form = DisplayNameForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"ok": False, "error": form.errors["display_name"][0]}, status=400)

    display_name = form.cleaned_data["display_name"]
    if UserProfile.objects.exclude(pk=profile.pk).filter(display_name__iexact=display_name).exists():
        return JsonResponse({"ok": False, "error": "That board name is already in use."}, status=400)

    try:
        validation = validate_display_name(
            user=profile,
            display_name=display_name,
            remote_addr=_remote_addr(request),
        )
    except ModerationRateLimitExceeded:
        return JsonResponse({"ok": False, "error": RATE_LIMIT_REJECTION}, status=429)
    except ValidationBusy:
        return JsonResponse({"ok": False, "error": BUSY_REJECTION}, status=503)
    if validation.decision != DisplayNameValidation.Decision.ALLOW:
        return JsonResponse(
            {"ok": False, "error": "That does not meet the Take the Board community guidelines."},
            status=400,
        )

    try:
        with transaction.atomic():
            validation = DisplayNameValidation.objects.select_for_update().get(pk=validation.pk)
            if validation.consumed_at or validation.expires_at <= timezone.now():
                return JsonResponse({"ok": False, "error": BUSY_REJECTION}, status=409)
            profile.display_name = display_name
            profile.save(update_fields=["display_name", "updated_at"])
            validation.consumed_at = timezone.now()
            validation.save(update_fields=["consumed_at"])
    except IntegrityError:
        return JsonResponse({"ok": False, "error": "That board name is already in use."}, status=400)
    return JsonResponse({"ok": True})


@require_POST
def email_resend(request: HttpRequest) -> JsonResponse:
    if response := _auth_enabled_response():
        return response
    pending = get_pending_auth(request)
    if not pending:
        return JsonResponse({"ok": False, "error": "Start again to get a new code."}, status=400)

    try:
        enforce_auth_rate_limit(
            action="resend",
            remote_addr=_remote_addr(request),
            email=pending.get("email", ""),
        )
        set_pending_auth(request, resend_email_code(pending))
    except RateLimitExceeded:
        return JsonResponse({"ok": False, "error": AUTH_RATE_LIMIT_REJECTION}, status=429)
    except CognitoError:
        return JsonResponse({"ok": False, "error": "We could not resend the code. Please try again."}, status=400)
    return JsonResponse({"ok": True, "message": "We sent another code."})


def hosted_login(request: HttpRequest, screen: str) -> HttpResponse:
    if not settings.TAKEBOARD_COGNITO_AUTH_ENABLED:
        return redirect("core:home")
    state = new_oauth_state()
    request.session[OAUTH_STATE_SESSION_KEY] = state
    request.session[OAUTH_NEXT_SESSION_KEY] = _safe_next(request, request.GET.get("next"))
    try:
        return redirect(hosted_login_url(screen=screen, state=state))
    except CognitoConfigurationError:
        return redirect("core:home")


def oauth_callback(request: HttpRequest) -> HttpResponse:
    expected_state = request.session.pop(OAUTH_STATE_SESSION_KEY, "")
    next_url = request.session.pop(OAUTH_NEXT_SESSION_KEY, reverse("core:home"))
    actual_state = request.GET.get("state", "")
    if not expected_state or not hmac.compare_digest(expected_state, actual_state):
        return HttpResponse("Invalid sign-in state.", status=400)
    if not request.GET.get("code"):
        return HttpResponse("Cognito did not complete sign-in.", status=400)

    try:
        tokens = exchange_authorization_code(request.GET["code"])
        profile = hydrate_profile(tokens)
    except CognitoError:
        return HttpResponse("Cognito could not complete sign-in.", status=400)

    set_authenticated_session(
        request,
        profile=profile,
        tokens={
            "access_token": tokens.access_token,
            "id_token": tokens.id_token,
            "refresh_token": tokens.refresh_token,
            "expires_in": tokens.expires_in,
        },
    )
    return redirect(next_url)


@require_POST
def logout(request: HttpRequest) -> HttpResponse:
    clear_authenticated_session(request)
    return redirect(_safe_next(request, request.POST.get("next")))


def account_detail(request: HttpRequest) -> HttpResponse:
    profile = get_authenticated_profile(request)
    if not profile:
        next_url = quote(request.get_full_path(), safe="")
        return redirect(f"{reverse('accounts:login')}?next={next_url}")
    return render(
        request,
        "accounts/account_detail.html",
        {"profile": profile, **build_account_history(profile)},
    )


def profile_detail(request: HttpRequest, display_name: str) -> HttpResponse:
    return HttpResponse("User profiles are coming soon.", content_type="text/plain")
