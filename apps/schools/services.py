import re

from django.conf import settings

from .models import Competition, DEFAULT_COMPETITION_SLUG


HEX_COLOR_PATTERN = re.compile(r"#[0-9a-fA-F]{6}")


def default_competition() -> Competition:
    """Return the competition served by the current MVP site surfaces."""
    slug = getattr(settings, "TAKEBOARD_DEFAULT_COMPETITION_SLUG", DEFAULT_COMPETITION_SLUG)
    return Competition.objects.get(slug=slug, active=True)


def safe_accent_color(value: str | None) -> str:
    """Return a CSS-safe school accent, falling back to the product accent."""
    return value if value and HEX_COLOR_PATTERN.fullmatch(value) else "#b3262f"
