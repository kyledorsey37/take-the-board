import logging

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.accounts.services.session import get_authenticated_profile
from apps.moderation.services.rate_limits import RateLimitExceeded, RateLimitUnavailable, ValidationBusy
from apps.moderation.services.reporting import ReportUnavailable, remote_addr, submit_message_report

from .models import Board


logger = logging.getLogger(__name__)
REPORT_SUCCESS = "Thanks. We’ll review this message."
REPORT_CLOSED = "This message is no longer accepting reports."
REPORT_RETRY = "Please try again later."


def board_index(request: HttpRequest) -> HttpResponse:
    boards = Board.objects.select_related("school", "current_controller").order_by(
        "-current_amount_cents", "school__name"
    )
    return render(request, "boards/index.html", {"boards": boards})


def _report_response(request: HttpRequest, *, message: str, accepted: bool, status: int = 200) -> HttpResponse:
    if request.headers.get("HX-Request"):
        return render(
            request,
            "components/message_report_result.html",
            {"message_report_result": message, "message_report_accepted": accepted},
            status=status,
        )
    messages.info(request, message)
    referer = request.META.get("HTTP_REFERER", "")
    if url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
        return redirect(referer)
    return redirect(reverse("boards:index"))


@require_POST
def report_takeover(request: HttpRequest, takeover_public_id) -> HttpResponse:
    """Accept an authenticated report without exposing report/case state."""
    profile = get_authenticated_profile(request)
    if not profile or profile.is_banned:
        return HttpResponseForbidden(REPORT_CLOSED)

    try:
        result = submit_message_report(
            takeover_public_id=takeover_public_id,
            reporter=profile,
            category=request.POST.get("category", ""),
            remote_addr=remote_addr(request),
        )
    except (RateLimitExceeded, ValidationBusy, RateLimitUnavailable):
        logger.info(
            "message_report_rate_limited",
            extra={"profile_id": profile.pk, "takeover_id": str(takeover_public_id)},
        )
        return _report_response(request, message=REPORT_RETRY, accepted=False, status=429)
    except ReportUnavailable:
        return _report_response(request, message=REPORT_CLOSED, accepted=False)

    if not result.accepted:
        return _report_response(request, message=REPORT_CLOSED, accepted=False)
    return _report_response(request, message=REPORT_SUCCESS, accepted=True)
