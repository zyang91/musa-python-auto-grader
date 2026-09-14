"""Regression tests for patterns found grading a real Assignment 1 class.

Every case here was a student whose work was right (or right enough) but whom
the grader scored as if it were missing: a split that only survived as a
GroupBy, a True/False Center City column, a function that returns a table,
variable names like `not_center_city_pct_change`, a notebook reading
`../data/...`, data loaded from Zillow's URL in an offline container, and a
submission handed in as a ZIP inside the Canvas export.
"""

from __future__ import annotations

import zipfile

import nbformat
import pandas as pd
import pytest
from nbformat.v4 import new_code_cell, new_notebook

from assignments.base import GradingContext, get_grader
from grader.discovery import discover_submissions, prepare_workdir
from grader.models import STATUS_MANUAL_REVIEW, STATUS_NOT_FOUND, STATUS_PASS, ExecutionRecord
from grader.notebook import NotebookAnalysis

from conftest import CENTER_CITY, OUTSIDE, PHILLY_ZIPS, _tidy_frame

PROBE_SOURCE = open("grader/probe_runtime.py", encoding="utf-8").read()


def _probe():
    namespace: dict = {}
    exec(PROBE_SOURCE, namespace)
    return namespace


def _write_notebook(path, sources=("import pandas as pd",)):
    path.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(new_notebook(cells=[new_code_cell(s) for s in sources]), str(path))
    return path


def _grade(rubric, rubric_id, probe):
    grader = get_grader(rubric)
    ctx = GradingContext(
        student_id="s",
        rubric=rubric,
        analysis=NotebookAnalysis(path="n.ipynb", imports={"pandas"}, read_calls=["read_csv"]),
        execution=ExecutionRecord(success=True, attempted=True, mode="local"),
        probe=probe,
    )
    return getattr(grader, f"check_{rubric_id}")(ctx, rubric.item(rubric_id))


# ---------------------------------------------------------------------------
# Canvas exports
# ---------------------------------------------------------------------------

def test_a_zip_inside_the_canvas_export_is_graded_not_dropped(tmp_path):
    root = tmp_path / "export"
    _write_notebook(root / "doejane_111_222_assignment-1.ipynb")
    nested = tmp_path / "inner.zip"
    with zipfile.ZipFile(nested, "w") as archive:
        archive.writestr("public/assignments/hw1.ipynb", nbformat.writes(new_notebook()))
        archive.writestr("public/assignments/.ipynb_checkpoints/hw1-checkpoint.ipynb", "{}")
        archive.writestr("public/data/zillow.csv", "RegionName\n19102\n")
    (root / "leesam_333_444_Lee_Assignment_1.zip").write_bytes(nested.read_bytes())

    candidates = {c.student_id: c for c in discover_submissions(root)}
    assert set(candidates) == {"doejane", "leesam"}
    nested = candidates["leesam"]
    assert nested.notebook_path.name == "hw1.ipynb"
    assert any("ZIP archive" in w for w in nested.warnings)


def test_a_students_uploaded_file_stays_with_that_student(tmp_path):
    root = tmp_path / "export"
    _write_notebook(root / "doejane_111_222_assignment-1.ipynb")
    _write_notebook(root / "smithjo_555_666_assignment-1.ipynb")
    (root / "doejane_111_222_Zip_zhvi_assignment-1-data.csv").write_text("a\n1\n")

    candidates = {c.student_id: c for c in discover_submissions(root)}
    # Canvas's prefix is removed, restoring the name the student's code uses.
    assert [p.name for p in candidates["doejane"].data_files] == ["Zip_zhvi_assignment-1-data.csv"]
    assert candidates["smithjo"].data_files == []


def test_discovery_never_writes_into_the_submissions_folder(tmp_path):
    root = tmp_path / "export"
    _write_notebook(root / "doejane_111_222_assignment-1.ipynb")
    (root / "doejane_111_222_data.csv").write_text("a\n1\n")
    before = sorted(p.name for p in root.rglob("*"))
    discover_submissions(root)
    assert sorted(p.name for p in root.rglob("*")) == before


# ---------------------------------------------------------------------------
# Paths that climb out of the notebook's folder
# ---------------------------------------------------------------------------

