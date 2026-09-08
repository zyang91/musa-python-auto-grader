"""Assignment 1 rubric checks.

The theme of these tests is that grading must not depend on the vintage of the
student's Zillow download: the checks are given payloads with different sizes and
must still reach the same verdicts.
"""

from __future__ import annotations

import pytest

from assignments.base import GradingContext, get_grader
from grader.models import (
    STATUS_EXECUTION_ERROR,
    STATUS_FAIL,
    STATUS_MANUAL_REVIEW,
    STATUS_NOT_FOUND,
    STATUS_PARTIAL,
    STATUS_PASS,
    ExecutionRecord,
)
from grader.notebook import NotebookAnalysis

from conftest import FUNCTION_SOURCE, TEMPLATE_STUB_SOURCE


def _analysis(**overrides) -> NotebookAnalysis:
    analysis = NotebookAnalysis(
        path="assignment-1.ipynb",
        n_code_cells=8,
        imports={"pandas"},
        read_calls=["read_csv"],
        referenced_files=["data/zillow_zhvi.csv"],
        functions=[{"name": "calculate_percent_increase", "params": ["group_df"],
                    "arity": 1, "source": FUNCTION_SOURCE, "has_docstring": True,
                    "lineno": 1}],
    )
    for key, value in overrides.items():
        setattr(analysis, key, value)
    return analysis


def make_context(rubric, probe=None, analysis=None, execution=None) -> GradingContext:
    return GradingContext(
        student_id="student_test",
        rubric=rubric,
        analysis=analysis or _analysis(),
        execution=execution or ExecutionRecord(success=True, attempted=True,
                                               execution_time_seconds=2.0, mode="local"),
        probe=probe,
    )


def grade_item(rubric, rubric_id, **kwargs):
    grader = get_grader(rubric)
    check = getattr(grader, f"check_{rubric_id}")
    return check(make_context(rubric, **kwargs), rubric.item(rubric_id))


def shrink(payload, keep_zips, n_dates):
    """Rewrite a payload as if the student had a smaller, older Zillow file."""
    for frame in payload["dataframes"]:
        samples = frame["value_samples"].get("RegionName")
        if samples is None:
            continue
        # Only the Philadelphia ZIPs shrink; the raw file keeps its other cities.
        kept = [
            z for z in samples
            if not str(z).zfill(5).startswith("191") or str(z).zfill(5) in keep_zips
        ]
        frame["value_samples"]["RegionName"] = kept
        frame["nunique"]["RegionName"] = len(kept)
        if "Date" in frame["nunique"]:
            frame["nunique"]["Date"] = n_dates
            frame["rows"] = len(kept) * n_dates
        else:
            frame["rows"] = len(kept)
    return payload


# ---------------------------------------------------------------------------
# Hidden tests stay hidden
# ---------------------------------------------------------------------------

def test_hidden_test_specs_carry_no_expected_values(rubric):
    specs = get_grader(rubric).hidden_test_specs()
    assert specs and specs[0]["type"] == "group_frame"
    blob = repr(specs)
    assert "expected" not in blob
    assert "credit_ratio" not in blob
    assert specs[0]["cases"][0]["anchors"][0] == ["2019-01-31", 80]


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def test_execution_pass(rubric):
    assert grade_item(rubric, "notebook_execution").status == STATUS_PASS


def test_execution_failure_gives_partial_credit_not_zero(rubric):
    execution = ExecutionRecord(success=False, attempted=True, error_cell=7,
                                error_message="KeyError: 'Zipcode'")
    result = grade_item(rubric, "notebook_execution", execution=execution)
    assert result.status == STATUS_EXECUTION_ERROR
    assert 0 < result.automatic_score < 10


# ---------------------------------------------------------------------------
# 1. Load the data
# ---------------------------------------------------------------------------

def test_data_loading_pass(rubric, probe_payload):
    assert grade_item(rubric, "data_loading", probe=probe_payload()).status == STATUS_PASS


def test_absolute_path_is_penalised(rubric, probe_payload):
    analysis = _analysis(absolute_paths=["/Users/student/Desktop/zillow_zhvi.csv"])
    result = grade_item(rubric, "data_loading", probe=probe_payload(), analysis=analysis)
    assert result.status == STATUS_PARTIAL
    assert result.automatic_score == 6
    assert "relative" in result.feedback


