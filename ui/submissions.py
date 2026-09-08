"""Submissions page — what discovery found (design.md §6, §17)."""

from __future__ import annotations

import streamlit as st

from . import state


def render() -> None:
    rubric = state.current_rubric()
    loaded = state.loaded()

    st.title("Submissions")
    st.caption(rubric.name if rubric else "")

    if loaded is None:
        st.info("Upload a Canvas ZIP or select a local folder in the sidebar.")
        st.markdown(
            "**Expected layouts**\n\n"
            "```\n"
            "submissions/\n"
            "├── student_001/\n"
            "│   ├── assignment1.ipynb\n"
            "│   └── data/\n"
            "└── student_002/\n"
            "    └── homework1.ipynb\n"
            "```\n\n"
            "or a Canvas export ZIP of flat files such as "
            "`doejane_12345_67890_assignment1.ipynb`."
        )
        return

    ok = loaded.ok_count
    total = len(loaded.candidates)
    st.write(f"**{total} submissions detected** · {ok} with a notebook · "
             f"{total - ok} without")

    if st.button("▶ Run Grader", type="primary", disabled=state.is_grading()):
        state.start_grading()
        st.rerun()

    st.divider()
    st.markdown("### Students detected")
    for candidate in loaded.candidates:
        icon = "✓" if candidate.ok and not candidate.warnings else ("⚠" if candidate.ok else "✕")
        detail = candidate.notebook_path.name if candidate.notebook_path else "no notebook"
        line = f"{icon} **{candidate.student_id}** — {detail}"
        if candidate.late:
            line += " · late"
        st.write(line)
        for warning in candidate.warnings:
            st.caption(f"⚠ {warning}")
        if len(candidate.all_notebooks) > 1:
            with st.expander(f"{len(candidate.all_notebooks)} notebooks in this submission"):
                for path in candidate.all_notebooks:
                    st.write(f"- `{path.name}`")
    st.caption(f"Source: `{loaded.source}`")
