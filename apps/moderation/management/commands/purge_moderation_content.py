from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.moderation.models import DisplayNameValidation, MessageValidation


class Command(BaseCommand):
    help = "Purge expired raw blocked/review moderation content while retaining decision metadata."

    def handle(self, *args, **options):
        now = timezone.now()
        messages = MessageValidation.objects.filter(
            content_retention_until__lte=now,
            decision__in=[MessageValidation.Decision.BLOCK, MessageValidation.Decision.REVIEW],
        ).exclude(message="").update(message="")
        names = DisplayNameValidation.objects.filter(
            content_retention_until__lte=now,
            decision__in=[DisplayNameValidation.Decision.BLOCK, DisplayNameValidation.Decision.REVIEW],
        ).exclude(display_name="").update(display_name="")
        self.stdout.write(self.style.SUCCESS(f"Purged {messages} message and {names} display-name candidates."))
