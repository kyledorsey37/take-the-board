from django.core.management.base import BaseCommand, CommandError

from apps.payments.services.capture_records import (
    backfill_missing_capture_records,
    reconcile_pending_capture_fees,
)


class Command(BaseCommand):
    help = "Backfill missing Stripe capture snapshots and reconcile delayed Stripe fees."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100, help="Maximum captures to process per phase.")

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit <= 0:
            raise CommandError("--limit must be greater than zero.")
        created = backfill_missing_capture_records(limit=limit)
        reconciled = reconcile_pending_capture_fees(limit=limit)
        self.stdout.write(
            self.style.SUCCESS(
                f"Created {created} capture snapshot(s); reconciled {reconciled} Stripe fee snapshot(s)."
            )
        )
