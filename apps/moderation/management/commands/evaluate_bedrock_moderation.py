"""Explicit developer-only live Bedrock moderation regression evaluation."""

from pathlib import Path
from time import perf_counter

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.moderation.services.evaluation import evaluate_cases, load_corpus, summarize_results
from apps.moderation.services.nova_classifier import classify_message


class Command(BaseCommand):
    help = "Run the synthetic moderation corpus against live configured Bedrock/Nova without persistence."

    def add_arguments(self, parser):
        parser.add_argument(
            "--corpus",
            type=Path,
            default=Path("data/moderation_evaluation/bedrock_regression.json"),
            help="Path to the synthetic labeled corpus (default: %(default)s)",
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=8,
            help="Maximum concurrent adapter calls (default: %(default)s)",
        )

    def handle(self, *args, **options):
        if not settings.TAKEBOARD_BEDROCK_ENABLED:
            raise CommandError("Bedrock moderation evaluation requires TAKEBOARD_BEDROCK_ENABLED=true.")
        if not settings.TAKEBOARD_BEDROCK_MODEL_ID or not settings.TAKEBOARD_BEDROCK_REGION:
            raise CommandError(
                "Bedrock moderation evaluation requires TAKEBOARD_BEDROCK_MODEL_ID and TAKEBOARD_BEDROCK_REGION."
            )
        corpus_path = options["corpus"]
        try:
            cases = load_corpus(corpus_path)
        except (OSError, ValueError) as error:
            raise CommandError(f"Unable to load moderation evaluation corpus: {error}") from error

        started = perf_counter()
        results = evaluate_cases(
            cases,
            classify_message,
            policy_version=settings.TAKEBOARD_MODERATION_POLICY_VERSION,
            max_workers=options["workers"],
        )
        summary = summarize_results(
            cases,
            results,
            policy_version=settings.TAKEBOARD_MODERATION_POLICY_VERSION,
            classifier_version=settings.TAKEBOARD_MODERATION_CLASSIFIER_MODEL_VERSION,
            elapsed_ms=(perf_counter() - started) * 1000,
        )
        # The output contract intentionally contains no candidate, notes, or provider payload.
        self.stdout.write(self.style.SUCCESS("Moderation evaluation summary:"))
        self.stdout.write(self._json(summary))
        self.stdout.write(self.style.SUCCESS("Per-case normalized results:"))
        for result in results:
            self.stdout.write(self._json({
                "case_id": result.case_id,
                "expected_action": result.expected_action,
                "expected_decision": result.expected_decision,
                "category": result.category,
                "actual_decision": result.actual_decision,
                "actual_category": result.actual_category,
                "failure": result.failure,
            }))
        if summary["failures"]:
            raise CommandError("Moderation evaluation had provider failures; no approval path was used.")

    @staticmethod
    def _json(value):
        import json

        return json.dumps(value, sort_keys=True, separators=(",", ":"))
