from django.core.management.base import BaseCommand
from django.db import transaction

from apps.boards.models import Board
from apps.core.models import GameConfig
from apps.leaderboard.week_services import get_or_create_current_period
from apps.rivalries.models import Rivalry
from apps.schools.models import Competition, DEFAULT_COMPETITION_SLUG, Entity


SCHOOLS = (
    ("Alabama", "alabama", "Alabama", "SEC", "#9E1B32"),
    ("Auburn", "auburn", "Auburn", "SEC", "#0C2340"),
    ("Georgia", "georgia", "Georgia", "SEC", "#BA0C2F"),
    ("Michigan", "michigan", "Michigan", "Big Ten", "#00274C"),
    ("Notre Dame", "notre-dame", "Notre Dame", "Independent", "#0C2340"),
    ("Ohio State", "ohio-state", "Ohio State", "Big Ten", "#BB0000"),
    ("Oklahoma", "oklahoma", "Oklahoma", "SEC", "#841617"),
    ("Texas", "texas", "Texas", "SEC", "#BF5700"),
    ("USC", "usc", "USC", "Big Ten", "#990000"),
)

RIVALRIES = (
    ("Red River", "red-river", "oklahoma", "texas"),
    ("The Game", "the-game", "michigan", "ohio-state"),
    ("Iron Bowl", "iron-bowl", "alabama", "auburn"),
)


class Command(BaseCommand):
    help = "Create an idempotent local roster of schools, boards, and rivalries."

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        competition, _ = Competition.objects.get_or_create(
            slug=DEFAULT_COMPETITION_SLUG,
            defaults={"name": "College Football", "sport": "Football", "active": True},
        )
        entities_by_slug = {}
        for name, slug, short_name, conference, accent_color in SCHOOLS:
            entity, _ = Entity.objects.get_or_create(
                competition=competition,
                slug=slug,
                defaults={
                    "name": name,
                    "short_name": short_name,
                    "group_name": conference,
                    "accent_color": accent_color,
                    "active": True,
                },
            )
            Board.objects.get_or_create(entity=entity)
            entities_by_slug[slug] = entity

        for name, slug, entity_a_slug, entity_b_slug in RIVALRIES:
            Rivalry.objects.get_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "entity_a": entities_by_slug[entity_a_slug],
                    "entity_b": entities_by_slug[entity_b_slug],
                    "active": True,
                },
            )

        if not GameConfig.objects.exists():
            GameConfig.objects.create()

        get_or_create_current_period(competition=competition)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(entities_by_slug)} College Football entities and boards with the current period."
            )
        )
