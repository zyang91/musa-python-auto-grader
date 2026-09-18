"""MUSA Grader — Streamlit entry point.

Run with:  streamlit run app.py

The UI never grades anything itself: it configures a ``GradingService`` and
renders what comes back (design.md §4).
"""

from __future__ import annotations

from pathlib import Path

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


def data_section(config, rubric) -> None:
    """Assignment data, supplied by the instructor (design.md §16-17).

    Uploading is the primary path: the file does not have to already live
    somewhere on this machine, and nothing about its location is assumed.
    """
    st.markdown("**Assignment data**")
    st.caption(
        "Students submit only a notebook, so you supply the data file here and "
        "the grader places it into every submission."
    )

    uploads = st.file_uploader(
        "Upload data file(s)",
        type=["csv", "tsv", "zip", "json", "geojson", "xlsx", "xls", "parquet", "txt", "gz"],
        accept_multiple_files=True,
        key="shared_data_upload",
        help="Uploads are kept in .musa_grader_data/ so they survive a restart.",
    )
    if uploads:
        state.add_data_files([state.save_uploaded_data(upload) for upload in uploads])

    with st.expander("or use a file already on this machine"):
        existing_path = st.text_input(
            "Path to the data file",
            key="shared_data_path",
            placeholder="~/Downloads/Zip_zhvi_..._month.csv",
        )
        if st.button("Add this file", use_container_width=True, disabled=not existing_path):
            state.add_data_files([existing_path])
            st.rerun()

    if config.shared_data_paths:
        st.caption("In use:")
        for path in list(config.shared_data_paths):
            row = st.columns([6, 1])
            row[0].write(state.describe_data_file(path))
            if row[1].button("✕", key=f"drop_data_{path}", help="Remove"):
                state.remove_data_file(path)
                st.rerun()
    else:
        st.caption(rubric.data.get("description", "").strip() or "No data file set yet.")


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
        uploaded = st.file_uploader("Upload Canvas ZIP", type=["zip"], key="submissions_zip")
        if uploaded is not None and state.load_upload_once(uploaded):
            st.rerun()

        folder = st.text_input("or local folder", value="examples/submissions")
        if st.button("Load folder", use_container_width=True):
            # A folder replaces an earlier upload; re-uploading should load again.
            st.session_state.loaded_upload_id = None
            state.load_from_path(folder)
            st.rerun()

        loaded = state.loaded()
        if st.session_state.last_error:
            st.error(f"Could not load submissions — {st.session_state.last_error}")
        elif loaded is not None:
            if loaded.candidates:
                st.success(
                    f"{len(loaded.candidates)} submissions loaded from "
                    f"`{Path(loaded.source).name}`"
                )
            else:
                st.warning(
                    f"`{Path(loaded.source).name}` loaded, but no notebooks were found "
                    "in it."
                )

        rubric = state.current_rubric()
        if rubric is not None and rubric.offers_data:
            st.divider()
            data_section(config, rubric)

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
        blockers = state.run_blockers()
        st.button(
            "▶ Run Grader",
            type="primary",
            use_container_width=True,
            disabled=bool(blockers),
            on_click=state.start_grading,
            help=" ".join(blockers) if blockers else None,
        )
        for reason in blockers:
            st.caption(f"Run is disabled: {reason}")

        for problem in state.preflight():
            st.error(problem, icon="🚫")
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
