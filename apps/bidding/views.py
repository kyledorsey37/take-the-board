from decimal import Decimal

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.boards.models import Board
from apps.accounts.services.session import get_authenticated_profile
from apps.schools.services import default_competition
from apps.moderation.models import MessageValidation
from apps.moderation.services.rate_limits import (
    RateLimitExceeded,
    ValidationBusy,
    enforce_checkout_limits,
)
from apps.moderation.services.validation import BUSY_REJECTION, RATE_LIMIT_REJECTION, validate_message

from .forms import TakeBoardForm
from .services.create_bid import (
    BidTooLowError,
    TakeoverError,
    authenticated_player,
    create_bid,
    dollars_to_cents,
)
from .services.confirmation import create_confirmation
from .services.risk import validate_bid_risk
from .services.rules import current_board_rules


def _error_response(
    request: HttpRequest,
    form: TakeBoardForm,
    error: str = "",
    error_kind: str = "error",
    status_code: int | None = None,
) -> HttpResponse:
    context = {"form": form, "takeover_error": error, "takeover_error_kind": error_kind}
    if request.headers.get("HX-Request"):
        return render(request, "components/takeover_result.html", context, status=status_code or 200)
    return render(request, "bidding/takeover_error.html", context, status=status_code or 400)


def _remote_addr(request: HttpRequest) -> str:
    return request.META.get("REMOTE_ADDR", "unknown")


@require_POST
def take_board(request: HttpRequest) -> HttpResponse:
    if not (settings.TAKEBOARD_DEMO_BIDDING_ENABLED or settings.TAKEBOARD_STRIPE_ENABLED):
        return HttpResponseForbidden("Board mechanics are not enabled in this environment.")

    board = get_object_or_404(
        Board.objects.select_related("entity__competition"),
        entity__competition=default_competition(),
        entity__slug=request.POST.get("board_slug", ""),
    )
    rules = current_board_rules()
    authenticated_profile = get_authenticated_profile(request)
    form = TakeBoardForm(
        request.POST,
        rules=rules,
        competition=board.entity.competition,
        require_display_name=not bool(
            settings.TAKEBOARD_REQUIRE_AUTH_FOR_BIDDING
            and authenticated_profile
            and authenticated_profile.display_name
        ),
    )
    if not form.is_valid():
        return _error_response(request, form, error_kind="form")

    if not request.session.session_key:
        request.session.create()

    if settings.TAKEBOARD_REQUIRE_AUTH_FOR_BIDDING and not authenticated_profile:
        return _error_response(request, form, "Sign in to take the board.")

    # Paid bids are screened before moderation to avoid spending provider capacity
    # on a bid the account could never place.
    amount_cents = dollars_to_cents(form.cleaned_data["amount"])
    if settings.TAKEBOARD_STRIPE_ENABLED:
        risk_decision = validate_bid_risk(authenticated_profile, amount_cents)
        if not risk_decision.allowed:
            return _error_response(request, form, risk_decision.user_message)

    message_validation = None
    if authenticated_profile:
        try:
            message_validation = validate_message(
                user=authenticated_profile,
                board=board,
                represented_entity=form.cleaned_data["represented_entity"],
                message=form.cleaned_data["message"],
                remote_addr=_remote_addr(request),
            )
        except RateLimitExceeded:
            return _error_response(
                request, form, RATE_LIMIT_REJECTION, error_kind="rate_limited", status_code=429
            )
        except ValidationBusy:
            return _error_response(request, form, BUSY_REJECTION, error_kind="busy", status_code=503)
        if message_validation.decision != MessageValidation.Decision.ALLOW:
            return _error_response(
                request,
                form,
                "That does not meet the Take the Board community guidelines.",
                error_kind="moderation",
            )

    try:
        if settings.TAKEBOARD_STRIPE_ENABLED:
            try:
                enforce_checkout_limits(user_id=authenticated_profile.id, remote_addr=_remote_addr(request))
            except RateLimitExceeded:
                return _error_response(
                    request, form, RATE_LIMIT_REJECTION, error_kind="rate_limited", status_code=429
                )
            except ValidationBusy:
                return _error_response(request, form, BUSY_REJECTION, error_kind="busy", status_code=503)
            player = authenticated_player(
                profile_id=authenticated_profile.id,
                favorite_entity=form.cleaned_data["represented_entity"],
            )
            confirmation, risk_decision = create_confirmation(
                board_id=board.id,
                user=player,
                represented_entity_id=form.cleaned_data["represented_entity"].id,
                amount_cents=amount_cents,
                message=form.cleaned_data["message"],
                validation=message_validation,
                rules=rules,
                ip_address=_remote_addr(request),
                user_agent=request.headers.get("User-Agent", ""),
                request_id=getattr(request, "request_id", ""),
            )
            return render(
                request,
                "bidding/bid_confirmation.html",
                {
                    "confirmation": confirmation,
                    "board": board,
                    "risk_decision": risk_decision,
                    "requires_terms": (
                        not authenticated_profile.terms_accepted_at
                        or authenticated_profile.terms_version
                        != settings.TAKEBOARD_BID_TERMS_VERSION
                    ),
                    "terms_version": settings.TAKEBOARD_BID_TERMS_VERSION,
                },
            )

        result = create_bid(
            board_id=board.id,
            session_key=request.session.session_key,
            display_name=(
                authenticated_profile.display_name
                if authenticated_profile
                else form.cleaned_data["display_name"]
            ),
            represented_entity_id=form.cleaned_data["represented_entity"].id,
            amount=form.cleaned_data["amount"],
            message=form.cleaned_data["message"],
            rules=rules,
            authenticated_profile_id=authenticated_profile.id if authenticated_profile else None,
        )
    except BidTooLowError as error:
        return _error_response(request, form, str(error), error_kind="price_changed")
    except TakeoverError as error:
        return _error_response(request, form, str(error))

    move = "live" if result.published else "pending"
    success_url = f"{reverse('schools:detail', kwargs={'slug': board.entity.slug})}?move={move}"
    if request.headers.get("HX-Request"):
        response = HttpResponse(status=204)
        response["HX-Redirect"] = success_url
        return response
    return redirect(success_url)


