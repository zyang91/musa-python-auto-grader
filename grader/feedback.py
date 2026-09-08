"""Student-facing markdown feedback (design.md §30)."""

from __future__ import annotations

from .models import (
    STATUS_MANUAL_REVIEW,
    STATUS_PASS,
    SubmissionResult,
    status_icon,
)


def build_feedback(
    result: SubmissionResult,
    assignment_name: str = "Assignment 1",
    include_evidence: bool = True,
) -> str:
    """Render one student's feedback as markdown."""
    lines: list[str] = [f"# {assignment_name} Feedback", ""]
    lines.append(f"Score: {result.total_score:g} / {result.max_score:g}")
    lines.append("")

    if result.execution.attempted and not result.execution.success:
        lines += [
            "> **Note:** your notebook did not run from top to bottom in a clean "
            "environment. Items below were graded from whatever did run.",
            "",
        ]

    for item in result.items:
        lines.append(f"## {item.name}")
        lines.append(f"{item.final_score:g} / {item.points_possible:g}")
        lines.append("")
        if item.feedback:
            lines.append(item.feedback)
            lines.append("")
        if item.manual_override and item.override_reason:
            lines.append(f"*Instructor note: {item.override_reason}*")
            lines.append("")
        if include_evidence:
            detail = _evidence_lines(item)
            if detail:
                lines.extend(detail)
                lines.append("")

    lines.append("## Review Status")
    lines.append("")
    if result.reviewed:
        lines.append("Reviewed.")
    elif result.needs_review:
        lines.append("Pending instructor review.")
    else:
        lines.append("Graded automatically; no issues were flagged for review.")
    lines.append("")
    return "\n".join(lines)


def _evidence_lines(item) -> list[str]:
    """Turn the most useful evidence into something a student can act on."""
    evidence = item.evidence or {}
    lines: list[str] = []

    cases = evidence.get("cases")
    if isinstance(cases, list) and cases:
        lines.append("Hidden tests:")
        lines.append("")
        for case in cases:
            mark = "✓" if case.get("passed") else "✕"
            detail = f"{mark} {case.get('label')}"
            if not case.get("passed"):
                actual = case.get("error") or case.get("actual")
                detail += f" — expected {case.get('expected')}, got {actual}"
            lines.append(f"- {detail}")
        return lines

    missing = evidence.get("missing_zips")
    extra = evidence.get("unexpected_zips")
    if missing or extra:
        if missing:
            lines.append(f"- Missing ZIP codes: {', '.join(missing)}")
        if extra:
            lines.append(f"- Unexpected ZIP codes: {', '.join(extra)}")
        return lines

    if evidence.get("absolute_paths"):
        lines.append(
            "- Use relative paths so the notebook runs on another machine: "
            + ", ".join(evidence["absolute_paths"][:3])
        )
        return lines

    if evidence.get("error_message") and item.status != STATUS_PASS:
        lines.append(f"- Error: `{evidence['error_message']}`")
    return lines


def summary_line(result: SubmissionResult) -> str:
    """One-line status used in tables and logs."""
    icon = status_icon(STATUS_PASS if result.execution.success else result.execution.status)
    review = " · needs review" if result.needs_review else ""
    return (
        f"{icon} {result.student_id}: {result.total_score:g}/{result.max_score:g}{review}"
    )


def build_class_report(summary: dict, assignment_name: str) -> str:
    """Markdown version of the class overview, for pasting into a course email."""
    lines = [f"# {assignment_name} — class summary", ""]
    lines.append(f"- Submissions: {summary.get('submissions', 0)}")
    if summary.get("mean_score") is not None:
        lines.append(f"- Mean score: {summary['mean_score']}")
        lines.append(f"- Median score: {summary['median_score']}")
    lines.append(f"- Needing review: {summary.get('needs_review', 0)}")
    lines.append(f"- Execution errors: {summary.get('execution_errors', 0)}")
    lines.append("")
    issues = summary.get("common_issues") or []
    if issues:
        lines.append("## Most common issues")
        lines.append("")
        for issue in issues:
            lines.append(f"- {issue['count']} — {issue['issue']}")
        lines.append("")
    breakdown = summary.get("rubric_breakdown") or []
    if breakdown:
        lines.append("## Rubric averages")
        lines.append("")
        for entry in breakdown:
            lines.append(
                f"- {entry['name']}: {entry['mean_score']} / {entry['points_possible']}"
                + (f" ({entry['mean_percent']}%)" if entry.get("mean_percent") is not None else "")
            )
    return "\n".join(lines)