def test_a_lone_notebook_reading_parent_data_finds_the_file(tmp_path):
    submission = tmp_path / "student_001"
    _write_notebook(submission / "hw1.ipynb")
    data = tmp_path / "Zip_zhvi.csv"
    data.write_text("a\n1\n")
    candidate = [c for c in discover_submissions(tmp_path) if c.student_id == "student_001"][0]
    run_dir = prepare_workdir(
        candidate, tmp_path / "work", shared_data=[data],
        referenced_paths=["../data/Zip_zhvi.csv"],
    )
    assert (run_dir / "notebook.ipynb").exists()
    assert (run_dir / ".." / "data" / "Zip_zhvi.csv").resolve().exists()
    assert candidate.run_subdir  # nested one level so `..` stays inside the workdir


def test_a_nested_notebook_keeps_its_submission_layout(tmp_path):
    submission = tmp_path / "subs" / "student_001"
    _write_notebook(submission / "public" / "assignments" / "hw1.ipynb")
    (submission / "public" / "data").mkdir(parents=True)
    (submission / "public" / "data" / "own.csv").write_text("a\n1\n")
    _write_notebook(tmp_path / "subs" / "student_002" / "hw1.ipynb")

    candidate = [c for c in discover_submissions(tmp_path / "subs")
                 if c.student_id == "student_001"][0]
    run_dir = prepare_workdir(candidate, tmp_path / "work")
    assert candidate.run_subdir == "public/assignments"
    assert (run_dir / ".." / "data" / "own.csv").resolve().exists()


def test_a_path_escaping_the_workdir_is_still_refused(tmp_path):
    from grader.discovery import place_shared_data

    data = tmp_path / "x.csv"
    data.write_text("a\n")
    workdir = tmp_path / "work"
    workdir.mkdir()
    report = place_shared_data(workdir, [data], referenced_paths=["../../../../../x.csv"])
    assert report["skipped"] == ["../../../../../x.csv"]


# ---------------------------------------------------------------------------
# The in-kernel probe
# ---------------------------------------------------------------------------

def test_an_arity_only_match_is_not_graded_as_the_function():
    probe = _probe()

    def looks_like_a_date(column_name):
        return column_name.startswith("20")

    namespace = {"looks_like_a_date": looks_like_a_date}
    functions = probe["_musa_profile_functions"](namespace)
    func, _, _ = probe["_musa_select_function"](
        namespace, functions, {"name_hints": ["percent", "increase", "calculate"], "arity": 1}
    )
    assert func is None


def test_a_split_that_survives_only_as_a_groupby_is_profiled():
    probe = _probe()
    frame = pd.DataFrame({"RegionName": [19102, 19103], "ZHVI": [1.0, 2.0]})
    payload = probe["_musa_probe_main"](
        {"inside_center": frame.groupby("RegionName")}, {"id_column_hints": ["regionname"]}
    )
    assert [d["name"] for d in payload["dataframes"]] == ["inside_center"]
    assert payload["dataframes"][0]["from_groupby"] is True


def test_a_series_grouped_by_a_flag_reports_per_flag_means():
    probe = _probe()
    index = pd.MultiIndex.from_tuples(
        [(True, 19102), (True, 19103), (False, 19120)], names=["cc", "RegionName"]
    )
    res = pd.Series([6.0, 8.0, 20.0], index=index)
    payload = probe["_musa_probe_main"]({"res": res}, {})
    assert payload["series"][0]["bool_level_means"] == {"False": 20.0, "True": 7.0}


GROUP_SPEC = {
    "id": "percent_increase_function",
    "type": "group_frame",
    "selector": {"name_hints": ["percent", "increase"], "arity": 1},
    "frame": {"id_column_hints": ["regionname"], "date_column_hints": ["date"],
              "value_column_hints": ["zhvi"], "default_id_column": "RegionName",
              "default_date_column": "Date", "default_value_column": "ZHVI"},
    "cases": [{"label": "100 → 150", "anchors": [["2019-01-31", 80], ["2020-03-31", 100],
                                                 ["2022-03-31", 150], ["2023-12-31", 200]]}],
}


def _run_function(func):
    probe = _probe()
    # The probe only grades functions the notebook itself defined (__main__).
    func.__module__ = "__main__"
    namespace = {"calculate_percent_increase": func}
    functions = probe["_musa_profile_functions"](namespace)
    return probe["_musa_run_hidden_tests"](namespace, functions, [GROUP_SPEC], pd)[0]["calls"][0]