def test_unfilled_template_scores_nothing_for_loading(rubric, probe_payload):
    payload = probe_payload()
    payload["dataframes"] = []
    analysis = _analysis(imports=set(), read_calls=[], referenced_files=[])
    result = grade_item(rubric, "data_loading", probe=payload, analysis=analysis)
    assert result.status == STATUS_FAIL
    assert result.automatic_score == 0


# ---------------------------------------------------------------------------
# 2. Trim to Philadelphia
# ---------------------------------------------------------------------------

def test_philadelphia_subset_pass(rubric, probe_payload):
    result = grade_item(rubric, "philadelphia_subset", probe=probe_payload())
    assert result.status == STATUS_PASS
    assert result.confidence >= 0.98


def test_philadelphia_subset_is_not_graded_on_zip_count(rubric, probe_payload):
    """A smaller Zillow vintage is not a mistake."""
    from conftest import CENTER_CITY, PHILLY_ZIPS

    keep = set(PHILLY_ZIPS[:20]) | set(CENTER_CITY)
    result = grade_item(
        rubric, "philadelphia_subset", probe=shrink(probe_payload(), keep, 40)
    )
    assert result.status == STATUS_PASS


def test_leftover_other_cities_are_caught(rubric, probe_payload):
    payload = probe_payload()
    payload["dataframes"][1]["value_samples"]["City"] = ["Philadelphia", "Camden"]
    result = grade_item(rubric, "philadelphia_subset", probe=payload)
    assert result.status == STATUS_PARTIAL
    assert "Camden" in result.evidence["unexpected_cities"]


def test_region_id_is_not_mistaken_for_a_zip_code(rubric, probe_payload):
    """RegionID values are five digits too; only ZIP columns may supply ZIPs."""
    payload = probe_payload()
    for frame in payload["dataframes"]:
        frame["value_samples"]["RegionID"] = [61000 + n for n in range(20)]
    result = grade_item(rubric, "philadelphia_subset", probe=payload)
    assert result.status == STATUS_PASS
    assert result.evidence["non_philadelphia_zips"] == []


def test_missing_subset_is_flagged_not_zeroed_silently(rubric, probe_payload):
    payload = probe_payload()
    payload["dataframes"] = []
    result = grade_item(rubric, "philadelphia_subset", probe=payload)
    assert result.status == STATUS_NOT_FOUND
    assert result.confidence < 0.8


# ---------------------------------------------------------------------------
# 3. Melt into tidy format
# ---------------------------------------------------------------------------

def test_tidy_transformation_pass(rubric, probe_payload):
    result = grade_item(rubric, "tidy_transformation", probe=probe_payload())
    assert result.status == STATUS_PASS
    assert result.evidence["detected_roles"]["value"] == "ZHVI"


def test_melt_is_checked_against_the_students_own_grid(rubric, probe_payload):
    """Row count is graded relative to their own ZIPs x dates, not a constant."""
    from conftest import CENTER_CITY, PHILLY_ZIPS

    keep = set(PHILLY_ZIPS[:20]) | set(CENTER_CITY)
    payload = shrink(probe_payload(), keep, 40)
    result = grade_item(rubric, "tidy_transformation", probe=payload)
    assert result.status == STATUS_PASS
    assert result.evidence["rows"] == result.evidence["expected_rows_from_this_students_data"]


def test_an_incomplete_melt_is_caught(rubric, probe_payload):
    payload = probe_payload()
    payload["dataframes"] = payload["dataframes"][:3]  # wide frames + one tidy frame
    payload["dataframes"][2]["rows"] = 2000  # far from this student's 46 x 102 grid
    result = grade_item(rubric, "tidy_transformation", probe=payload)
    assert result.status == STATUS_PARTIAL
    assert "implies" in result.feedback


def test_wrong_value_column_name_costs_points(rubric, probe_payload):
    payload = probe_payload()
    for frame in payload["dataframes"]:
        if "ZHVI" in frame["columns"]:
            frame["columns"] = ["RegionName", "Date", "value"]
            frame["numeric_summary"] = {"value": {"min": 1, "max": 2}}
            frame["nunique"]["value"] = frame["rows"]
    result = grade_item(rubric, "tidy_transformation", probe=payload)
    assert result.status == STATUS_PARTIAL
    assert result.automatic_score == 15  # 20 - 25%
    assert "ZHVI" in result.feedback


