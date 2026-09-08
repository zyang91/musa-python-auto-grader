"""Review policy and class-level aggregation (design.md §8, §25)."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from .models import (
    STATUS_EXECUTION_ERROR,
    STATUS_FAIL,
    STATUS_MANUAL_REVIEW,
    STATUS_NOT_FOUND,
    STATUS_PARTIAL,
    SubmissionResult,
)

DEFAULT_CONFIDENCE_THRESHOLD = 0.80


def apply_review_policy(
    result: SubmissionResult,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    review_below_full_marks: bool = True,
) -> SubmissionResult:
    """Decide what a human still has to look at.

    Flags are additive and explicit: a TA should be able to read why a submission
    reached the queue without opening the raw results.

    With ``review_below_full_marks`` on (the default), every deduction goes to the
    queue: an automated deduction is a claim about a student's work, and a person
    signs off on it before it becomes a grade. Full marks need no defence, so a
    clean submission passes straight through.
    """
    reasons: list[str] = []

    if result.status == "skipped":
        # One clear reason beats a wall of "could not locate" lines.
        result.review_reasons = [
            result.error or "Submission could not be graded"
        ] + [f"Submission: {w}" for w in result.discovery_warnings]
        return result

    for warning in result.discovery_warnings:
        reasons.append(f"Submission: {warning}")

    if result.execution.attempted and not result.execution.success:
        if result.execution.timeout:
            reasons.append("Notebook execution timed out")
        else:
            reasons.append(
                f"Notebook execution failed at cell {result.execution.error_cell}: "
                f"{result.execution.error_message}"
            )
    elif not result.execution.attempted:
        reasons.append("Notebook was never executed")

    for item in result.items:
        if item.manual_override:
            continue
        if item.type == "qualitative" and item.status == STATUS_MANUAL_REVIEW:
            # Expected, not a problem: a written answer always wants human eyes.
            reasons.append(f"{item.name}: qualitative item awaiting a human read")
        elif item.confidence < confidence_threshold and item.status != STATUS_NOT_FOUND:
            reasons.append(
                f"Low confidence on {item.name} ({item.confidence:.0%})"
            )
        elif item.status == STATUS_NOT_FOUND and item.points_possible > 0:
            reasons.append(f"Could not locate the work for {item.name}")

    if review_below_full_marks and result.items:
        lost = [
            f"{item.name} ({item.final_score:g}/{item.points_possible:g})"
            for item in result.items
            if item.final_score < item.points_possible
        ]
        if lost:
            reasons.append(
                f"Not full marks — {result.total_score:g}/{result.max_score:g}: "
                + ", ".join(lost)
            )

    # De-duplicate while preserving order.
    seen: set[str] = set()
    result.review_reasons = [r for r in reasons if not (r in seen or seen.add(r))]
    return result


def grade_letter(percentage: float | None) -> str:
    if percentage is None:
        return "—"
    for cutoff, letter in ((93, "A"), (90, "A-"), (87, "B+"), (83, "B"), (80, "B-"),
                           (77, "C+"), (73, "C"), (70, "C-"), (60, "D")):
        if percentage >= cutoff:
            return letter
    return "F"


def class_summary(results: Iterable[SubmissionResult]) -> dict[str, Any]:
    """Summary cards, distribution and common issues (design.md §8)."""
    results = list(results)
    graded = [r for r in results if r.status == "graded"]
    scores = [r.total_score for r in graded if r.max_score]
    percentages = [r.percentage for r in graded if r.percentage is not None]

    execution_errors = sum(
        1 for r in results if r.execution.attempted and not r.execution.success
    )
    needs_review = sum(1 for r in results if r.needs_review)

    summary: dict[str, Any] = {
        "submissions": len(results),
        "graded": len(graded),
        "mean_score": round(sum(scores) / len(scores), 1) if scores else None,
        "median_score": _median(scores),
        "min_score": min(scores) if scores else None,
        "max_score": max(scores) if scores else None,
        "needs_review": needs_review,
        "execution_errors": execution_errors,
        "manual_overrides": sum(1 for r in results if r.has_manual_override),
        "reviewed": sum(1 for r in results if r.reviewed),
        "distribution": grade_distribution(percentages),
        "common_issues": common_issues(results),
        "rubric_breakdown": rubric_breakdown(graded),
    }
    return summary


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle], 1)
    return round((ordered[middle - 1] + ordered[middle]) / 2, 1)


def grade_distribution(percentages: list[float], bin_size: int = 10) -> list[dict[str, Any]]:
    bins = list(range(0, 100, bin_size))
    counts = {low: 0 for low in bins}
    for value in percentages:
        low = min(int(value // bin_size) * bin_size, 100 - bin_size)
        counts[max(low, 0)] += 1
    # `bucket` stays short so rotated axis labels are not clipped in the charts;
    # `label` carries the full range for tables and exports.
    return [
        {
            "bucket": str(low),
            "label": f"{low}-{low + bin_size - 1}",
            "low": low,
            "count": counts[low],
        }
        for low in bins
    ]


def common_issues(results: Iterable[SubmissionResult], limit: int = 10) -> list[dict[str, Any]]:
    """Rank the deductions that affected the most students (design.md §8)."""
    counter: Counter[str] = Counter()
    for result in results:
        if result.execution.attempted and not result.execution.success:
            counter["Notebook execution failures"] += 1
        for item in result.items:
            if item.status in (STATUS_FAIL, STATUS_NOT_FOUND):
                counter[f"{item.name} — not correct"] += 1
            elif item.status == STATUS_PARTIAL:
                counter[f"{item.name} — partially correct"] += 1
            elif item.status == STATUS_EXECUTION_ERROR:
                counter[f"{item.name} — blocked by execution error"] += 1
        for path_issue in result.artifacts.get("absolute_paths", []) or []:
            counter["Absolute file paths"] += 1
            break
    return [{"issue": issue, "count": count} for issue, count in counter.most_common(limit)]


def rubric_breakdown(results: Iterable[SubmissionResult]) -> list[dict[str, Any]]:
    """Mean score per rubric item — shows where the class as a whole struggled."""
    totals: dict[str, dict[str, Any]] = {}
    for result in results:
        for item in result.items:
            entry = totals.setdefault(
                item.rubric_id,
                {"rubric_id": item.rubric_id, "name": item.name,
                 "points_possible": item.points_possible, "scores": []},
            )
            entry["scores"].append(item.final_score)
    breakdown = []
    for entry in totals.values():
        scores = entry.pop("scores")
        entry["mean_score"] = round(sum(scores) / len(scores), 2) if scores else 0.0
        entry["mean_percent"] = (
            round(100 * entry["mean_score"] / entry["points_possible"], 1)
            if entry["points_possible"] else None
        )
        breakdown.append(entry)
    return breakdown


def review_queue(results: Iterable[SubmissionResult]) -> list[dict[str, Any]]:
    """Unresolved review items, worst first (design.md §14)."""
    queue = []
    for result in results:
        if not result.needs_review:
            continue
        reasons = result.open_review_reasons()
        queue.append(
            {
                "student_id": result.student_id,
                "display_name": result.display_name or result.student_id,
                "reason": reasons[0] if reasons else "Flagged for review",
                "all_reasons": reasons,
                "score": result.total_score if result.items else None,
                "max_score": result.max_score,
                "percentage": result.percentage,
                "confidence": result.confidence,
                "execution_ok": result.execution.success,
            }
        )
    # Broken submissions first, then least confident, then biggest deduction.
    queue.sort(
        key=lambda entry: (
            entry["execution_ok"],
            entry["confidence"] if entry["confidence"] is not None else 0,
            entry["percentage"] if entry["percentage"] is not None else 0,
        )
    )
    return queue
