"""Review queue page (design.md §14)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from . import state


def render() -> None:
    st.title("Review Queue")
    session = state.session()
    if session is None:
        st.info("No grading session is loaded yet.")
        return

    queue = session.queue()
    if not queue:
        st.success("Nothing is waiting for review.")
        _reviewed_list(session)
        return

    st.caption(f"{len(queue)} submissions need a human decision.")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Student": entry["student_id"],
                    "Reason": entry["reason"],
                    "Score": entry["score"],
                    "Confidence": entry["confidence"],
                }
                for entry in queue
            ]
        ),
        hide_index=True,
        use_container_width=True,
        column_config={
            "Score": st.column_config.NumberColumn(format="%.1f"),
            "Confidence": st.column_config.NumberColumn(format="%.2f"),
        },
    )

    st.divider()
    for entry in queue:
        columns = st.columns([2, 5, 1, 1])
        columns[0].write(f"**{entry['student_id']}**")
        with columns[1]:
            st.write(entry["reason"])
            if len(entry["all_reasons"]) > 1:
                with st.expander(f"{len(entry['all_reasons']) - 1} more"):
                    for reason in entry["all_reasons"][1:]:
                        st.write(f"- {reason}")
        if columns[2].button("Open", key=f"queue_open_{entry['student_id']}"):
            state.open_student(entry["student_id"])
            st.rerun()
        if columns[3].button("Mark Reviewed", key=f"queue_done_{entry['student_id']}"):
            session.mark_reviewed(entry["student_id"], True)
            session.save()
            st.rerun()

    _reviewed_list(session)


def _reviewed_list(session) -> None:
    reviewed = [r for r in session.ordered_results() if r.reviewed]
    if not reviewed:
        return
    with st.expander(f"{len(reviewed)} already reviewed"):
        for result in reviewed:
            columns = st.columns([3, 1])
            columns[0].write(f"{result.student_id} — {result.total_score:g}/{result.max_score:g}")
            if columns[1].button("Reopen", key=f"reopen_{result.student_id}"):
                session.mark_reviewed(result.student_id, False)
                session.save()
                st.rerun()
