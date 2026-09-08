"""Notebook instrumentation and execution."""

from __future__ import annotations

import nbformat
import pytest
from nbformat.v4 import new_code_cell, new_notebook, new_output

from grader.executor import (
    MODE_LOCAL,
    ExecutionConfig,
    build_probe_cells,
    execute_submission,
    instrument_notebook,
    strip_probe_cells,
)

PROBE_CONFIG = {
    "id_column_hints": ["zip"],
    "hidden_tests": [
        {
            "id": "pct",
            "selector": {"name_hints": ["percent", "increase"], "arity": 2},
            "cases": [{"label": "100 → 120", "args": [100, 120], "kwargs": {}}],
        }
    ],
}


def _write_notebook(path, sources):
    nbformat.write(new_notebook(cells=[new_code_cell(s) for s in sources]), str(path))
    return path


def test_probe_cells_are_tagged():
    cells = build_probe_cells({"out_dir": "/tmp"})
    assert len(cells) == 2
    assert all(cell.metadata["musa_probe"] for cell in cells)


def test_instrument_notebook_clears_stale_outputs(tmp_path):
    source = tmp_path / "notebook.ipynb"
    nb = new_notebook(cells=[new_code_cell("1 + 1")])
    nb.cells[0]["outputs"] = [new_output("stream", name="stdout", text="stale")]
    nb.cells[0]["execution_count"] = 7
    nbformat.write(nb, str(source))

    target = instrument_notebook(source, {"out_dir": "/tmp"}, tmp_path / "out.ipynb")
    result = nbformat.read(str(target), as_version=4)
    assert result.cells[0]["outputs"] == []
    assert result.cells[0]["execution_count"] is None
    assert sum(1 for c in result.cells if c.get("metadata", {}).get("musa_probe")) == 2


def test_strip_probe_cells(tmp_path):
    path = tmp_path / "nb.ipynb"
    nb = new_notebook(cells=[new_code_cell("1")] + build_probe_cells({"out_dir": "/tmp"}))
    nbformat.write(nb, str(path))
    strip_probe_cells(path)
    assert len(nbformat.read(str(path), as_version=4).cells) == 1


@pytest.mark.slow
def test_execute_success_returns_probe_payload(tmp_path):
    _write_notebook(
        tmp_path / "notebook.ipynb",
        [
            "import pandas as pd",
            "df = pd.DataFrame({'zipcode': ['19102', '19103'], 'value': [1, 2]})",
            "def percent_increase(a, b):\n    return (b - a) / a * 100",
            "answer = percent_increase(100, 120)",
        ],
    )
    config = ExecutionConfig(mode=MODE_LOCAL, cell_timeout_seconds=60, timeout_seconds=180)
    record, probe = execute_submission(tmp_path, PROBE_CONFIG, config)

    assert record.success is True
    assert record.error_cell is None
    assert probe is not None
    assert [d["name"] for d in probe["dataframes"]] == ["df"]
    assert probe["dataframes"][0]["id_columns"] == ["zipcode"]

    test = probe["hidden_tests"][0]
    assert test["found"] is True
    assert test["function_name"] == "percent_increase"
    assert test["calls"][0]["value"] == 20.0


@pytest.mark.slow
def test_execution_error_still_grades_what_ran(tmp_path):
    """design.md §19: preserve the traceback, keep grading, never auto-zero."""
    _write_notebook(
        tmp_path / "notebook.ipynb",
        [
            "import pandas as pd",
            "good = pd.DataFrame({'zipcode': ['19102'], 'value': [1]})",
            "raise ValueError('boom')",
            "later = 5",
        ],
    )
    config = ExecutionConfig(mode=MODE_LOCAL, cell_timeout_seconds=60, timeout_seconds=180)
    record, probe = execute_submission(tmp_path, PROBE_CONFIG, config)

    assert record.success is False
    assert record.error_cell == 3
    assert "ValueError" in (record.error_message or "")
    assert "boom" in record.traceback
    # The probe still ran, so objects created before the failure are gradable.
    assert probe is not None
    assert [d["name"] for d in probe["dataframes"]] == ["good"]


@pytest.mark.slow
def test_timeout_is_reported(tmp_path):
    _write_notebook(tmp_path / "notebook.ipynb", ["import time\ntime.sleep(30)"])
    config = ExecutionConfig(mode=MODE_LOCAL, cell_timeout_seconds=2, timeout_seconds=2)
    record, _ = execute_submission(tmp_path, {"hidden_tests": []}, config)
    assert record.success is False
    assert record.timeout is True


def test_missing_notebook_is_not_an_error(tmp_path):
    record, probe = execute_submission(
        tmp_path, {"hidden_tests": []}, ExecutionConfig(mode=MODE_LOCAL)
    )
    assert record.attempted is False
    assert probe is None
