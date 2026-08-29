from django.conf import settings
from django.http import HttpRequest


def analytics(request: HttpRequest) -> dict[str, str]:
    """Expose the production GA4 measurement ID to shared templates."""
    return {
        "google_analytics_measurement_id": settings.GOOGLE_ANALYTICS_MEASUREMENT_ID,
    }
