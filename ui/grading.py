"""Grading page — live progress (design.md §7)."""

from __future__ import annotations

import time

import streamlit as st

from grader.executor import MODE_LOCAL

from . import state

STAGE_LABELS = [
    ("execution", "Notebook execution"),
    ("structural", "Structural checks"),
    ("hidden", "Hidden tests"),
    ("feedback", "Feedback generation"),
]

STAGE_ICONS = {"done": "✓", "running": "running", "error": "✕", "waiting": "waiting"}


def render() -> None:
    st.title("Grading")
    loaded = state.loaded()
    progress = st.session_state.progress
    running = state.is_grading()

    if loaded is None and progress is None:
        st.info("Load submissions first, then start the grader from the sidebar.")
        return

    for warning in state.execution_warnings():
        st.warning(warning)

    controls = st.columns([1, 1, 3])
    with controls[0]:
        if st.button("▶ Run Grader", type="primary", disabled=running or loaded is None):
            state.start_grading()
            st.rerun()
    with controls[1]:
        if st.button("Stop", disabled=not running):
            state.cancel_grading()
            st.info("Finishing the current submission, then stopping.")

    if state.settings().execution_mode == MODE_LOCAL:
        st.caption("⚠ Running in Unsafe Local mode — student code executes on this machine.")

    if progress is None:
        return

    st.divider()
    total = max(progress.total, 1)
    st.markdown(f"### Grading {state.current_rubric().name if state.current_rubric() else ''}")
    st.progress(min(progress.completed / total, 1.0),
                text=f"{progress.completed} / {progress.total}")

    if progress.current_student and running:
        st.write(f"**Currently grading:** `{progress.current_student}`")
        for key, label in STAGE_LABELS:
            status = (progress.stages or {}).get(key, "waiting")
            icon = STAGE_ICONS.get(status, status)
            st.write(f"{label:<24} {icon}")

    columns = st.columns(5)
    columns[0].metric("Completed", progress.completed)
    columns[1].metric("Successful", progress.successful)
    columns[2].metric("Flagged", progress.flagged)
    columns[3].metric("Failed", progress.failed)
    columns[4].metric("Remaining", progress.remaining)

    if running:
        # Poll rather than block: the page keeps repainting while grading runs.
        time.sleep(1.0)
        st.rerun()

    state.collect_finished_run()
    session = state.session()
    if session is not None:
        st.success(
            f"Grading finished — {len(session.results)} submissions, "
            f"{sum(1 for r in session.ordered_results() if r.needs_review)} need review."
        )
        if st.button("Go to class overview"):
            state.set_page("🏠 Overview")
            st.rerun()
    if st.session_state.last_error:
        st.error(st.session_state.last_error)
