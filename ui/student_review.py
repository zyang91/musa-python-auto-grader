"""Student review page — the most important screen (design.md §10-13)."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from grader.feedback import build_feedback
from grader.models import STATUS_MANUAL_REVIEW, RubricItemResult, SubmissionResult, status_icon
from grader.notebook import render_cells

from . import state
from .components import (
    confidence_text,
    filter_results,
    render_evidence,
    render_notebook,
    status_badge,
    submissions_table,
)

FILTERS = [
    "All", "Needs Review", "Execution Failed", "Score < 70", "Low Confidence", "Completed",
]


def render() -> None:
    session = state.session()
    if session is None:
        st.title("Students")
        st.info("No grading session is loaded yet.")
        return

    selected = st.session_state.selected_student
    if selected is None or selected not in session.results:
        _render_table(session)
        return
    _render_student(session, session.results[selected])


# ---------------------------------------------------------------------------
# Student table (design.md §9)
# ---------------------------------------------------------------------------

def _render_table(session) -> None:
    st.title("Students")
    results = session.ordered_results()

    columns = st.columns([3, 2])
    with columns[0]:
        st.session_state.student_search = st.text_input(
            "Search", value=st.session_state.student_search, placeholder="student id"
        )
    with columns[1]:
        st.session_state.student_filter = st.selectbox(
            "Filter", FILTERS, index=FILTERS.index(st.session_state.student_filter)
        )

    filtered = filter_results(
        results, st.session_state.student_filter, st.session_state.student_search
    )
    st.caption(f"{len(filtered)} of {len(results)} submissions")

    if not filtered:
        st.info("No submissions match this filter.")
        return

    st.dataframe(
        submissions_table(filtered),
        hide_index=True,
        use_container_width=True,
        column_config={
            "Score": st.column_config.NumberColumn(format="%.1f"),
            "Confidence": st.column_config.NumberColumn(format="%.2f"),
        },
    )

    st.markdown("#### Open a submission")
    grid = st.columns(4)
    for index, result in enumerate(filtered):
        label = f"{status_icon(result.execution.status)} {result.student_id}"
        if grid[index % 4].button(label, key=f"open_student_{result.student_id}",
                                  use_container_width=True):
            st.session_state.selected_student = result.student_id
            st.rerun()


# ---------------------------------------------------------------------------
# One student
# ---------------------------------------------------------------------------

def _render_student(session, result: SubmissionResult) -> None:
    header = st.columns([4, 1, 1, 1])
    with header[0]:
        st.title(result.student_id)
        st.markdown(
            f"**Current Score: {result.total_score:g} / {result.max_score:g}** · "
            + ("Status: Needs Review" if result.needs_review
               else ("Status: Reviewed" if result.reviewed else "Status: Graded"))
        )
    previous_id = session.neighbour(result.student_id, -1)
    next_id = session.neighbour(result.student_id, 1)
    if header[1].button("← Previous", disabled=previous_id is None):
        st.session_state.selected_student = previous_id
        st.rerun()
    if header[2].button("Next →", disabled=next_id is None):
        st.session_state.selected_student = next_id
        st.rerun()
    if header[3].button("All students"):
        st.session_state.selected_student = None
        st.rerun()

    if result.has_manual_override:
        st.caption(
            f"Automatic total was {result.automatic_total:g}; "
            f"manual overrides are applied."
        )

    reasons = result.open_review_reasons()
    if reasons:
        with st.expander(f"⚠ {len(reasons)} reason(s) this submission needs review", expanded=True):
            for reason in reasons:
                st.write(f"- {reason}")

    tabs = st.tabs(["Grading", "Notebook", "Execution Log", "Raw Results", "Feedback"])

    with tabs[0]:
        _render_rubric(session, result)
    with tabs[1]:
        _render_notebook_tab(result)
    with tabs[2]:
        _render_execution_tab(result)
    with tabs[3]:
        st.json(result.to_dict())
    with tabs[4]:
        st.markdown(build_feedback(result, session.assignment_name))

    st.divider()
    review_columns = st.columns([1, 3])
    with review_columns[0]:
        if st.button(
            "Mark Reviewed" if not result.reviewed else "Reopen",
            type="primary" if not result.reviewed else "secondary",
        ):
            session.mark_reviewed(result.student_id, not result.reviewed)
            session.save()
            st.rerun()
    review_columns[1].caption(
        "Marking a submission reviewed removes it from the review queue; the "
        "automatic scores are kept as they were."
    )


def _render_rubric(session, result: SubmissionResult) -> None:
    for item in result.items:
        icon = status_icon(item.status)
        title = (
            f"{icon} {item.name} — {item.final_score:g} / {item.points_possible:g}"
            + (" · overridden" if item.manual_override else "")
        )
        with st.expander(title, expanded=item.needs_review):
            top = st.columns([3, 1])
            with top[0]:
                st.markdown(status_badge(item.status), unsafe_allow_html=True)
                st.write(item.feedback or "_No feedback recorded._")
            with top[1]:
                st.metric("Confidence", confidence_text(item.confidence))

            st.markdown("**Evidence**")
            render_evidence(item)

            st.divider()
            _override_form(session, result, item)


def _override_form(session, result: SubmissionResult, item: RubricItemResult) -> None:
    """Manual score adjustment (design.md §11)."""
    with st.form(f"override_{result.student_id}_{item.rubric_id}"):
        st.caption(f"Automatic score: {item.automatic_score:g} / {item.points_possible:g}")
        columns = st.columns([1, 3])
        with columns[0]:
            manual_score = st.number_input(
                "Manual score",
                min_value=0.0,
                max_value=float(item.points_possible),
                value=float(item.manual_score if item.manual_score is not None
                            else item.automatic_score),
                step=0.5,
            )
        with columns[1]:
            reason = st.text_input("TA comment", value=item.override_reason)
        enabled = st.checkbox("Override automatic grade", value=item.manual_override)
        if st.form_submit_button("Save"):
            session.set_override(
                result.student_id, item.rubric_id, manual_score, reason, enabled
            )
            session.save()
            state.notify(f"Saved {item.name} for {result.student_id}.")
            st.rerun()


def _render_notebook_tab(result: SubmissionResult) -> None:
    executed = result.execution.executed_notebook_path
    source = result.notebook_path
    choice = "Executed"
    if executed and source:
        choice = st.radio(
            "Version", ["Executed", "As submitted"], horizontal=True, key=f"nb_{result.student_id}"
        )
    path = executed if (choice == "Executed" and executed) else source
    if not path or not Path(path).exists():
        st.info("The notebook file is no longer available on disk.")
        return
    st.caption(f"`{path}`")
    render_notebook(render_cells(path))


def _render_execution_tab(result: SubmissionResult) -> None:
    execution = result.execution
    columns = st.columns(4)
    columns[0].metric("Success", "yes" if execution.success else "no")
    columns[1].metric("Time (s)", f"{execution.execution_time_seconds:g}")
    columns[2].metric("Mode", execution.mode)
    columns[3].metric("Timed out", "yes" if execution.timeout else "no")

    if execution.error_message:
        st.error(f"Cell {execution.error_cell}: {execution.error_message}")
    if execution.traceback:
        st.code(execution.traceback[-6000:])
    st.markdown("**Runner log**")
    st.code(execution.log[-8000:] or "(empty)")
    if result.artifacts.get("probe_errors"):
        st.warning("Probe warnings: " + "; ".join(result.artifacts["probe_errors"][:5]))