def test_no_tidy_frame(rubric, probe_payload):
    payload = probe_payload()
    payload["dataframes"] = payload["dataframes"][:2]  # wide frames only
    result = grade_item(rubric, "tidy_transformation", probe=payload)
    assert result.status == STATUS_NOT_FOUND


# ---------------------------------------------------------------------------
# 4. Split Center City from the rest
# ---------------------------------------------------------------------------

def test_center_city_split_pass(rubric, probe_payload):
    result = grade_item(rubric, "center_city_split", probe=probe_payload())
    assert result.status == STATUS_PASS
    assert len(result.evidence["expected_center_city_zips"]) == 9


def test_split_expectations_follow_the_students_own_zips(rubric, probe_payload):
    """A ZIP the student's file does not contain cannot be required of them."""
    from conftest import CENTER_CITY, PHILLY_ZIPS

    keep = set(PHILLY_ZIPS) | set(CENTER_CITY)
    keep.discard("19109")
    payload = shrink(probe_payload(), keep, 102)
    result = grade_item(rubric, "center_city_split", probe=payload)
    assert "19109" not in result.evidence["expected_center_city_zips"]
    assert result.status == STATUS_PASS


def test_incomplete_center_city_list_is_partial(rubric, probe_payload):
    payload = probe_payload()
    short_list = ["19102", "19103", "19106", "19107"]
    for frame in payload["dataframes"]:
        if frame["name"] == "center_city":
            frame["value_samples"]["RegionName"] = short_list
            frame["nunique"]["RegionName"] = len(short_list)
    result = grade_item(rubric, "center_city_split", probe=payload)
    assert result.status == STATUS_PARTIAL
    assert "19109" in result.feedback


def test_unsplit_data_is_not_accepted_as_either_half(rubric, probe_payload):
    payload = probe_payload()
    payload["dataframes"] = payload["dataframes"][:3]  # no split frames at all
    result = grade_item(rubric, "center_city_split", probe=payload)
    assert result.status == STATUS_FAIL
    assert result.automatic_score == 0
    assert result.confidence < 0.8


# ---------------------------------------------------------------------------
# 5. The percent increase function
# ---------------------------------------------------------------------------

def test_function_all_tests_pass(rubric, probe_payload):
    result = grade_item(rubric, "percent_increase_function", probe=probe_payload())
    assert result.status == STATUS_PASS
    assert result.evidence["tests_passed"] == 3


def test_unfilled_template_function_is_recognised(rubric, probe_payload):
    payload = probe_payload()
    entry = payload["hidden_tests"][0]
    entry["source"] = TEMPLATE_STUB_SOURCE
    for call in entry["calls"]:
        call["value"] = None
    result = grade_item(rubric, "percent_increase_function", probe=payload)
    assert result.status == STATUS_FAIL
    assert result.automatic_score == 0
    assert "unfilled" in result.feedback


def test_fraction_units_get_partial_credit(rubric, probe_payload):
    payload = probe_payload()
    for call, value in zip(payload["hidden_tests"][0]["calls"], [0.5, -0.5, 0.0]):
        call["value"] = value
    result = grade_item(rubric, "percent_increase_function", probe=payload)
    assert result.status == STATUS_PARTIAL
    assert result.automatic_score == pytest.approx(12.0)  # 20 * 0.6
    assert "fraction" in result.feedback


def test_first_and_last_row_implementation_is_named(rubric, probe_payload):
    """The anchors imply a different answer for a first/last implementation."""
    payload = probe_payload()
    for call, value in zip(payload["hidden_tests"][0]["calls"], [150.0, -64.0, 100.0]):
        call["value"] = value
    result = grade_item(rubric, "percent_increase_function", probe=payload)
    assert result.status == STATUS_PARTIAL
    assert result.automatic_score == pytest.approx(10.0)  # 20 * 0.5
    assert "first and last rows" in result.feedback


def test_function_that_raises_is_sent_to_review(rubric, probe_payload):
    payload = probe_payload()
    for call in payload["hidden_tests"][0]["calls"]:
        call.update({"ok": False, "value": None, "error": "KeyError: 'Date'"})
    result = grade_item(rubric, "percent_increase_function", probe=payload)
    assert result.status == STATUS_MANUAL_REVIEW
    assert result.confidence < 0.8


