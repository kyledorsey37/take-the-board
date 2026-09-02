import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.boards.models import Board
from apps.core.models import GameConfig
from apps.leaderboard.week_services import get_or_create_current_period
from apps.rivalries.models import Rivalry
from apps.schools.models import Competition, DEFAULT_COMPETITION_SLUG, Entity

from .seed_demo_data import RIVALRIES, SCHOOLS


class Command(BaseCommand):
    help = "Create the idempotent production roster of schools, boards, and rivalries."

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        if os.environ.get("TAKEBOARD_ENVIRONMENT", "").strip().lower() != "production":
            raise CommandError("seed_production_roster requires TAKEBOARD_ENVIRONMENT=production.")

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
                f"Seeded {len(entities_by_slug)} production College Football entities and boards."
            )
        )
