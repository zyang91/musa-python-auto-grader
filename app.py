"""MUSA Grader — Streamlit entry point.

Run with:  streamlit run app.py

The UI never grades anything itself: it configures a ``GradingService`` and
renders what comes back (design.md §4).
"""

from __future__ import annotations

import streamlit as st

import grader
from grader.executor import MODE_DOCKER, MODE_LOCAL
from ui import (
    analytics,
    export,
    grading,
    overview,
    review_queue,
    settings as settings_page,
    state,
    student_review,
    submissions,
)

st.set_page_config(page_title="MUSA Grader", page_icon="📓", layout="wide")

PAGE_RENDERERS = {
    "🏠 Overview": overview.render,
    "📥 Submissions": submissions.render,
    "▶ Grading": grading.render,
    "👥 Students": student_review.render,
    "⚠ Review Queue": review_queue.render,
    "📊 Class Analytics": analytics.render,
    "📤 Export": export.render,
    "⚙ Settings": settings_page.render,
}


def sidebar() -> None:
    config = state.settings()
    with st.sidebar:
        st.markdown("## MUSA Grader")

        choices = state.rubric_choices()
        if not choices:
            st.error("No rubric files were found in `rubrics/`.")
        else:
            ids = sorted(choices)
            labels = {}
            for assignment_id in ids:
                rubric = state.load_rubric_safe(choices[assignment_id])
                labels[assignment_id] = rubric.name if rubric else assignment_id
            st.session_state.assignment_id = st.selectbox(
                "Assignment",
                ids,
                index=ids.index(st.session_state.assignment_id)
                if st.session_state.assignment_id in ids else 0,
                format_func=lambda key: labels.get(key, key),
            )

        st.divider()
        st.markdown("**Submissions**")
        uploaded = st.file_uploader("Upload Canvas ZIP", type=["zip"])
        if uploaded is not None and st.button("Load ZIP", use_container_width=True):
            state.load_from_upload(uploaded)
            st.rerun()

        folder = st.text_input("or local folder", value="examples/submissions")
        if st.button("Load folder", use_container_width=True):
            state.load_from_path(folder)
            st.rerun()

        st.divider()
        st.markdown("**Execution mode**")
        mode = st.radio(
            "Execution mode",
            [MODE_DOCKER, MODE_LOCAL],
            index=0 if config.execution_mode == MODE_DOCKER else 1,
            format_func=lambda value: "Safe Docker" if value == MODE_DOCKER else "Unsafe Local",
            label_visibility="collapsed",
        )
        config.execution_mode = mode

        st.markdown("**Qualitative grading**")
        config.llm_enabled = st.checkbox("Enable LLM grading", value=config.llm_enabled)

        st.divider()
        loaded = state.loaded()
        st.button(
            "▶ Run Grader",
            type="primary",
            use_container_width=True,
            disabled=loaded is None or state.is_grading(),
            on_click=state.start_grading,
        )
        if loaded is not None:
            st.caption(f"{len(loaded.candidates)} submissions loaded")

        for warning in state.execution_warnings():
            st.warning(warning, icon="⚠")

        st.divider()
        rubric = state.current_rubric()
        st.caption(f"MUSA Grader v{grader.__version__}")
        if rubric is not None:
            st.caption(f"Rubric: {rubric.version}")


def main() -> None:
    state.init()
    sidebar()

    state.apply_pending_page()
    st.session_state.setdefault("nav_radio", st.session_state.page)
    page = st.radio(
        "Navigation",
        list(PAGE_RENDERERS),
        horizontal=True,
        label_visibility="collapsed",
        key="nav_radio",
    )
    st.session_state.page = page

    message = state.drain_toast()
    if message:
        st.toast(message)

    state.collect_finished_run()
    PAGE_RENDERERS[st.session_state.page]()


main()