@require_POST
def confirm_bid(request: HttpRequest, public_id) -> HttpResponse:
    """Perform explicit bid confirmation and only then create Stripe Checkout."""
    if not settings.TAKEBOARD_STRIPE_ENABLED:
        return HttpResponseForbidden("Stripe payments are not enabled in this environment.")
    profile = get_authenticated_profile(request)
    if not profile:
        return HttpResponseForbidden("Sign in to continue to payment.")
    from .models import BidConfirmation
    from apps.payments.services.create_checkout import create_checkout

    confirmation = get_object_or_404(BidConfirmation, public_id=public_id, user=profile)
    amount_text = f"{confirmation.amount_cents / 100:.0f}"
    decision = validate_bid_risk(profile, confirmation.amount_cents)
    if not decision.allowed:
        return _error_response(
            request,
            TakeBoardForm(
                rules=current_board_rules(),
                competition=confirmation.board.entity.competition,
            ),
            decision.user_message,
        )
    requires_terms = (
        not profile.terms_accepted_at
        or profile.terms_version != settings.TAKEBOARD_BID_TERMS_VERSION
    )
    if requires_terms:
        if request.POST.get("terms_accepted") != "on":
            return render(
                request,
                "bidding/bid_confirmation.html",
                {
                    "confirmation": confirmation,
                    "board": confirmation.board,
                    "risk_decision": decision,
                    "requires_terms": True,
                    "terms_error": "Please acknowledge the real-money purchase terms.",
                    "terms_version": settings.TAKEBOARD_BID_TERMS_VERSION,
                },
                status=400,
            )
        from django.utils import timezone
        profile.terms_version = settings.TAKEBOARD_BID_TERMS_VERSION
        profile.terms_accepted_at = timezone.now()
        profile.save(update_fields=["terms_version", "terms_accepted_at", "updated_at"])
    if decision.requires_typed_confirmation and request.POST.get("typed_confirmation", "").strip() != f"CONFIRM {amount_text}":
        return render(
            request,
            "bidding/bid_confirmation.html",
            {
                "confirmation": confirmation,
                "board": confirmation.board,
                "risk_decision": decision,
                "requires_terms": False,
                "typed_confirmation_error": f"Type CONFIRM {amount_text} to continue.",
                "terms_version": settings.TAKEBOARD_BID_TERMS_VERSION,
            },
            status=400,
        )
    try:
        enforce_checkout_limits(user_id=profile.id, remote_addr=_remote_addr(request))
        checkout = create_checkout(
            board_id=confirmation.board_id,
            profile_id=profile.id,
            represented_entity_id=confirmation.represented_entity_id,
            amount=Decimal(confirmation.amount_cents) / 100,
            message=confirmation.message,
            validation_id=confirmation.message_validation_id,
            confirmation_id=confirmation.id,
            rules=current_board_rules(),
            return_url=(
                request.build_absolute_uri(
                    reverse("schools:detail", kwargs={"slug": confirmation.board.entity.slug})
                )
                + "?checkout_session_id={CHECKOUT_SESSION_ID}"
            ),
        )
    except (TakeoverError, BidTooLowError) as error:
        return render(
            request,
            "bidding/bid_confirmation.html",
            {
                "confirmation": confirmation,
                "board": confirmation.board,
                "risk_decision": decision,
                "requires_terms": False,
                "confirmation_error": str(error),
                "terms_version": settings.TAKEBOARD_BID_TERMS_VERSION,
            },
            status=409,
        )
    return render(
        request,
        "components/stripe_checkout.html",
        {
            "checkout_client_secret": checkout.client_secret,
            "bid_status_url": reverse("payments:bid_status", kwargs={"public_id": checkout.bid_public_id}),
        },
    )
