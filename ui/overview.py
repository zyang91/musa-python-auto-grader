"""Overview page — the class dashboard (design.md §6, §8)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from grader.feedback import build_class_report

from . import state
from .components import metric_cards


def render() -> None:
    rubric = state.current_rubric()
    session = state.session()
    loaded = state.loaded()

    st.title("MUSA Grader")
    st.subheader(rubric.name if rubric else "No assignment selected")

    if session is None:
        if loaded is None:
            st.info(
                "No grading session is currently loaded.\n\n"
                "Upload student submissions using the sidebar."
            )
            _previous_sessions()
            return
        st.success(f"{len(loaded.candidates)} submissions detected — ready to grade.")
        if st.button("▶ Run Grader", type="primary"):
            state.start_grading()
            st.rerun()
        st.caption("Open the Submissions page to check what was detected.")
        _previous_sessions()
        return

    summary = session.summary()
    metric_cards(
        [
            ("Submissions", summary["submissions"], None),
            ("Mean grade", summary["mean_score"],
             f"Mean final score across the {summary['graded']} graded submissions; "
             "submissions with no notebook are excluded."),
            ("Need review", summary["needs_review"], "Unresolved flags"),
            ("Execution errors", summary["execution_errors"], "Notebooks that did not run"),
        ]
    )

    st.divider()
    left, right = st.columns([3, 2])

    with left:
        st.markdown("### Grade distribution")
        distribution = pd.DataFrame(summary["distribution"]).set_index("bucket")["count"]
        st.bar_chart(distribution, x_label="Score (%)", y_label="Students")

    with right:
        st.markdown("### Most common issues")
        issues = summary.get("common_issues") or []
        if not issues:
            st.caption("No recurring issues were recorded.")
        for issue in issues[:8]:
            st.write(f"**{issue['count']}** — {issue['issue']}")

    st.divider()
    st.markdown("### Rubric averages")
    breakdown = summary.get("rubric_breakdown") or []
    if breakdown:
        st.dataframe(
            pd.DataFrame(breakdown)[
                ["name", "mean_score", "points_possible", "mean_percent"]
            ].rename(
                columns={
                    "name": "Rubric item",
                    "mean_score": "Mean",
                    "points_possible": "Out of",
                    "mean_percent": "Mean %",
                }
            ),
            hide_index=True,
            use_container_width=True,
        )

    with st.expander("Class report (markdown)"):
        st.code(build_class_report(summary, session.assignment_name), language="markdown")


def _previous_sessions() -> None:
    sessions = state.previous_sessions()
    if not sessions:
        return
    st.divider()
    st.markdown("### Previous grading sessions")
    for entry in sessions[:8]:
        columns = st.columns([4, 2, 2, 1])
        columns[0].write(f"`{entry['session_id']}`")
        columns[1].write(entry["assignment_name"])
        columns[2].write(f"{entry['submissions']} submissions")
        if columns[3].button("Open", key=f"open_{entry['session_id']}"):
            state.load_session_from_disk(entry["path"])
            st.rerun()
