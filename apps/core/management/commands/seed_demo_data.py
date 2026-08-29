from django.core.management.base import BaseCommand
from django.db import transaction

from apps.boards.models import Board
from apps.core.models import GameConfig
from apps.leaderboard.week_services import get_or_create_current_season_week
from apps.rivalries.models import Rivalry
from apps.schools.models import School


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
        schools_by_slug = {}
        for name, slug, short_name, conference, accent_color in SCHOOLS:
            school, _ = School.objects.get_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "short_name": short_name,
                    "conference": conference,
                    "accent_color": accent_color,
                    "active": True,
                },
            )
            Board.objects.get_or_create(school=school)
            schools_by_slug[slug] = school

        for name, slug, school_a_slug, school_b_slug in RIVALRIES:
            Rivalry.objects.get_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "school_a": schools_by_slug[school_a_slug],
                    "school_b": schools_by_slug[school_b_slug],
                    "active": True,
                },
            )

        if not GameConfig.objects.exists():
            GameConfig.objects.create()

        get_or_create_current_season_week()

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(schools_by_slug)} schools and boards with the current season week."
            )
        )
