"""End-to-end HW2 runs against the shipped example submissions.

These execute real notebook kernels, so they are marked slow.

The property that matters most here is the one that makes this assignment
different from Assignment 1: **the grading run fails for every submission** —
students do not hand in their dataset, so every notebook dies at ``read_csv`` —
and the charts still have to be graded, out of the outputs the student saved.
"""

from __future__ import annotations

import importlib.util

import pytest

from grader.executor import MODE_LOCAL
from grader.service import GraderSettings, GradingService

pytestmark = pytest.mark.slow


def _service(**overrides):
    settings = GraderSettings(
        execution_mode=MODE_LOCAL, cell_timeout_seconds=90, timeout_seconds=240,
        **overrides,
    )
    return GradingService.from_rubric_path("rubrics/hw2.yaml", settings)


def _demo_submissions(dest):
    spec = importlib.util.spec_from_file_location(
        "make_hw2_submissions", "examples/make_hw2_submissions.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_submissions(dest)


@pytest.fixture(scope="module")
def graded(tmp_path_factory):
    root = tmp_path_factory.mktemp("hw2run")
    submissions = _demo_submissions(root / "submissions")
    service = _service()
    loaded = service.load_submissions(submissions)
    session = service.new_session(loaded.source)
    session.root = root / session.session_id
    return service, loaded, service.run(loaded.candidates, session=session)


def _result(session, student_id):
    return session.results[student_id]


def test_submissions_contain_no_data(graded):
    """The demo mirrors the real hand-in: notebooks and nothing else."""
    from pathlib import Path

    _, loaded, _ = graded
    assert not list(Path(loaded.source).rglob("*.csv"))


def test_no_data_means_no_preflight_nag(graded):
    """Unlike HW1, the grader is not expected to supply anything."""
    assert _service().preflight() == []


def test_every_grading_run_fails_and_that_is_fine(graded):
    """The point of the assignment is the elements, not a reproducible result."""
    _, _, session = graded
    assert all(not r.execution.success for r in session.ordered_results())
    best = _result(session, "student_101")
    assert best.total_score >= 95


def test_charts_are_graded_from_the_students_own_saved_output(graded):
    _, _, session = graded
    item = _result(session, "student_101").item("altair_charts")
    assert item.status == "pass"
    assert item.evidence["evidence_source"] == "merged"
    assert {c["output_source"] for c in item.evidence["chart_details"]} == {"submitted"}


def test_the_altair_requirements_are_read_out_of_the_compiled_spec(graded):
    _, _, session = graded
    good = _result(session, "student_101")
    transformation = good.item("altair_transformation")
    brush = good.item("altair_brush_selection")
    assert transformation.status == "pass" and transformation.evidence["operations"]
    assert brush.status == "pass" and brush.evidence["brushes"]


def test_the_extra_credit_dashboard_is_found_and_left_to_a_human(graded):
    _, _, session = graded
    item = _result(session, "student_101").item("altair_dashboard_extra_credit")
    assert item.status == "manual_review"
    assert item.points_possible == 0
    assert item.evidence["cross_filter_params"]


def test_a_pan_zoom_interactive_does_not_earn_the_brush_mark(graded):
    _, _, session = graded
    assert _result(session, "student_102").item("altair_brush_selection").automatic_score == 0


def test_an_absolute_path_is_the_only_data_loading_deduction(graded):
    """Nothing about the dataset itself is graded — only how it is loaded."""
    _, _, session = graded
    item = _result(session, "student_102").item("data_loading")
    assert "absolute file path" in item.feedback
    assert item.automatic_score == 6


def test_a_notebook_handed_in_unrun_is_marked_down_for_that_alone(graded):
    _, _, session = graded
    unrun = _result(session, "student_104")
    assert "no saved output at all" in unrun.item("notebook_execution").feedback
    # The written work is still there and still graded.
    assert unrun.item("chart_conclusions").automatic_score == 15


def test_every_judgement_item_reaches_the_review_queue(graded):
    _, _, session = graded
    for result in session.ordered_results():
        for item in result.items:
            if item.type == "qualitative":
                assert item.status == "manual_review", (result.student_id, item.rubric_id)
        assert result.needs_review


def test_no_students_dataset_leaks_into_the_stored_evidence(graded):
    """Altair inlines the whole dataframe in its spec; it must not be kept."""
    import json

    _, _, session = graded
    blob = json.dumps([r.to_dict() for r in session.ordered_results()])
    assert "philly_311_sample" in blob  # the path is evidence
    assert '"service_request_id": 1000070' not in blob  # the rows are not
    assert len(blob) < 2_000_000
