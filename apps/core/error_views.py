from django.http import HttpRequest, HttpResponse
from django.template.loader import get_template


def _error_response(
    request: HttpRequest,
    *,
    template_name: str,
    status: int,
    code: str,
    label: str,
    title: str,
    message: str,
) -> HttpResponse:
    response = HttpResponse(
        get_template(template_name).render(
            {
                "error_code": code,
                "error_label": label,
                "error_title": title,
                "error_message": message,
                "request_id": getattr(request, "request_id", ""),
            }
        ),
        status=status,
    )
    response["Cache-Control"] = "no-store"
    return response


def bad_request(request: HttpRequest, exception: Exception) -> HttpResponse:
    return _error_response(
        request,
        template_name="400.html",
        status=400,
        code="400",
        label="Bad request",
        title="That request did not go through.",
        message="Something about the request was not valid. Try again from the page you came from.",
    )


def permission_denied(request: HttpRequest, exception: Exception) -> HttpResponse:
    return _error_response(
        request,
        template_name="403.html",
        status=403,
        code="403",
        label="Access denied",
        title="You cannot access that page.",
        message="You may need to sign in, or this page may no longer be available to you.",
    )


def page_not_found(request: HttpRequest, exception: Exception) -> HttpResponse:
    return _error_response(
        request,
        template_name="404.html",
        status=404,
        code="404",
        label="Page not found",
        title="That page is not here.",
        message="The link may be outdated, or the page may have moved.",
    )


def server_error(request: HttpRequest) -> HttpResponse:
    return _error_response(
        request,
        template_name="500.html",
        status=500,
        code="500",
        label="Something went wrong",
        title="The board needs a quick reset.",
        message="We hit an unexpected problem. Please try again in a moment.",
    )
