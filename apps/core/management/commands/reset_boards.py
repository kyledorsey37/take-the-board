from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.boards.services.reset_boards import WeeklyResetError, reset_boards
from apps.core.sentry import capture_critical_exception
from apps.payments.services.cancel_authorization import cancel_authorization
from apps.schools.services import default_competition


class Command(BaseCommand):
    help = "Reset boards for the next season week."

    def handle(self, *args, **options):
        try:
            result = reset_boards(
                competition=default_competition(),
                cancel_pending_authorization=(
                    cancel_authorization if settings.TAKEBOARD_STRIPE_ENABLED else None
                ),
            )
        except WeeklyResetError as error:
            capture_critical_exception("scheduled_board_reset_failure", error)
            raise CommandError(str(error)) from error

        if result.already_reset:
            self.stdout.write(
                self.style.WARNING(f"Week {result.period.week_number} {result.period.year} was already reset.")
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Reset {result.boards_reset} boards for Week {result.period.week_number} {result.period.year}; "
                f"prepared {result.stats_rows} entity-period records."
            )
        )
