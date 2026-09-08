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


SHARED_DATA = "examples/data/zillow_zhvi.csv"


def _service(data=(SHARED_DATA,), **overrides):
    """Students submit notebooks only; the grader supplies the data."""
    settings = GraderSettings(
        execution_mode=MODE_LOCAL, cell_timeout_seconds=90, timeout_seconds=240,
        shared_data_paths=list(data), **overrides
    )
    return GradingService.from_rubric_path("rubrics/hw1.yaml", settings)


def _demo_submissions(dest):
    """Build the demo tree from examples/, rather than reading the folder itself.

    `examples/submissions/` is a working area — real student notebooks get
    dropped into it — so the tests must not depend on its contents.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "make_example_submissions", "examples/make_example_submissions.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_submissions(dest)


@pytest.fixture(scope="module")
def graded(tmp_path_factory):
    root = tmp_path_factory.mktemp("run")
    submissions = _demo_submissions(root / "submissions")
    service = _service()
    loaded = service.load_submissions(submissions)
    session = service.new_session(loaded.source)
    session.root = root / session.session_id
    return service, loaded, service.run(loaded.candidates, session=session)


def test_submissions_contain_no_data(graded):
    """The demo mirrors the real hand-in: notebooks and nothing else."""
    from pathlib import Path

    _, loaded, _ = graded
    assert not list(Path(loaded.source).rglob("*.csv"))


def test_preflight_warns_when_no_data_is_configured():
    problems = _service(data=()).preflight()
    assert problems and "submit only a notebook" in problems[0]


def test_preflight_warns_about_a_missing_file():
    problems = _service(data=("/nope/missing.csv",)).preflight()
    assert any("not found" in p for p in problems)


def test_data_is_placed_where_each_notebook_reads_from(graded):
    """Three notebooks, three different paths, all supplied from one file."""
    _, _, session = graded
    paths = {
        student: {
            entry["path"]
            for entry in session.results[student].artifacts["data_placement"]["placed"]
        }
        for student in ("student_001", "student_003", "student_005")
    }
    assert "data/zillow_zhvi.csv" in paths["student_001"]
    # student_003 keeps the path in a variable, under the real Zillow filename.
    assert "data/Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv" in paths["student_003"]
    # student_005 reads from the working directory root.
    assert "zillow_zhvi.csv" in paths["student_005"]


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

    altered_file = tmp_path / "alternate_vintage.csv"
    altered.to_csv(altered_file, index=False)

    submissions = tmp_path / "submissions"
    submission = submissions / "student_alt"
    submission.mkdir(parents=True)
    shutil.copy2("examples/good_submission.ipynb", submission / "assignment-1.ipynb")

    service = _service(data=(str(altered_file),))
    loaded = service.load_submissions(submissions)
    session = service.new_session(loaded.source)
    session.root = tmp_path / "results"
    result = service.run(loaded.candidates, session=session).results["student_alt"]

    assert result.total_score == 100
    assert result.needs_review is False
    # ...and the checks really did see different data.
    tidy = result.item("tidy_transformation").evidence
    assert tidy["unique_dates"] == len(dates) - 20
    assert tidy["unique_ids"] == len(philadelphia) - len(dropped)
