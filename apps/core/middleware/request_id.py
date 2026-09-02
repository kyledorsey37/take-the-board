import logging
import time
import uuid
import re

from apps.core.logging import request_id_var, user_id_var


logger = logging.getLogger(__name__)
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


class RequestIDMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        supplied_id = request.headers.get("X-Request-ID", "")
        request_id = supplied_id if REQUEST_ID_PATTERN.fullmatch(supplied_id) else str(uuid.uuid4())
        request.request_id = request_id
        request_id_token = request_id_var.set(request_id)

        user_id = ""
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            user_id = str(user.pk)
        user_id_token = user_id_var.set(user_id)

        started_at = time.monotonic()
        try:
            response = self.get_response(request)
        finally:
            user = getattr(request, "user", None)
            if user is not None and getattr(user, "is_authenticated", False):
                user_id_var.set(str(user.pk))

            duration_ms = int((time.monotonic() - started_at) * 1000)
            logger.info(
                "request_completed",
                extra={
                    "method": request.method,
                    "path": request.path,
                    "status_code": getattr(locals().get("response", None), "status_code", 500),
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.reset(request_id_token)
            user_id_var.reset(user_id_token)

        response["X-Request-ID"] = request_id
        return response