def test_a_function_returning_a_table_is_readable():
    def calculate_percent_increase(group_df):
        early = group_df[group_df["Date"] == "2020-03-31"][["RegionName", "ZHVI"]]
        late = group_df[group_df["Date"] == "2022-03-31"][["RegionName", "ZHVI"]]
        merged = pd.merge(early, late, on="RegionName", suffixes=("_2020", "_2022"))
        merged["Percent_Increase"] = (merged["ZHVI_2022"] / merged["ZHVI_2020"] - 1) * 100
        return merged

    call = _run_function(calculate_percent_increase)
    assert call["ok"] and 50.0 in call["table"]["numbers"]


def test_a_whole_frame_function_is_retried_with_several_zip_codes():
    def calculate_percent_increase(group_df):
        march_2020 = group_df.loc[group_df["Date"] == "2020-03-31"].squeeze()
        march_2022 = group_df.loc[group_df["Date"] == "2022-03-31"].squeeze()
        march_2020 = march_2020.set_index("RegionName")  # fails on a one-ZIP group
        march_2022 = march_2022.set_index("RegionName")
        return 100 * (march_2022["ZHVI"] / march_2020["ZHVI"] - 1)

    call = _run_function(calculate_percent_increase)
    assert call["ok"]
    assert call["schema_used"].endswith("_multi_group")
    assert call["table"]["numbers"] == [50.0, 50.0]


# ---------------------------------------------------------------------------
# HW1 checks on those payloads
# ---------------------------------------------------------------------------

def test_function_table_and_whole_frame_answers_pass(rubric, probe_payload):
    payload = probe_payload()
    for call, expected in zip(payload["hidden_tests"][0]["calls"], [50.0, -50.0, 0.0]):
        call.update({"value": "<DataFrame>", "value_type": "Series",
                     "table": {"shape": [2, 1], "numbers": [expected, expected]},
                     "schema_used": "student_schema_multi_group"})
    result = _grade(rubric, "percent_increase_function", payload)
    assert result.status == STATUS_PASS
    assert result.automatic_score == 20
    assert "several ZIP codes" in result.feedback


@pytest.mark.parametrize(
    "center_name, outside_name",
    [
        ("center_city_pct_change", "not_center_city_pct_change"),
        ("Average_Center_city_result", "Average_Not_Center_city_result"),
        ("avg_incity", "avg_outcity"),
        ("mean_df_in_center", "mean_df_out_center"),
        ("inner_donut_effect", "outer_donut_effect"),
        ("cc_avg", "non_cc_avg"),
    ],
)
def test_real_variable_names_are_assigned_to_the_right_group(
    rubric, probe_payload, center_name, outside_name
):
    payload = probe_payload()
    payload["series"] = []
    payload["scalars"] = [
        {"name": "ratio", "type": "float", "value": 2.97},
        {"name": center_name, "type": "float", "value": 6.08},
        {"name": outside_name, "type": "float", "value": 18.07},
    ]
    result = _grade(rubric, "donut_effect_comparison", payload)
    assert result.status == STATUS_PASS, result.feedback
    assert result.evidence["center_city_value"] == 6.08
    assert result.evidence["outside_value"] == 18.07


def test_comparison_read_from_result_tables(rubric, probe_payload):
    payload = probe_payload()
    payload["series"], payload["scalars"] = [], []
    for name, mean in (("CENTER_CITY_INCREASE", 6.1), ("OUTSIDE_CENTER_CITY_INCREASE", 18.1)):
        payload["dataframes"].append({
            "name": name, "rows": 9, "n_columns": 4,
            "columns": ["RegionName", "ZHVI_2020", "ZHVI_2022", "Percent_Increase"],
            "numeric_summary": {"ZHVI_2020": {"mean": 300000.0},
                                "Percent_Increase": {"mean": mean}},
            "value_samples": {}, "nunique": {}, "id_columns": [],
            "boolean_group_values": {},
        })
    result = _grade(rubric, "donut_effect_comparison", payload)
    assert result.status == STATUS_PASS, result.feedback
    assert result.evidence["center_city_value"] == 6.1


def test_comparison_read_from_a_flag_grouped_series(rubric, probe_payload):
    payload = probe_payload()
    payload["scalars"] = []
    payload["series"] = [{"name": "res", "numeric_summary": {"mean": 12.0, "count": 46},
                          "bool_level_means": {"True": 6.0, "False": 18.0}}]
    payload["dataframes"][2]["boolean_group_values"] = {"cc": {"RegionName": CENTER_CITY}}
    result = _grade(rubric, "donut_effect_comparison", payload)
    assert result.status == STATUS_PASS, result.feedback
    assert result.evidence["center_city_value"] == 6.0


