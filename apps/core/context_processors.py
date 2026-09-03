from django.conf import settings
from django.http import HttpRequest


def analytics(request: HttpRequest) -> dict[str, str]:
    """Expose production analytics configuration and the browser consent choice."""
    consent = request.COOKIES.get("ttb_analytics_consent", "")
    if consent not in {"accepted", "declined"}:
        consent = ""
    return {
        "google_analytics_measurement_id": settings.GOOGLE_ANALYTICS_MEASUREMENT_ID,
        "analytics_consent": consent,
        "analytics_consent_banner_enabled": bool(
            settings.GOOGLE_ANALYTICS_MEASUREMENT_ID
            or settings.TAKEBOARD_ANALYTICS_CONSENT_PREVIEW
        ),
    }


def admin_dashboard(request: HttpRequest) -> dict:
    """Load the operations home only for the authenticated Admin index."""
    if request.path.rstrip("/") != "/admin" or not getattr(request.user, "is_staff", False):
        return {}
    from apps.core.services.admin_dashboard import build_admin_dashboard

    return {"admin_dashboard": build_admin_dashboard(request)}
