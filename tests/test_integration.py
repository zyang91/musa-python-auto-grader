"""End-to-end run against the shipped example submissions.

These execute real notebook kernels, so they are marked slow.
"""

from __future__ import annotations

import pytest

from grader.executor import MODE_LOCAL
from grader.service import GraderSettings, GradingService

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def graded(tmp_path_factory):
    root = tmp_path_factory.mktemp("results")
    settings = GraderSettings(
        execution_mode=MODE_LOCAL, cell_timeout_seconds=90, timeout_seconds=180
    )
    service = GradingService.from_rubric_path("rubrics/hw1.yaml", settings)
    loaded = service.load_submissions("examples/submissions")
    session = service.new_session(loaded.source)
    session.root = root / session.session_id
    return service, loaded, service.run(loaded.candidates, session=session)


def test_all_example_submissions_are_discovered(graded):
    _, loaded, _ = graded
    assert [c.student_id for c in loaded.candidates] == [
        f"student_00{n}" for n in range(1, 7)
    ]


def test_correct_submission_scores_nearly_full_marks(graded):
    _, _, session = graded
    result = session.results["student_001"]
    assert result.execution.success is True
    assert result.percentage >= 95
    # Only the qualitative item is left for a human.
    unresolved = [i.rubric_id for i in result.items if i.needs_review]
    assert unresolved == ["interpretation"]


def test_partial_submission_loses_the_right_points(graded):
    _, _, session = graded
    result = session.results["student_003"]
    assert result.execution.success is True

    assert result.item("data_loading").evidence["absolute_paths"]
    assert result.item("center_city_definition").evidence["missing_zips"] == ["19106"]
    assert "fraction" in result.item("percent_change_function").feedback
    # The parts they did correctly still earn full credit.
    assert result.item("philadelphia_subset").automatic_score == 15
    assert result.item("tidy_transformation").automatic_score == 15


def test_broken_notebook_still_gets_partial_grading(graded):
    """design.md §19: keep grading what ran; never a silent zero."""
    _, _, session = graded
    result = session.results["student_005"]
    assert result.execution.success is False
    assert result.execution.error_cell is not None
    assert "KeyError" in result.execution.error_message
    # The function defined after the failing cell still ran and still counts.
    assert result.item("percent_change_function").automatic_score == 15
    assert result.needs_review is True


def test_multiple_notebooks_are_flagged(graded):
    _, _, session = graded
    result = session.results["student_004"]
    assert any("2 notebooks" in reason for reason in result.review_reasons)


def test_missing_notebook_scores_zero_and_is_flagged(graded):
    _, _, session = graded
    result = session.results["student_006"]
    assert result.status == "skipped"
    assert result.total_score == 0
    assert result.needs_review is True


def test_executed_notebooks_are_saved_without_probe_cells(graded):
    import nbformat

    _, _, session = graded
    path = session.results["student_001"].execution.executed_notebook_path
    nb = nbformat.read(path, as_version=4)
    assert not any(c.get("metadata", {}).get("musa_probe") for c in nb.cells)
    assert "_musa_probe_main" not in nbformat.writes(nb)


def test_hidden_test_arguments_do_not_leak_to_the_student(graded):
    """The stored notebook must not reveal the hidden test cases."""
    import nbformat

    _, _, session = graded
    path = session.results["student_001"].execution.executed_notebook_path
    source = nbformat.writes(nbformat.read(path, as_version=4))
    assert "332217.5" not in source


def test_class_summary_and_queue(graded):
    _, _, session = graded
    summary = session.summary()
    assert summary["submissions"] == 6
    assert summary["execution_errors"] == 1
    assert summary["common_issues"]

    queue = session.queue()
    assert {entry["student_id"] for entry in queue} >= {"student_005", "student_006"}
    # Broken submissions sort above routine qualitative reads.
    assert queue[0]["student_id"] in {"student_005", "student_006"}
