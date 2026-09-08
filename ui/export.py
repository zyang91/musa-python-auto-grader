"""Export page (design.md §29) and regrading controls (design.md §31)."""

from __future__ import annotations

import streamlit as st

from . import state


def render() -> None:
    st.title("Export")
    session = state.session()
    if session is None:
        st.info("No grading session is loaded yet.")
        return

    st.caption(
        f"Session `{session.session_id}` · {len(session.results)} submissions · "
        f"rubric {session.rubric_version}"
    )
    if session.root:
        st.caption(f"Saved to `{session.root}`")

    unresolved = sum(1 for r in session.ordered_results() if r.needs_review)
    if unresolved:
        st.warning(
            f"{unresolved} submissions are still flagged for review. You can export "
            "now, but the review queue is not empty."
        )

    columns = st.columns(2)
    with columns[0]:
        st.download_button(
            "⬇ Download grades.csv",
            data=session.grades_csv(),
            file_name=f"{session.session_id}_grades.csv",
            mime="text/csv",
            use_container_width=True,
        )
        st.download_button(
            "⬇ Download rubric scores (long CSV)",
            data=session.rubric_csv(),
            file_name=f"{session.session_id}_rubric_scores.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with columns[1]:
        st.download_button(
            "⬇ Download all feedback",
            data=session.feedback_zip(),
            file_name=f"{session.session_id}_feedback.zip",
            mime="application/zip",
            use_container_width=True,
        )
        st.download_button(
            "⬇ Download flagged submissions",
            data=session.flagged_csv(),
            file_name=f"{session.session_id}_flagged.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.download_button(
        "⬇ Download full grading archive",
        data=session.archive_zip(),
        file_name=f"{session.session_id}_archive.zip",
        mime="application/zip",
        use_container_width=True,
    )

    st.divider()
    st.markdown("### Preview: grades.csv")
    st.code(session.grades_csv(), language="text")

    st.divider()
    _regrade(session)


def _regrade(session) -> None:
    st.markdown("### Regrade submissions")
    st.caption(
        "Re-runs every automated check against the current rubric. Useful after "
        "correcting an expected value in `rubrics/hw1.yaml`."
    )
    loaded = state.loaded()
    if loaded is None:
        st.info(
            "The original submissions are no longer loaded in this app session. "
            "Re-select the submissions folder in the sidebar to regrade."
        )
        return
    preserve = st.checkbox("Preserve manual overrides", value=True)
    st.checkbox("Re-run qualitative grading", value=False, disabled=True,
                help="Qualitative grading always re-runs when LLM grading is enabled.")
    if st.button("Regrade", type="primary", disabled=state.is_grading()):
        state.start_grading(preserve_overrides=preserve)
        st.rerun()