def test_a_flag_column_split_passes(rubric, probe_payload):
    payload = probe_payload()
    payload["dataframes"] = payload["dataframes"][:3]  # no separate split frames
    payload["dataframes"][2]["boolean_group_values"] = {"cc": {"RegionName": CENTER_CITY}}
    result = _grade(rubric, "center_city_split", payload)
    assert result.status == STATUS_PASS, result.feedback
    assert result.evidence["flag_column"]["column"] == "cc"


def test_split_is_not_penalised_again_for_an_earlier_subset_mistake(rubric, probe_payload):
    """Philadelphia, MS rows cost points in the subset item, not twice."""
    leftovers = ["39350", "39365"]
    payload = probe_payload()
    for frame in payload["dataframes"][1:3]:
        frame["value_samples"]["RegionName"] = list(frame["value_samples"]["RegionName"]) + leftovers
    payload["dataframes"][4] = _tidy_frame("outside_center_city", OUTSIDE + leftovers)
    result = _grade(rubric, "center_city_split", payload)
    assert result.status == STATUS_PASS, result.feedback


# ---------------------------------------------------------------------------
# Offline execution
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_data_read_from_a_url_uses_the_supplied_copy_offline(tmp_path):
    from grader.executor import MODE_LOCAL, ExecutionConfig, execute_submission

    workdir = tmp_path / "work"
    (workdir / "data").mkdir(parents=True)
    (workdir / "data" / "Zip_zhvi.csv").write_text("RegionName,ZHVI\n19102,1\n")
    _write_notebook(workdir / "notebook.ipynb", [
        "import pandas as pd",
        "df = pd.read_csv('https://files.example.invalid/research/Zip_zhvi.csv')",
        "rows = len(df)",
    ])
    record, probe = execute_submission(
        workdir,
        {"hidden_tests": [], "url_redirects": {"Zip_zhvi.csv": "data/Zip_zhvi.csv"}},
        ExecutionConfig(mode=MODE_LOCAL, cell_timeout_seconds=60, timeout_seconds=180),
    )
    assert record.success, record.error_message
    assert record.error_cell is None
    assert {"name": "rows", "type": "int", "value": 1} in probe["scalars"]


def test_a_correct_function_with_an_unhelpful_name_is_found_by_behaviour():
    def percInc(group_df):
        start = group_df.loc[group_df["Date"] == "2020-03-31", "ZHVI"].squeeze()
        end = group_df.loc[group_df["Date"] == "2022-03-31", "ZHVI"].squeeze()
        return (end - start) / start * 100

    def looks_like_a_date(column_name):
        return column_name.startswith("20")

    probe = _probe()
    for func in (looks_like_a_date, percInc):
        func.__module__ = "__main__"
    namespace = {"looks_like_a_date": looks_like_a_date, "percInc": percInc}
    functions = probe["_musa_profile_functions"](namespace)
    entry = probe["_musa_run_hidden_tests"](namespace, functions, [GROUP_SPEC], pd)[0]
    assert entry["function_name"] == "percInc"
    assert entry["selected_by"] == "behaviour"
    assert entry["calls"][0]["value"] == 50.0


def test_a_helper_that_only_raises_is_still_not_graded():
    def looks_like_a_date(column_name):
        return column_name.startswith("20")

    looks_like_a_date.__module__ = "__main__"
    probe = _probe()
    namespace = {"looks_like_a_date": looks_like_a_date}
    functions = probe["_musa_profile_functions"](namespace)
    entry = probe["_musa_run_hidden_tests"](namespace, functions, [GROUP_SPEC], pd)[0]
    assert entry["found"] is False


@pytest.mark.parametrize("columns", [
    [f"2020-{m:02d}-28" for m in range(1, 13)] * 3,
    [f"{m}/28/2020" for m in range(1, 13)] * 3,
    [f"{m}/28/20" for m in range(1, 13)] * 3,
])
def test_excel_resaved_date_columns_count_as_a_wide_zhvi_table(rubric, probe_payload, columns):
    """Excel turns 2020-03-31 into 3/31/2020; the file is still the right data."""
    payload = probe_payload()
    payload["dataframes"][0]["columns"] = ["RegionName", "City", "State"] + columns
    result = _grade(rubric, "data_loading", payload)
    assert result.status == STATUS_PASS, result.feedback
