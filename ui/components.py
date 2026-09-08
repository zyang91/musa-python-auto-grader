"""Shared UI pieces: status chips, cards, evidence rendering.

Status is never communicated by colour alone (design.md §15) — every badge
carries an icon and a word.
"""

from __future__ import annotations

import base64
from typing import Any

import pandas as pd
import streamlit as st

from grader.models import (
    STATUS_DISPLAY,
    RubricItemResult,
    SubmissionResult,
    status_color,
    status_icon,
)

COLOR_HEX = {
    "green": "#1a7f37",
    "yellow": "#9a6700",
    "red": "#b42318",
    "gray": "#6b7280",
}

STATUS_WORDS = {
    "pass": "Passed",
    "partial": "Partial",
    "fail": "Failed",
    "warning": "Warning",
    "manual_review": "Needs review",
    "execution_error": "Execution error",
    "not_found": "Not found",
}


def status_badge(status: str) -> str:
    icon = status_icon(status)
    word = STATUS_WORDS.get(status, status.replace("_", " ").title())
    color = COLOR_HEX[status_color(status)]
    return (
        f"<span style='color:{color};font-weight:600'>{icon} {word}</span>"
    )


def metric_cards(cards: list[tuple[str, Any, str | None]]) -> None:
    """Summary cards (design.md §8)."""
    columns = st.columns(len(cards))
    for column, (label, value, help_text) in zip(columns, cards):
        with column:
            st.metric(label, value if value is not None else "—", help=help_text)


def confidence_text(confidence: float | None) -> str:
    if confidence is None:
        return "—"
    return f"{confidence:.0%}"


def submissions_table(results: list[SubmissionResult]) -> pd.DataFrame:
    """The searchable student table from design.md §9."""
    rows = []
    for result in results:
        rows.append(
            {
                "Student": result.student_id,
                "Score": result.total_score if result.items else None,
                "Max": result.max_score,
                "Execution": status_icon(result.execution.status)
                + " "
                + ("ok" if result.execution.success else
                   ("timeout" if result.execution.timeout else
                    ("none" if not result.execution.attempted else "error"))),
                "Confidence": result.confidence,
                "Review": "Review" if result.needs_review else ("Reviewed" if result.reviewed else ""),
                "Override": "yes" if result.has_manual_override else "",
            }
        )
    return pd.DataFrame(rows)


def filter_results(
    results: list[SubmissionResult], choice: str, search: str
) -> list[SubmissionResult]:
    """Filters listed in design.md §9."""
    search = (search or "").strip().lower()
    if search:
        results = [
            r for r in results
            if search in r.student_id.lower() or search in (r.display_name or "").lower()
        ]
    if choice == "Needs Review":
        return [r for r in results if r.needs_review]
    if choice == "Execution Failed":
        return [r for r in results if r.execution.attempted and not r.execution.success]
    if choice == "Score < 70":
        return [r for r in results if r.percentage is not None and r.percentage < 70]
    if choice == "Low Confidence":
        return [r for r in results if (r.confidence or 1.0) < 0.8]
    if choice == "Completed":
        return [r for r in results if r.status == "graded" and not r.needs_review]
    return results


# ---------------------------------------------------------------------------
# Evidence viewer (design.md §12)
# ---------------------------------------------------------------------------

def render_evidence(item: RubricItemResult) -> None:
    evidence = item.evidence or {}
    if not evidence:
        st.caption("No evidence was recorded for this item.")
        return

    rendered_keys: set[str] = set()

    cases = evidence.get("cases")
    if isinstance(cases, list) and cases:
        st.markdown("**Hidden tests**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "": "✓" if case.get("passed") else "✕",
                        "Case": case.get("label"),
                        "Expected": case.get("expected"),
                        "Actual": case.get("error") or case.get("actual"),
                    }
                    for case in cases
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
        rendered_keys.add("cases")

    if evidence.get("function_source"):
        st.markdown("**Student function**")
        st.code(evidence["function_source"], language="python")
        rendered_keys.add("function_source")

    dataframe = evidence.get("dataframe")
    if isinstance(dataframe, dict):
        st.markdown("**Detected dataframe**")
        st.write(
            f"Name: `{dataframe.get('name')}` · Rows: {dataframe.get('rows')} · "
            f"Columns: {dataframe.get('n_columns')}"
        )
        columns = dataframe.get("columns") or []
        if columns:
            st.code("\n".join(str(c) for c in columns))
        head = dataframe.get("head")
        if head:
            st.dataframe(pd.DataFrame(head), hide_index=True, use_container_width=True)
        rendered_keys.add("dataframe")

    expected_zips = evidence.get("expected_zips")
    if expected_zips:
        left, right = st.columns(2)
        with left:
            st.markdown("**Expected ZIP codes**")
            st.code("\n".join(expected_zips))
        with right:
            st.markdown("**Detected ZIP codes**")
            st.code("\n".join(evidence.get("student_zips", [])) or "—")
        if evidence.get("missing_zips"):
            st.warning("Missing: " + ", ".join(evidence["missing_zips"]))
        if evidence.get("unexpected_zips"):
            st.warning("Unexpected: " + ", ".join(evidence["unexpected_zips"]))
        if evidence.get("matched_from"):
            st.caption(f"Matched from {evidence['matched_from']}")
        rendered_keys |= {
            "expected_zips", "student_zips", "missing_zips", "unexpected_zips", "matched_from",
        }

    if evidence.get("traceback"):
        st.markdown("**Traceback**")
        st.code(evidence["traceback"][-4000:])
        rendered_keys.add("traceback")

    if evidence.get("response_text"):
        st.markdown("**Markdown response**")
        st.markdown("> " + evidence["response_text"].replace("\n", "\n> "))
        rendered_keys.add("response_text")

    remaining = {k: v for k, v in evidence.items() if k not in rendered_keys}
    if remaining:
        with st.expander("All evidence"):
            st.json(remaining)


# ---------------------------------------------------------------------------
# Notebook viewer (design.md §13)
# ---------------------------------------------------------------------------

def render_notebook(cells: list[dict[str, Any]], max_cells: int = 200) -> None:
    if not cells:
        st.info("No notebook is available for this submission.")
        return
    for index, cell in enumerate(cells[:max_cells], start=1):
        kind = cell.get("cell_type")
        if kind == "markdown":
            st.markdown(cell.get("source", ""))
        elif kind == "code":
            count = cell.get("execution_count")
            st.caption(f"In [{count if count is not None else ' '}]")
            st.code(cell.get("source", ""), language="python")
            for output in cell.get("outputs", []):
                _render_output(output)
        else:
            st.text(cell.get("source", ""))
        st.divider()
    if len(cells) > max_cells:
        st.caption(f"{len(cells) - max_cells} further cells were not rendered.")


def _render_output(output: dict[str, Any]) -> None:
    kind = output.get("type")
    if kind == "text":
        st.text(output.get("text", ""))
    elif kind == "html":
        st.markdown(output.get("html", ""), unsafe_allow_html=True)
    elif kind == "image":
        try:
            st.image(base64.b64decode(output.get("data", "")))
        except Exception:
            st.caption("[image output could not be rendered]")
    elif kind == "error":
        st.error(f"{output.get('ename')}: {output.get('evalue')}")
        with st.expander("Traceback"):
            st.code(output.get("traceback", ""))
