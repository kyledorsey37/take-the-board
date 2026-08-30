"""Choose and persist a landing-page hero copy variant."""

from secrets import choice

from django.http import HttpRequest


HERO_VARIANTS = {
    "a": {
        "kicker": "One board. Fans fight to control the message.",
        "title_first": "Put your words",
        "title_second_prefix": "on",
        "title_second_emphasis": "their",
        "title_second_suffix": "board.",
        "intro": (
            "Every school has one public message. Take it over, talk your talk, "
            "and dare the next fan to top you."
        ),
    },
    "b": {
        "kicker": "Say something your rival can't ignore.",
        "title_first": "Take the board.",
        "title_second_prefix": "",
        "title_second_emphasis": "Start the fight.",
        "title_second_suffix": "",
        "intro": (
            "One public message. One current controller. One chance to make "
            "the next fan outbid you."
        ),
    },
}
HERO_VARIANT_SESSION_KEY = "home_hero_variant"


def home_hero_variant(request: HttpRequest) -> dict[str, str]:
    """Return a stable per-session hero variant for clean A/B measurement."""
    variant_key = request.session.get(HERO_VARIANT_SESSION_KEY)
    if variant_key not in HERO_VARIANTS:
        variant_key = choice(tuple(HERO_VARIANTS))
        request.session[HERO_VARIANT_SESSION_KEY] = variant_key

    return {"key": variant_key, **HERO_VARIANTS[variant_key]}
