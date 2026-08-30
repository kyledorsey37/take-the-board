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
from .services.create_bid import BidTooLowError, TakeoverError, create_bid
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
            from apps.payments.services.create_checkout import create_checkout

            try:
                enforce_checkout_limits(user_id=authenticated_profile.id, remote_addr=_remote_addr(request))
            except RateLimitExceeded:
                return _error_response(
                    request, form, RATE_LIMIT_REJECTION, error_kind="rate_limited", status_code=429
                )
            except ValidationBusy:
                return _error_response(request, form, BUSY_REJECTION, error_kind="busy", status_code=503)
            checkout = create_checkout(
                board_id=board.id,
                profile_id=authenticated_profile.id,
                represented_entity_id=form.cleaned_data["represented_entity"].id,
                amount=form.cleaned_data["amount"],
                message=form.cleaned_data["message"],
                validation_id=message_validation.id,
                rules=rules,
                return_url=(
                    request.build_absolute_uri(
                        reverse("schools:detail", kwargs={"slug": board.entity.slug})
                    )
                    + "?checkout_session_id={CHECKOUT_SESSION_ID}"
                ),
            )
            return render(
                request,
                "components/stripe_checkout.html",
                {
                    "checkout_client_secret": checkout.client_secret,
                    "bid_status_url": reverse(
                        "payments:bid_status",
                        kwargs={"public_id": checkout.bid_public_id},
                    ),
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
