import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core import management
from django.test import TestCase, override_settings

from apps.moderation.services.evaluation import (
    EvaluationCase,
    EvaluationResult,
    evaluate_cases,
    load_corpus,
    summarize_results,
)
from apps.moderation.services.nova_classifier import Classification


CORPUS_PATH = Path("data/moderation_evaluation/bedrock_regression.json")


class ModerationEvaluationTests(TestCase):
    def test_corpus_is_stratified_and_has_stable_schema(self):
        cases = load_corpus(CORPUS_PATH)
        self.assertEqual(len(cases), 250)
        self.assertEqual(len({case.case_id for case in cases}), 250)
        self.assertEqual(sum(case.category == "must_allow_anchor" for case in cases), 60)
        self.assertEqual(sum(case.category == "rivalry_trash_talk" for case in cases), 60)
        self.assertEqual(sum(case.expected_decision == "block" for case in cases), 80)
        self.assertEqual(sum(case.expected_decision == "review" for case in cases), 50)

    def test_metrics_separate_false_blocks_false_allows_reviews_and_latency(self):
        cases = [
            EvaluationCase("one", "synthetic allow", "message", "allow", "allow", "anchor", "test"),
            EvaluationCase("two", "synthetic block", "message", "reject", "block", "threat", "test"),
            EvaluationCase("three", "synthetic review", "message", "reject", "review", "other", "test"),
        ]
        results = [
            EvaluationResult("one", "allow", "allow", "anchor", "review", "other", 10.0),
            EvaluationResult("two", "reject", "block", "threat", "allow", "safe", 20.0),
            EvaluationResult("three", "reject", "review", "other", "review", "other", 30.0),
        ]
        summary = summarize_results(
            cases, results, policy_version="p", classifier_version="m", elapsed_ms=65
        )
        self.assertEqual(summary["false_block_rate_expected_allow"], 1.0)
        self.assertEqual(summary["false_allow_rate_clear_block"], 1.0)
        self.assertEqual(summary["review_rate"], 0.6667)
        self.assertEqual(summary["confusion_matrix"]["block"]["allow"], 1)
        self.assertEqual(summary["latency_ms"]["p50"], 20.0)

    def test_evaluator_calls_adapter_for_every_case_and_reports_no_candidate(self):
        cases = [
            EvaluationCase("opaque-1", "SECRET SYNTHETIC TEXT", "message", "allow", "allow", "safe", "note"),
            EvaluationCase("opaque-2", "OTHER SYNTHETIC TEXT", "message", "reject", "block", "spam", "note"),
        ]
        results = evaluate_cases(
            cases,
            lambda **kwargs: Classification("allow", "safe", 0.9),
            policy_version="test-policy",
        )
        report = json.dumps([result.__dict__ for result in results])
        self.assertEqual(len(results), 2)
        self.assertNotIn("SECRET SYNTHETIC TEXT", report)
        self.assertEqual(results[0].case_id, "opaque-1")

    @override_settings(
        TAKEBOARD_BEDROCK_ENABLED=False,
        TAKEBOARD_BEDROCK_MODEL_ID="",
        TAKEBOARD_BEDROCK_REGION="us-east-1",
    )
    def test_live_command_fails_loudly_when_bedrock_is_disabled(self):
        with self.assertRaises(management.CommandError):
            management.call_command("evaluate_bedrock_moderation", corpus=CORPUS_PATH)

    @override_settings(
        TAKEBOARD_BEDROCK_ENABLED=True,
        TAKEBOARD_BEDROCK_MODEL_ID="amazon.nova-lite-v1:0",
        TAKEBOARD_BEDROCK_REGION="us-east-1",
    )
    @patch(
        "apps.moderation.management.commands.evaluate_bedrock_moderation.classify_message",
        return_value=Classification("allow", "safe", 0.9),
    )
    def test_live_command_is_explicit_uncached_and_does_not_persist_text_or_rows(self, classify):
        output = StringIO()
        management.call_command("evaluate_bedrock_moderation", corpus=CORPUS_PATH, stdout=output)
        rendered = output.getvalue()
        self.assertEqual(classify.call_count, 250)
        self.assertNotIn("RUDY", rendered)
        self.assertNotIn("Synthetic", rendered)
        self.assertNotIn("notes", rendered.lower())
        self.assertIn("case-0001", rendered)
        self.assertIn("policy_version", rendered)
