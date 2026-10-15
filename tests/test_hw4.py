"""Assignment 4: graded without ever running the notebook.

The property these tests exist for is the one the assignment's design rests on:
**grading Assignment 4 never scrapes anything.** Its notebooks drive a browser
through Craigslist and download from OpenStreetMap and ArcGIS, so the grader
must not start a kernel, a container running the notebook, or a network
connection — in Docker mode or in local mode. The only thing that may run is
the three ``format_*`` functions, cut out on their own and called in the Docker
sandbox with ``--network none``.

So the first group of tests grades the demo submissions with every route to a
live request wired to fail: notebook execution, ``subprocess``, sockets. The
second group checks what the function extraction refuses to send. The rest pin
the grades the demo submissions earn, so a rubric edit that changes them is a
visible decision.
"""

from __future__ import annotations

import importlib.util
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from grader import function_runner, function_sandbox
from grader.executor import (
    DEFAULT_IMAGE,
    MODE_DOCKER,
    MODE_LOCAL,
    MODE_NOT_EXECUTED,
    ExecutionConfig,
    docker_image_exists,
)
from grader.function_sandbox import (
    STATUS_RAN,
    STATUS_SKIPPED,
    FunctionTestRun,
    extract_functions,
    run_isolated_functions,
)
from grader.models import STATUS_MANUAL_REVIEW, STATUS_PASS
from grader.rubric import load_rubric
from grader.service import GraderSettings, GradingService

from conftest import ROOT

RUBRIC = ROOT / "rubrics" / "hw4.yaml"
PART1 = {
    "district_polygon", "street_network", "network_edges", "crash_data",
    "crash_geodataframe", "trim_crashes", "reproject", "nearest_edges",
    "crash_counts", "merge_edges", "crash_index", "crash_index_histogram",
    "crash_index_map",
}
PART2 = {
    "selenium_driver", "soup", "listing_elements", "first_listing_fields",
    "format_functions", "scraping_loop", "price_histograms", "altair_scatter",
}
# Anything that would mean a notebook's scraping or downloading code was sent
# somewhere to run.
LIVE_MARKERS = ("webdriver", "craigslist", "driver.get", "osmnx", "graph_from_polygon",
                "read_file", "sleep(")


