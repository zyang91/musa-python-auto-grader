"""Class analytics page (design.md §8)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from . import state
from .components import metric_cards


def render() -> None:
    st.title("Class Analytics")
    session = state.session()
    if session is None:
        st.info("No grading session is loaded yet.")
        return

    summary = session.summary()
    scope = (
        f"Across the {summary['graded']} graded submissions "
        f"(of {summary['submissions']} detected)."
    )
    metric_cards(
        [
            ("Mean", summary["mean_score"], scope),
            ("Median", summary["median_score"], scope),
            ("Lowest", summary["min_score"], scope),
            ("Highest", summary["max_score"], scope),
        ]
    )
    if summary["graded"] < summary["submissions"]:
        st.caption(
            f"{summary['submissions'] - summary['graded']} submission(s) could not be "
            "graded (no notebook) and are excluded from these statistics."
        )

    st.divider()
    st.markdown("### Grade distribution")
    distribution = pd.DataFrame(summary["distribution"]).set_index("bucket")["count"]
    st.bar_chart(distribution, x_label="Score (%)", y_label="Students")

    st.markdown("### Mean score by rubric item")
    breakdown = pd.DataFrame(summary.get("rubric_breakdown") or [])
    if not breakdown.empty:
        st.bar_chart(
            breakdown.set_index("name")["mean_percent"],
            x_label="Rubric item", y_label="Class mean (%)",
        )
        st.dataframe(
            breakdown.rename(
                columns={
                    "name": "Rubric item",
                    "mean_score": "Mean",
                    "points_possible": "Out of",
                    "mean_percent": "Mean %",
                }
            )[["Rubric item", "Mean", "Out of", "Mean %"]],
            hide_index=True,
            use_container_width=True,
        )

    st.markdown("### Most common issues")
    issues = pd.DataFrame(summary.get("common_issues") or [])
    if issues.empty:
        st.caption("No recurring issues were recorded.")
    else:
        st.dataframe(
            issues.rename(columns={"issue": "Issue", "count": "Students"}),
            hide_index=True,
            use_container_width=True,
        )

    st.markdown("### Item statuses")
    rows = []
    for result in session.ordered_results():
        for item in result.items:
            rows.append({"Rubric item": item.name, "Status": item.status})
    if rows:
        pivot = (
            pd.DataFrame(rows)
            .pivot_table(index="Rubric item", columns="Status", aggfunc=len, fill_value=0)
        )
        st.dataframe(pivot, use_container_width=True)
