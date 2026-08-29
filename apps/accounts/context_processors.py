from django.conf import settings

from .services.session import get_authenticated_profile


def auth(request):
    profile = get_authenticated_profile(request)
    return {
        "auth_profile": profile,
        "cognito_auth_enabled": settings.TAKEBOARD_COGNITO_AUTH_ENABLED,
        "auth_modal_enabled": (
            settings.TAKEBOARD_COGNITO_AUTH_ENABLED
            or settings.TAKEBOARD_AUTH_MODAL_PREVIEW
        ),
        "auth_modal_preview": (
            settings.TAKEBOARD_AUTH_MODAL_PREVIEW
            and not settings.TAKEBOARD_COGNITO_AUTH_ENABLED
        ),
    }
