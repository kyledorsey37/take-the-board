"""Privacy-preserving live Bedrock moderation evaluation helpers.

This module deliberately does not use the application validation service. The
developer evaluation must exercise the configured adapter on every case,
without decision-cache reuse or durable moderation records.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Callable, Iterable

from .nova_classifier import Classification


EXPECTED_ACTIONS = frozenset({"allow", "reject", "review"})
DECISIONS = ("allow", "block", "review")


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    candidate: str
    content_type: str
    expected_action: str
    expected_decision: str
    category: str
    notes: str


@dataclass(frozen=True)
class EvaluationResult:
    case_id: str
    expected_action: str
    expected_decision: str
    category: str
    actual_decision: str | None
    actual_category: str | None
    latency_ms: float | None
    failure: str | None = None


def load_corpus(path: Path) -> list[EvaluationCase]:
    """Load and validate the versioned JSON corpus without logging candidates."""
    with path.open(encoding="utf-8") as corpus_file:
        payload = json.load(corpus_file)
    if not isinstance(payload, list) or not payload:
        raise ValueError("moderation evaluation corpus must be a non-empty list")

    cases: list[EvaluationCase] = []
    case_ids: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("moderation evaluation corpus entries must be objects")
        required = {"case_id", "candidate", "content_type", "expected_action", "expected_decision", "category", "notes"}
        if set(item) != required:
            raise ValueError("moderation evaluation corpus entry has an invalid schema")
        case = EvaluationCase(**item)
        if case.case_id in case_ids:
            raise ValueError("moderation evaluation case IDs must be unique")
        if case.expected_action not in EXPECTED_ACTIONS or case.expected_decision not in DECISIONS:
            raise ValueError("moderation evaluation entry has an invalid expected outcome")
        if case.content_type not in {"message", "display_name"}:
            raise ValueError("moderation evaluation entry has an invalid content type")
        case_ids.add(case.case_id)
        cases.append(case)
    return cases


def _failure_name(error: Exception) -> str:
    """Return a stable, non-sensitive failure label."""
    return error.__class__.__name__


def evaluate_cases(
    cases: Iterable[EvaluationCase],
    classify: Callable[..., Classification],
    *,
    content_type_override: str | None = None,
    policy_version: str,
    max_workers: int = 8,
) -> list[EvaluationResult]:
    """Run every case once; callers provide the uncached classifier function.

    Bedrock calls are independent, so bounded concurrency keeps the explicit
    developer suite practical while preserving the corpus order in the report.
    """
    case_list = list(cases)

    def evaluate_one(case: EvaluationCase) -> EvaluationResult:
        started = perf_counter()
        try:
            actual = classify(
                content_type=content_type_override or case.content_type,
                policy_version=policy_version,
                candidate=case.candidate,
            )
        except Exception as error:  # noqa: BLE001 - report one sanitized failure per case.
            return EvaluationResult(
                case_id=case.case_id,
                expected_action=case.expected_action,
                expected_decision=case.expected_decision,
                category=case.category,
                actual_decision=None,
                actual_category=None,
                latency_ms=round((perf_counter() - started) * 1000, 2),
                failure=_failure_name(error),
            )
        return EvaluationResult(
            case_id=case.case_id,
            expected_action=case.expected_action,
            expected_decision=case.expected_decision,
            category=case.category,
            actual_decision=actual.decision,
            actual_category=actual.category,
            latency_ms=round((perf_counter() - started) * 1000, 2),
        )

    if not case_list:
        return []
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(case_list)))) as executor:
        return list(executor.map(evaluate_one, case_list))


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * percentile))
    return round(ordered[index], 2)


def summarize_results(
    cases: Iterable[EvaluationCase],
    results: Iterable[EvaluationResult],
    *,
    policy_version: str,
    classifier_version: str,
    elapsed_ms: float,
) -> dict[str, object]:
    cases_by_id = {case.case_id: case for case in cases}
    result_list = list(results)
    expected_allow = [result for result in result_list if result.expected_action == "allow"]
    clear_blocks = [
        result
        for result in result_list
        if result.expected_action == "reject" and result.expected_decision == "block"
    ]
    confusion = {expected: {actual: 0 for actual in DECISIONS} for expected in DECISIONS}
    category_breakdown: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "allow": 0, "block": 0, "review": 0, "failures": 0}
    )
    for case in cases_by_id.values():
        category_breakdown[case.category]["total"] += 1
    for result in result_list:
        if result.actual_decision in DECISIONS:
            confusion[result.expected_decision][result.actual_decision] += 1
            category_breakdown[result.category][result.actual_decision] += 1
        elif result.failure:
            category_breakdown[result.category]["failures"] += 1

    latencies = [result.latency_ms for result in result_list if result.latency_ms is not None]
    failures = [asdict(result) for result in result_list if result.failure]
    for failure in failures:
        # Defensive assertion: this report must never gain a candidate field.
        failure.pop("latency_ms", None)

    false_blocks = sum(result.actual_decision != "allow" for result in expected_allow)
    false_allows = sum(result.actual_decision == "allow" for result in clear_blocks)
    actual_reviews = sum(result.actual_decision == "review" for result in result_list)
    actual_rejections = sum(result.actual_decision in {"block", "review"} for result in result_list)
    mismatches = sum(
        result.actual_decision is None or result.actual_decision != result.expected_decision
        for result in result_list
    )

    return {
        "total_cases": len(cases_by_id),
        "completed_cases": len(result_list) - len(failures),
        "failures": failures,
        "mismatches": mismatches,
        "confusion_matrix": confusion,
        "false_block_rate_expected_allow": round(false_blocks / len(expected_allow), 4) if expected_allow else None,
        "false_allow_rate_clear_block": round(false_allows / len(clear_blocks), 4) if clear_blocks else None,
        "review_rate": round(actual_reviews / len(result_list), 4) if result_list else None,
        "rejection_rate": round(actual_rejections / len(result_list), 4) if result_list else None,
        "category_breakdown": dict(sorted(category_breakdown.items())),
        "latency_ms": {
            "min": round(min(latencies), 2) if latencies else None,
            "mean": round(statistics.mean(latencies), 2) if latencies else None,
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": round(max(latencies), 2) if latencies else None,
        },
        "elapsed_ms": round(elapsed_ms, 2),
        "policy_version": policy_version,
        "classifier_version": classifier_version,
    }
