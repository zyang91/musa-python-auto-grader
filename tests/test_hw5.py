"""Assignment 5: graded without running the notebook or opening its data.

Two properties the design rests on. **Grading never reaches the network** —
the notebooks query the Census API and download TIGER tracts. And **grading
never opens a data file** — the restaurants come from the Yelp Dataset
Challenge, 8 GB in full, and loading it once per student would take minutes
and run the grading machine out of memory. So the demo submissions are graded
with notebook execution, subprocesses, sockets and every pandas/geopandas
reader wired to fail. The rest pin the grades the demo submissions earn.
"""

from __future__ import annotations

import importlib.util
import socket
import subprocess
from pathlib import Path

import pytest

from grader.executor import MODE_DOCKER, MODE_LOCAL, MODE_NOT_EXECUTED
from grader.models import STATUS_PASS
from grader.rubric import load_rubric
from grader.service import GraderSettings, GradingService

from conftest import ROOT

RUBRIC = ROOT / "rubrics" / "hw5.yaml"
PART1 = {
    "census_income", "census_tracts", "restaurants", "spatial_join",
    "income_merge", "stars_income_plot",
}


def _builder():
    spec = importlib.util.spec_from_file_location(
        "make_hw5_submissions", ROOT / "examples" / "make_hw5_submissions.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def submissions(tmp_path_factory) -> Path:
    return _builder().build_submissions(tmp_path_factory.mktemp("hw5") / "submissions")


def _tripwire(monkeypatch) -> None:
    """Every way grading could run the notebook, go online or load the data."""
    import pandas

    def forbidden(what):
        def fail(*args, **kwargs):
            raise AssertionError(f"Assignment 5 grading must not {what}: {args[:1]}")
        return fail

    monkeypatch.setattr("grader.service.execute_submission", forbidden("execute a notebook"))
    monkeypatch.setattr("grader.executor.execute_submission", forbidden("execute a notebook"))
    monkeypatch.setattr(socket.socket, "connect", forbidden("open a connection"))
    monkeypatch.setattr(socket, "create_connection", forbidden("open a connection"))
    monkeypatch.setattr(subprocess, "run", forbidden("start a process"))
    monkeypatch.setattr(subprocess, "Popen", forbidden("start a process"))
    for reader in ("read_json", "read_csv", "read_parquet"):
        monkeypatch.setattr(pandas, reader, forbidden("read a data file"))
    # The grader's own install has no geopandas (only the sandbox image does),
    # which already keeps it from reading a shapefile; trip it where it exists.
    try:
        import geopandas
    except ImportError:
        return
    monkeypatch.setattr(geopandas, "read_file", forbidden("read a data file"))


def _grade(submissions, root, mode):
    service = GradingService.from_rubric_path(RUBRIC, GraderSettings(execution_mode=mode))
    loaded = service.load_submissions(submissions)
    session = service.new_session(loaded.source)
    session.root = root / session.session_id
    return service.run(loaded.candidates, session=session, workdir_root=root / "work")


@pytest.fixture(scope="module")
def graded(submissions, tmp_path_factory):
    patcher = pytest.MonkeyPatch()
    try:
        _tripwire(patcher)
        session = _grade(submissions, tmp_path_factory.mktemp("graded"), MODE_DOCKER)
    finally:
        patcher.undo()
    return session


def _items(session, student):
    return {item.rubric_id: item for item in session.results[student].items}


# ---------------------------------------------------------------------------
# The rubric
# ---------------------------------------------------------------------------

def test_rubric_forbids_execution_and_splits_90_10():
    rubric = load_rubric(RUBRIC)
    assert rubric.never_executes
    assert rubric.total_points == 100
    points = {item.id: item.points for item in rubric.items}
    assert points["notebook_execution"] == 10
    assert sum(points[i] for i in PART1) == 90
    assert set(points) == PART1 | {"notebook_execution"}


# ---------------------------------------------------------------------------
# Never a live request, never a data file
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode", [MODE_LOCAL, MODE_DOCKER])
def test_grading_runs_nothing_and_reads_no_data(submissions, tmp_path, monkeypatch, mode):
    _tripwire(monkeypatch)
    session = _grade(submissions, tmp_path, mode)

    assert len(session.results) == 4
    for result in session.results.values():
        assert result.status == "graded", result.error
        assert result.execution.attempted is False
        assert result.execution.mode == MODE_NOT_EXECUTED
        assert not any(i.evidence.get("grader_error") for i in result.items)


# ---------------------------------------------------------------------------
# The grades the demo submissions earn
# ---------------------------------------------------------------------------

def test_a_complete_submission_earns_full_marks_without_review(graded):
    result = graded.results["student_complete"]
    assert result.total_score == 100
    assert not result.needs_review, result.review_reasons
    assert all(item.status == STATUS_PASS for item in result.items)
    items = _items(graded, "student_complete")
    assert "388 tracts" in items["census_income"].feedback
    assert "7,350 restaurants" in items["restaurants"].feedback


def test_the_usual_mistakes_are_named(graded):
    items = _items(graded, "student_mistakes")
    assert "negative placeholder" in items["census_income"].feedback
    assert items["census_income"].automatic_score == 17
    assert "merged with the income data" in items["census_tracts"].feedback
    restaurants = items["restaurants"]
    assert "Latitude is passed as x" in restaurants.feedback
    assert restaurants.automatic_score == 13
    plot = items["stars_income_plot"]
    assert "written answer" in plot.feedback and "title and axis labels" in plot.feedback
    assert graded.results["student_mistakes"].needs_review


def test_reading_the_full_yelp_dump_is_named_not_penalised(graded):
    restaurants = _items(graded, "student_mistakes")["restaurants"]
    assert "full Yelp dataset" in restaurants.feedback
    assert restaurants.evidence["reads_full_yelp_dataset"]
    clean = _items(graded, "student_complete")["restaurants"]
    assert "reads_full_yelp_dataset" not in clean.evidence


def test_a_step_is_graded_on_the_code_under_its_own_heading(graded):
    """The crashed notebook merges in 1.2 but never reaches 1.5."""
    items = _items(graded, "student_crashed")
    assert items["census_tracts"].automatic_score == 15
    merge = items["income_merge"]
    assert merge.automatic_score == 0
    assert "no code under the 1.5 heading" in merge.feedback
    assert merge.confidence < 0.8


def test_a_crash_partway_is_flagged(graded):
    items = _items(graded, "student_crashed")
    restaurants = items["restaurants"]
    assert "ValueError" in restaurants.feedback
    assert restaurants.confidence < 0.8
    assert items["stars_income_plot"].automatic_score == 0


def test_the_untouched_template_earns_almost_nothing(graded):
    result = graded.results["student_template"]
    assert result.total_score <= 5
    assert all(
        item.automatic_score == 0 for item in result.items
        if item.rubric_id != "notebook_execution"
    )
    assert result.needs_review


def test_an_answer_typed_into_the_template_cell_counts(submissions, tmp_path):
    import nbformat

    builder = _builder()
    nb = builder.good_notebook()
    nb.cells.pop()  # the separate answer cell
    question = next(
        c for c in nb.cells if c.cell_type == "markdown" and "### 1.6" in c.source
    )
    question.source += "\n\n" + builder.GOOD_ANSWER
    folder = tmp_path / "subs" / "student_inline"
    folder.mkdir(parents=True)
    nbformat.write(nb, str(folder / "assignment-5.ipynb"))
    session = _grade(tmp_path / "subs", tmp_path, MODE_LOCAL)
    plot = _items(session, "student_inline")["stars_income_plot"]
    assert plot.automatic_score == 15, plot.feedback
