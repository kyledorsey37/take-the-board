from django.conf import settings

from .models import Competition, DEFAULT_COMPETITION_SLUG


def default_competition() -> Competition:
    """Return the competition served by the current MVP site surfaces."""
    slug = getattr(settings, "TAKEBOARD_DEFAULT_COMPETITION_SLUG", DEFAULT_COMPETITION_SLUG)
    return Competition.objects.get(slug=slug, active=True)