def test_ambiguous_function_lowers_confidence(rubric, probe_payload):
    payload = probe_payload()
    payload["hidden_tests"][0]["ambiguous"] = True
    result = grade_item(rubric, "percent_increase_function", probe=payload)
    assert result.confidence == 0.75


def test_missing_function(rubric, probe_payload):
    payload = probe_payload()
    payload["hidden_tests"][0] = {"id": "percent_increase_function", "found": False,
                                  "candidates": [], "calls": []}
    result = grade_item(rubric, "percent_increase_function", probe=payload,
                        analysis=_analysis(functions=[]))
    assert result.status == STATUS_NOT_FOUND


# ---------------------------------------------------------------------------
# 6. The comparison
# ---------------------------------------------------------------------------

def test_donut_effect_pass(rubric, probe_payload):
    result = grade_item(rubric, "donut_effect_comparison", probe=probe_payload())
    assert result.status == STATUS_PASS
    assert result.evidence["center_city_value"] == 8.2
    assert result.evidence["outside_value"] == 26.8


def test_values_are_not_compared_against_expected_numbers(rubric, probe_payload):
    """Any pair in the right direction is accepted, whatever the data."""
    payload = probe_payload()
    payload["scalars"] = [
        {"name": "center_city_avg", "type": "float", "value": 61.4},
        {"name": "outside_avg", "type": "float", "value": 88.9},
    ]
    payload["series"] = []
    assert grade_item(rubric, "donut_effect_comparison", probe=payload).status == STATUS_PASS


def test_reversed_direction_is_flagged(rubric, probe_payload):
    payload = probe_payload()
    payload["scalars"] = [
        {"name": "center_city_avg", "type": "float", "value": 30.0},
        {"name": "outside_avg", "type": "float", "value": 10.0},
    ]
    payload["series"] = []
    result = grade_item(rubric, "donut_effect_comparison", probe=payload)
    assert result.status == STATUS_PARTIAL
    assert "Donut Effect" in result.feedback


def test_non_cc_naming_is_assigned_to_the_outside_group(rubric, probe_payload):
    payload = probe_payload()
    payload["scalars"] = [
        {"name": "cc_avg", "type": "float", "value": 8.0},
        {"name": "non_cc_avg", "type": "float", "value": 27.0},
    ]
    payload["series"] = []
    result = grade_item(rubric, "donut_effect_comparison", probe=payload)
    assert result.evidence["center_city_value"] == 8.0
    assert result.evidence["outside_value"] == 27.0


def test_series_means_are_used_when_no_scalar_was_assigned(rubric, probe_payload):
    payload = probe_payload()
    payload["scalars"] = []
    result = grade_item(rubric, "donut_effect_comparison", probe=payload)
    assert result.status == STATUS_PASS
    assert result.evidence["center_city_value"] == 8.2


def test_unnameable_values_go_to_review(rubric, probe_payload):
    payload = probe_payload()
    payload["scalars"] = [{"name": "a", "type": "float", "value": 8.0},
                          {"name": "b", "type": "float", "value": 27.0}]
    payload["series"] = []
    result = grade_item(rubric, "donut_effect_comparison", probe=payload)
    assert result.status == STATUS_MANUAL_REVIEW


def test_no_values_found(rubric, probe_payload):
    payload = probe_payload()
    payload["scalars"] = []
    payload["series"] = []
    result = grade_item(rubric, "donut_effect_comparison", probe=payload)
    assert result.status == STATUS_NOT_FOUND


# ---------------------------------------------------------------------------
# Behaviour when nothing ran
# ---------------------------------------------------------------------------

def test_no_probe_means_review_not_a_silent_zero(rubric):
    execution = ExecutionRecord(success=False, attempted=True, error_cell=1,
                                error_message="ImportError")
    results = get_grader(rubric).grade(make_context(rubric, probe=None, execution=execution))
    by_id = {r.rubric_id: r for r in results}
    assert by_id["philadelphia_subset"].status == STATUS_EXECUTION_ERROR
    assert by_id["philadelphia_subset"].confidence == 0.0
