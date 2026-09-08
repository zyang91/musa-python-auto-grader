"""End-to-end runs against the shipped example submissions.

These execute real notebook kernels, so they are marked slow.
"""

from __future__ import annotations

import shutil

import pandas as pd
import pytest

from grader.executor import MODE_LOCAL
from grader.service import GraderSettings, GradingService

pytestmark = pytest.mark.slow

ID_COLUMNS = ["RegionID", "SizeRank", "RegionName", "RegionType", "StateName",
              "State", "City", "Metro", "CountyName"]


def _service(**overrides):
    settings = GraderSettings(
        execution_mode=MODE_LOCAL, cell_timeout_seconds=90, timeout_seconds=240, **overrides
    )
    return GradingService.from_rubric_path("rubrics/hw1.yaml", settings)


@pytest.fixture(scope="module")
def graded(tmp_path_factory):
    root = tmp_path_factory.mktemp("results")
    service = _service()
    loaded = service.load_submissions("examples/submissions")
    session = service.new_session(loaded.source)
    session.root = root / session.session_id
    return service, loaded, service.run(loaded.candidates, session=session)


def test_all_example_submissions_are_discovered(graded):
    _, loaded, _ = graded
    assert [c.student_id for c in loaded.candidates] == [
        f"student_00{n}" for n in range(1, 8)
    ]


def test_correct_submission_scores_full_marks_with_nothing_to_review(graded):
    _, _, session = graded
    result = session.results["student_001"]
    assert result.execution.success is True
    assert result.total_score == 100
    assert result.needs_review is False


def test_partial_submission_loses_the_right_points(graded):
    """Each deduction should name a specific instruction that was not followed."""
    _, _, session = graded
    result = session.results["student_003"]
    assert result.execution.success is True

    assert result.item("data_loading").evidence["absolute_paths"]
    # The steps they did correctly still earn full credit.
    assert result.item("philadelphia_subset").automatic_score == 15
    # ...and the ones they did not are named.
    assert "ZHVI" in result.item("tidy_transformation").feedback
    assert "19109" in result.item("center_city_split").feedback
    assert "first and last rows" in result.item("percent_increase_function").feedback
    # The Donut Effect still holds, so the comparison itself is correct.
    assert result.item("donut_effect_comparison").status == "pass"


def test_untouched_template_is_recognised(graded):
    """The template runs cleanly but does nothing, and must not look like work."""
    _, _, session = graded
    result = session.results["student_007"]
    assert result.execution.success is True
    assert result.item("notebook_execution").automatic_score == 10
    assert result.total_score == 10
    assert "unfilled" in result.item("percent_increase_function").feedback


def test_broken_notebook_still_gets_partial_grading(graded):
    """Keep grading what ran; never a silent zero."""
    _, _, session = graded
    result = session.results["student_005"]
    assert result.execution.success is False
    assert "KeyError" in result.execution.error_message
    # They trimmed to Philadelphia and wrote a correct function before crashing.
    assert result.item("philadelphia_subset").automatic_score == 15
    assert result.item("percent_increase_function").automatic_score == 20
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


def test_class_summary_and_queue(graded):
    _, _, session = graded
    summary = session.summary()
    assert summary["submissions"] == 7
    assert summary["execution_errors"] == 1
    queue = session.queue()
    assert {entry["student_id"] for entry in queue} >= {"student_005", "student_006"}
    assert queue[0]["student_id"] in {"student_005", "student_006"}


# ---------------------------------------------------------------------------
# The point of the redesign: grades must not move when the data does
# ---------------------------------------------------------------------------

def test_same_notebook_different_zillow_vintage_scores_the_same(tmp_path):
    """A shorter, smaller, rescaled ZHVI file must not change the grade."""
    source = pd.read_csv("examples/data/zillow_zhvi.csv")
    dates = [c for c in source.columns if c not in ID_COLUMNS]

    philadelphia = source[source["City"] == "Philadelphia"]["RegionName"].unique()
    center_city = {19102, 19103, 19106, 19107, 19109, 19123, 19130, 19146, 19147}
    dropped = set(philadelphia[:6]) - center_city

    altered = source[~source["RegionName"].isin(dropped)][ID_COLUMNS + dates[20:]].copy()
    for column in dates[20:]:
        altered[column] = (altered[column] * 1.37).round(0)

    submission = tmp_path / "student_alt"
    (submission / "data").mkdir(parents=True)
    altered.to_csv(submission / "data" / "zillow_zhvi.csv", index=False)
    shutil.copy2("examples/good_submission.ipynb", submission / "assignment-1.ipynb")

    service = _service()
    loaded = service.load_submissions(tmp_path)
    session = service.new_session(loaded.source)
    session.root = tmp_path / "results"
    result = service.run(loaded.candidates, session=session).results["student_alt"]

    assert result.total_score == 100
    assert result.needs_review is False
    # ...and the checks really did see different data.
    tidy = result.item("tidy_transformation").evidence
    assert tidy["unique_dates"] == len(dates) - 20
    assert tidy["unique_ids"] == len(philadelphia) - len(dropped)