def _builder():
    spec = importlib.util.spec_from_file_location(
        "make_hw4_submissions", ROOT / "examples" / "make_hw4_submissions.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def submissions(tmp_path_factory) -> Path:
    return _builder().build_submissions(tmp_path_factory.mktemp("hw4") / "submissions")


class Tripwire:
    """Every way a grading run could reach a notebook kernel or the network."""

    def __init__(self, monkeypatch, allow_docker_functions: bool = False):
        self.commands: list[list[str]] = []
        self.payloads: list[str] = []
        self.allow_docker_functions = allow_docker_functions

        def no_execution(*args, **kwargs):
            raise AssertionError("Assignment 4 must never execute a notebook")

        def no_connect(*args, **kwargs):
            raise AssertionError(f"Assignment 4 grading opened a network connection: {args}")

        def fake_run(command, *args, **kwargs):
            self.commands.append(list(command))
            if not self.allow_docker_functions:
                raise AssertionError(f"Assignment 4 grading started a process: {command}")
            return self._fake_sandbox(command)

        monkeypatch.setattr("grader.service.execute_submission", no_execution)
        monkeypatch.setattr("grader.executor.execute_submission", no_execution)
        monkeypatch.setattr(socket.socket, "connect", no_connect)
        monkeypatch.setattr(socket, "create_connection", no_connect)
        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(subprocess, "Popen", no_execution)

    def _fake_sandbox(self, command):
        """Stand in for the container: the real runner, on the payload it was given.

        Only the demo submissions' own format_* functions run here, in-process —
        which is what the container would run, minus the container.
        """
        sandbox = Path(command[command.index("-v") + 1].split(":")[0])
        payload = sandbox / "payload.json"
        self.payloads.append(payload.read_text())
        argv = sys.argv
        sys.argv = ["runner", str(payload), str(sandbox / "results.json")]
        try:
            function_runner.main()
        finally:
            sys.argv = argv
        return subprocess.CompletedProcess(command, 0, "", "")


def _grade(submissions, root, mode):
    service = GradingService.from_rubric_path(RUBRIC, GraderSettings(execution_mode=mode))
    loaded = service.load_submissions(submissions)
    session = service.new_session(loaded.source)
    session.root = root / session.session_id
    return service.run(loaded.candidates, session=session, workdir_root=root / "work")


# ---------------------------------------------------------------------------
# The rubric
# ---------------------------------------------------------------------------

def test_rubric_forbids_execution_and_splits_55_35_10():
    rubric = load_rubric(RUBRIC)
    assert rubric.never_executes
    assert rubric.total_points == 100
    points = {item.id: item.points for item in rubric.items}
    assert points["notebook_execution"] == 10
    assert sum(points[i] for i in PART1) == 55
    assert sum(points[i] for i in PART2) == 35
    assert set(points) == PART1 | PART2 | {"notebook_execution"}


def test_other_assignments_still_execute():
    for name in ("hw1", "hw2", "hw3"):
        assert not load_rubric(ROOT / "rubrics" / f"{name}.yaml").never_executes


# ---------------------------------------------------------------------------
# Never a live request
# ---------------------------------------------------------------------------

def test_local_mode_starts_nothing_and_opens_no_connection(submissions, tmp_path, monkeypatch):
    """Local mode has a network, so nothing at all may run — not even the functions."""
    tripwire = Tripwire(monkeypatch)
    session = _grade(submissions, tmp_path, MODE_LOCAL)

    assert tripwire.commands == []
    assert len(session.results) == 4
    for result in session.results.values():
        assert result.status == "graded", result.error
        assert result.execution.attempted is False
        assert result.execution.mode == MODE_NOT_EXECUTED
        assert result.execution.executed_notebook_path is None
        assert "Notebook was never executed" not in result.review_reasons
        functions = next(i for i in result.items if i.rubric_id == "format_functions")
        assert functions.status == STATUS_MANUAL_REVIEW  # not called, so a TA checks


def test_docker_mode_runs_only_the_extracted_functions_without_network(
    submissions, tmp_path, monkeypatch
):
    tripwire = Tripwire(monkeypatch, allow_docker_functions=True)
    session = _grade(submissions, tmp_path, MODE_DOCKER)

    assert len(session.results) == 4
    # One sandbox call per submission, and every one of them is the function
    # runner in a container with no network — never the notebook runner.
    assert len(tripwire.commands) == 4
    for command in tripwire.commands:
        assert command[:2] == ["docker", "run"]
        assert command[command.index("--network") + 1] == "none"
        assert "--read-only" in command
        assert command[-3].endswith("_musa_functions.py")
        assert not any(part.endswith(".ipynb") for part in command)
        assert command[command.index("-v") + 1].split(":")[0].endswith("_musa_functions")
    # Nothing that scrapes or downloads was in what the container received.
    for payload in tripwire.payloads:
        for marker in LIVE_MARKERS:
            assert marker not in payload, marker
        assert set(json.loads(payload)["functions"]) <= {
            "format_bedrooms", "format_size", "format_price"
        }


def test_the_sandbox_directory_holds_only_the_payload_and_runner(tmp_path, monkeypatch):
    extracted = extract_functions(
        ["def format_size(s):\n    return float(s.replace('ft2', ''))"], ["format_size"]
    )
    calls = []

    def fake_run(command, *args, **kwargs):
        calls.append(command)
        sandbox = Path(command[command.index("-v") + 1].split(":")[0])
        assert sorted(p.name for p in sandbox.iterdir()) == ["_musa_functions.py", "payload.json"]
        return subprocess.CompletedProcess(command, 1, "", "boom")

    monkeypatch.setattr(function_sandbox.subprocess, "run", fake_run)
    run = run_isolated_functions(
        tmp_path, extracted,
        [{"id": "a", "function": "format_size", "args": ["850ft2"], "expected": 850}],
        ExecutionConfig(mode=MODE_DOCKER),
    )
    assert calls
    assert run.status == "error"
    # The expected value never leaves the host.
    payload = json.loads((tmp_path / "_musa_functions" / "payload.json").read_text())
    assert "expected" not in json.dumps(payload)


def test_local_mode_never_calls_the_functions(tmp_path):
    extracted = extract_functions(["def format_size(s):\n    return 1.0"], ["format_size"])
    run = run_isolated_functions(
        tmp_path, extracted, [{"id": "a", "function": "format_size", "args": ["1ft2"]}],
        ExecutionConfig(mode=MODE_LOCAL),
    )
    assert run.status == STATUS_SKIPPED
    assert not (tmp_path / "_musa_functions").exists()


# ---------------------------------------------------------------------------
# What extraction refuses to send
# ---------------------------------------------------------------------------

NOTEBOOK_CELLS = [
    "import re\nimport requests\nfrom selenium import webdriver\nimport numpy as np",
    "driver = webdriver.Chrome()\ndriver.get('https://philadelphia.craigslist.org')",
    "def format_bedrooms(s):\n    return int(s.replace('br', ''))",
    "x = 1\ndef format_size(s: str = 'x') -> float:\n    return float(s[:-3])\nprint(driver)",
]


def test_only_the_named_functions_and_safe_imports_are_extracted():
    extracted = extract_functions(NOTEBOOK_CELLS, ["format_bedrooms", "format_size"])
    assert set(extracted.functions) == {"format_bedrooms", "format_size"}
    assert extracted.imports == ["import re", "import numpy as np"]
    sent = json.dumps(extracted.to_dict())
    for forbidden in ("requests", "selenium", "webdriver", "driver", "x = 1", "print("):
        assert forbidden not in sent, forbidden
    # Annotations run at definition time, so they are stripped too.
    assert "->" not in extracted.functions["format_size"]
    assert ": str" not in extracted.functions["format_size"]


def test_definition_time_code_is_refused_or_stripped():
    cells = [
        "@register_with(driver.get('https://craigslist.org'))\n"
        "def format_price(s):\n    return float(s[1:])",
        "def format_size(s, page=driver.get('https://craigslist.org')):\n    return 1.0",
        "async def format_bedrooms(s):\n    return 1",
    ]
    extracted = extract_functions(cells, ["format_price", "format_size", "format_bedrooms"])
    assert "driver" not in extracted.functions["format_price"]  # decorator removed
    assert "format_size" in extracted.rejected  # a non-literal default cannot be stripped
    assert "format_bedrooms" in extracted.rejected
    assert set(extracted.functions) == {"format_price"}


def test_the_last_definition_wins_and_a_missing_one_is_reported():
    cells = [
        "def format_price(s):\n    return",
        "def format_price(s):\n    return float(s.strip('$').replace(',', ''))",
    ]
    extracted = extract_functions(cells, ["format_price", "format_size"])
    assert "replace" in extracted.functions["format_price"]
    assert extracted.cells["format_price"] == 2
    assert extracted.missing == ["format_size"]


def test_a_number_returned_as_text_does_not_match():
    assert function_sandbox.matches({"ok": True, "value": 2}, 2)
    assert function_sandbox.matches({"ok": True, "value": 2.0}, 2)
    assert not function_sandbox.matches({"ok": True, "value": "2"}, 2)
    assert not function_sandbox.matches({"ok": True, "value": None}, 2)
    assert not function_sandbox.matches({"ok": False, "error": "ValueError"}, 2)


# ---------------------------------------------------------------------------
# The grades the demo submissions earn
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def docker_graded(submissions, tmp_path_factory):
    """Docker mode, with the sandbox answered by the stand-in above."""
    patcher = pytest.MonkeyPatch()
    try:
        Tripwire(patcher, allow_docker_functions=True)
        session = _grade(submissions, tmp_path_factory.mktemp("graded"), MODE_DOCKER)
    finally:
        patcher.undo()
    return session


def _items(session, student):
    return {item.rubric_id: item for item in session.results[student].items}


def test_a_complete_submission_earns_full_marks_without_review(docker_graded):
    result = docker_graded.results["student_complete"]
    assert result.total_score == 100
    assert not result.needs_review, result.review_reasons
    assert all(item.status == STATUS_PASS for item in result.items)


def test_scraping_must_be_shown_not_loaded_from_a_csv(docker_graded):
    loop = _items(docker_graded, "student_csv_results")["scraping_loop"]
    assert loop.automatic_score == 0
    assert "CSV" in loop.feedback
    assert loop.evidence["results_read_from_csv_in_cells"]


def test_the_usual_mistakes_are_named(docker_graded):
    items = _items(docker_graded, "student_csv_results")
    assert "Latitude is passed as x" in items["crash_geodataframe"].feedback
    assert items["crash_geodataframe"].automatic_score == 2
    merge = items["merge_edges"]
    assert "left merge" in merge.feedback and "filled with zero" in merge.feedback
    # format_price chokes on "$1,500" and "$2,350"; the other two are fine.
    assert items["format_functions"].automatic_score == 7
    assert "interactive" in items["altair_scatter"].feedback
    assert docker_graded.results["student_csv_results"].needs_review


def test_the_template_scaffold_earns_nothing(docker_graded):
    result = docker_graded.results["student_template"]
    by_id = _items(docker_graded, "student_template")
    # The provided loop has `driver.get(url)` and `pd.concat(...)` in it.
    assert by_id["selenium_driver"].automatic_score == 0
    assert by_id["crash_data"].automatic_score == 0
    assert by_id["scraping_loop"].automatic_score == 0
    assert result.total_score <= 5
    assert result.needs_review


def test_a_crash_partway_is_flagged_not_just_zeroed(docker_graded):
    items = _items(docker_graded, "student_crashed")
    assert items["district_polygon"].automatic_score == 4
    trim = items["trim_crashes"]
    assert trim.confidence < 0.8
    assert "NameError" in trim.feedback


def test_unrun_functions_get_a_provisional_score_for_a_ta():
    from assignments.hw4 import _is_stub

    assert _is_stub("def f(s):\n    return")
    assert _is_stub("def f(s):\n    pass")
    assert not _is_stub("def f(s):\n    return int(s[:-2])")


# ---------------------------------------------------------------------------
# The real sandbox (needs the image)
# ---------------------------------------------------------------------------

@pytest.mark.docker
@pytest.mark.skipif(not docker_image_exists(DEFAULT_IMAGE), reason=f"{DEFAULT_IMAGE} is not built")
def test_the_real_sandbox_has_no_network_and_grades_the_functions(tmp_path):
    cells = [
        "import re",
        "def format_price(s):\n    return float(re.sub(r'[$,]', '', s))",
        "def format_size(s):\n"
        "    import urllib.request\n"
        "    urllib.request.urlopen('https://philadelphia.craigslist.org', timeout=5)\n"
        "    return 850.0",
    ]
    extracted = extract_functions(cells, ["format_price", "format_size"])
    run = run_isolated_functions(
        tmp_path, extracted,
        [{"id": "p", "function": "format_price", "args": ["$1,500"]},
         {"id": "s", "function": "format_size", "args": ["850ft2"]}],
        ExecutionConfig(mode=MODE_DOCKER, docker_image=DEFAULT_IMAGE),
    )
    assert run.status == STATUS_RAN, run.reason
    assert function_sandbox.matches(run.case("p"), 1500)
    reached = run.case("s")
    assert not reached["ok"]
    assert "URLError" in reached["error"]  # no name resolution, no route out


def test_function_test_run_reports_cases():
    run = FunctionTestRun(status=STATUS_RAN, report={"cases": [{"id": "a", "ok": True}]})
    assert run.case("a") == {"id": "a", "ok": True}
    assert run.case("b") is None
