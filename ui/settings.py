"""Settings page (design.md §33)."""

from __future__ import annotations

import streamlit as st

from grader.executor import MODE_DOCKER, MODE_LOCAL, docker_available, docker_image_exists

from . import state


def render() -> None:
    st.title("Settings")
    config = state.settings()

    st.markdown("### Execution")
    columns = st.columns(2)
    with columns[0]:
        config.timeout_seconds = st.number_input(
            "Hard timeout per submission (s)", 30, 3600, int(config.timeout_seconds), 30
        )
        config.cell_timeout_seconds = st.number_input(
            "Timeout per cell (s)", 10, 1800, int(config.cell_timeout_seconds), 10
        )
    with columns[1]:
        config.memory_limit = st.text_input("Memory limit", config.memory_limit)
        config.cpu_limit = st.text_input("CPU limit", str(config.cpu_limit))

    config.docker_image = st.text_input("Docker image", config.docker_image)
    if config.execution_mode == MODE_DOCKER:
        if not docker_available():
            st.error("Docker is not reachable from this machine.")
        elif not docker_image_exists(config.docker_image):
            st.warning(
                f"`{config.docker_image}` is not built. Run:\n\n"
                "```\ndocker build -t musa-grader:latest -f docker/Dockerfile .\n```"
            )
        else:
            st.success("Docker image is available.")
    else:
        st.warning(
            "Unsafe Local mode executes student notebooks directly on this machine, "
            "with no network, memory or filesystem isolation."
        )

    st.divider()
    st.markdown("### Review")
    config.review_below_full_marks = st.toggle(
        "Review every submission that loses points",
        value=config.review_below_full_marks,
        help=(
            "On: any deduction goes to the review queue, so a person signs off on "
            "every point taken away. Off: only uncertain or failed submissions are "
            "flagged."
        ),
    )
    config.confidence_threshold = st.slider(
        "Confidence threshold for manual review",
        0.0, 1.0, float(config.confidence_threshold), 0.05,
        help="Rubric items graded below this confidence are sent to the review queue.",
    )

    st.divider()
    st.markdown("### Qualitative grading")
    config.llm_enabled = st.toggle("Enable LLM grading", value=config.llm_enabled)
    columns = st.columns(2)
    with columns[0]:
        config.llm_provider = st.selectbox(
            "Provider", ["anthropic"], index=0, disabled=not config.llm_enabled
        )
    with columns[1]:
        config.llm_model = st.text_input(
            "Model", config.llm_model, disabled=not config.llm_enabled
        )
    st.caption(
        "Student names are never sent to the provider, and any low-confidence "
        "judgement is routed to the review queue rather than applied silently. "
        "Requires ANTHROPIC_API_KEY in the environment."
    )

    st.divider()
    st.markdown("### Rubric")
    rubric = state.current_rubric()
    if rubric is not None:
        st.write(f"**{rubric.name}** · version `{rubric.version}` · {rubric.total_points:g} points")
        st.caption(f"`{rubric.source_path}`")
        st.caption("Rubric editing is YAML-only in this prototype.")
        with st.expander("Rubric items"):
            for item in rubric.items:
                st.write(f"- **{item.name}** ({item.points:g} pts, `{item.type}`)")
