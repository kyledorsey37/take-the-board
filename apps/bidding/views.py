from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.boards.models import Board
from apps.accounts.services.session import get_authenticated_profile

from .forms import TakeBoardForm
from .services.create_bid import BidTooLowError, TakeoverError, create_bid
from .services.rules import current_board_rules


def _error_response(
    request: HttpRequest,
    form: TakeBoardForm,
    error: str = "",
    error_kind: str = "error",
) -> HttpResponse:
    context = {"form": form, "takeover_error": error, "takeover_error_kind": error_kind}
    if request.headers.get("HX-Request"):
        return render(request, "components/takeover_result.html", context)
    return render(request, "bidding/takeover_error.html", context, status=400)


@require_POST
def take_board(request: HttpRequest) -> HttpResponse:
    if not (settings.TAKEBOARD_DEMO_BIDDING_ENABLED or settings.TAKEBOARD_STRIPE_ENABLED):
        return HttpResponseForbidden("Board mechanics are not enabled in this environment.")

    board = get_object_or_404(
        Board.objects.select_related("school"),
        school__slug=request.POST.get("board_slug", ""),
    )
    rules = current_board_rules()
    authenticated_profile = get_authenticated_profile(request)
    form = TakeBoardForm(
        request.POST,
        rules=rules,
        require_display_name=not bool(
            settings.TAKEBOARD_REQUIRE_AUTH_FOR_BIDDING
            and authenticated_profile
            and authenticated_profile.display_name
        ),
    )
    if not form.is_valid():
        return _error_response(request, form, error_kind="validation")

    if not request.session.session_key:
        request.session.create()

    if settings.TAKEBOARD_REQUIRE_AUTH_FOR_BIDDING and not authenticated_profile:
        return _error_response(request, form, "Sign in to take the board.")

    try:
        if settings.TAKEBOARD_STRIPE_ENABLED:
            from apps.payments.services.create_checkout import create_checkout

            checkout = create_checkout(
                board_id=board.id,
                profile_id=authenticated_profile.id,
                represented_school_id=form.cleaned_data["represented_school"].id,
                amount=form.cleaned_data["amount"],
                message=form.cleaned_data["message"],
                rules=rules,
                return_url=(
                    request.build_absolute_uri(
                        reverse("schools:detail", kwargs={"slug": board.school.slug})
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
            represented_school_id=form.cleaned_data["represented_school"].id,
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
    success_url = f"{reverse('schools:detail', kwargs={'slug': board.school.slug})}?move={move}"
    if request.headers.get("HX-Request"):
        response = HttpResponse(status=204)
        response["HX-Redirect"] = success_url
        return response
    return redirect(success_url)
