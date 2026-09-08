"""Assignment 1 rubric checks (design.md §23)."""

from __future__ import annotations

import pytest

from assignments.base import GradingContext, get_grader
from grader.models import (
    STATUS_EXECUTION_ERROR,
    STATUS_FAIL,
    STATUS_NOT_FOUND,
    STATUS_PARTIAL,
    STATUS_PASS,
    ExecutionRecord,
)
from grader.notebook import NotebookAnalysis, extract_markdown_responses


def make_context(rubric, probe=None, analysis=None, execution=None) -> GradingContext:
    return GradingContext(
        student_id="student_test",
        rubric=rubric,
        analysis=analysis or _analysis(),
        execution=execution or ExecutionRecord(success=True, attempted=True,
                                               execution_time_seconds=2.0, mode="local"),
        probe=probe,
    )


def _analysis(**overrides) -> NotebookAnalysis:
    analysis = NotebookAnalysis(
        path="notebook.ipynb",
        n_code_cells=8,
        imports={"pandas", "matplotlib"},
        read_calls=["read_csv"],
        referenced_files=["data/zillow_home_values.csv"],
        markdown_cells=[
            "## Interpretation\n\nIn a short paragraph, describe what happened.",
            "Center City home values increased by about 31 percent between 2010 and "
            "2020. The rise was steady after an early dip, which is consistent with "
            "sustained demand near the central business district and limited new "
            "supply across the four Center City ZIP codes over the decade studied.",
        ],
    )
    for key, value in overrides.items():
        setattr(analysis, key, value)
    return analysis


def grade_item(rubric, rubric_id, **kwargs):
    grader = get_grader(rubric)
    item = rubric.item(rubric_id)
    check = getattr(grader, f"check_{rubric_id}")
    return check(make_context(rubric, **kwargs), item)


# ---------------------------------------------------------------------------
# Hidden tests never leak into the container
# ---------------------------------------------------------------------------

def test_hidden_test_specs_carry_no_expected_values(rubric):
    specs = get_grader(rubric).hidden_test_specs()
    assert specs and specs[0]["id"] == "percent_change_function"
    blob = repr(specs)
    assert "expected" not in blob
    assert specs[0]["cases"][0]["args"] == [100, 120]


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def test_execution_pass(rubric):
    result = grade_item(rubric, "notebook_execution")
    assert result.status == STATUS_PASS
    assert result.automatic_score == 10


def test_execution_failure_gives_partial_credit_not_zero(rubric):
    """design.md §19: a late failure is worth more than an immediate one."""
    execution = ExecutionRecord(
        success=False, attempted=True, error_cell=7, error_message="KeyError: 'Zipcode'"
    )
    result = grade_item(rubric, "notebook_execution", execution=execution)
    assert result.status == STATUS_EXECUTION_ERROR
    assert 0 < result.automatic_score < 10
    assert "cell 7" in result.feedback


def test_timeout_is_distinguished_from_an_error(rubric):
    execution = ExecutionRecord(success=False, attempted=True, timeout=True)
    result = grade_item(rubric, "notebook_execution", execution=execution)
    assert result.evidence["timeout"] is True


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def test_absolute_path_is_penalised(rubric, probe_payload):
    analysis = _analysis(absolute_paths=["/Users/student/Desktop/data.csv"])
    result = grade_item(rubric, "data_loading", probe=probe_payload(), analysis=analysis)
    assert result.status == STATUS_PARTIAL
    assert result.automatic_score == 6
    assert "absolute" in result.feedback


def test_clean_data_loading_passes(rubric, probe_payload):
    result = grade_item(rubric, "data_loading", probe=probe_payload())
    assert result.status == STATUS_PASS


# ---------------------------------------------------------------------------
# Philadelphia subset — found by shape, not by variable name (design.md §21)
# ---------------------------------------------------------------------------

def test_philadelphia_subset_found_without_solution_variable_names(rubric, probe_payload):
    payload = probe_payload()
    payload["dataframes"][1]["name"] = "my_own_weird_name"
    result = grade_item(rubric, "philadelphia_subset", probe=payload)
    assert result.status == STATUS_PASS
    assert result.evidence["philadelphia_zip_count"] == 46


def test_philadelphia_subset_with_leftover_rows_is_partial(rubric, probe_payload):
    payload = probe_payload()
    payload["dataframes"][1]["value_samples"]["zipcode"] += ["15201", "15203"]
    result = grade_item(rubric, "philadelphia_subset", probe=payload)
    assert result.status == STATUS_PARTIAL
    assert "15201" in result.evidence["non_philadelphia_zips"]


def test_missing_subset_is_flagged_not_zeroed_silently(rubric, probe_payload):
    payload = probe_payload()
    payload["dataframes"] = []
    result = grade_item(rubric, "philadelphia_subset", probe=payload)
    assert result.status == STATUS_NOT_FOUND
    assert result.confidence < 0.8  # goes to the review queue


# ---------------------------------------------------------------------------
# Tidy transformation
# ---------------------------------------------------------------------------

def test_tidy_transformation_pass(rubric, probe_payload):
    result = grade_item(rubric, "tidy_transformation", probe=probe_payload())
    assert result.status == STATUS_PASS
    assert result.evidence["detected_roles"]["date"] == "date"


def test_tidy_row_count_off_by_a_lot_is_partial(rubric, probe_payload):
    payload = probe_payload()
    payload["dataframes"][1]["rows"] = 1200
    result = grade_item(rubric, "tidy_transformation", probe=payload)
    assert result.status == STATUS_PARTIAL
    assert result.automatic_score < 15


# ---------------------------------------------------------------------------
# Center City classification
# ---------------------------------------------------------------------------

def test_center_city_exact_match(rubric, probe_payload):
    result = grade_item(rubric, "center_city_definition", probe=probe_payload())
    assert result.status == STATUS_PASS
    assert result.confidence >= 0.98


def test_center_city_one_wrong_zip(rubric, probe_payload):
    payload = probe_payload()
    payload["collections"][0]["values"] = ["19102", "19103", "19104", "19107"]
    payload["dataframes"][1]["boolean_group_values"]["center_city"]["zipcode"] = [
        "19102", "19103", "19104", "19107",
    ]
    result = grade_item(rubric, "center_city_definition", probe=payload)
    assert result.status == STATUS_PARTIAL
    assert result.evidence["missing_zips"] == ["19106"]
    assert result.evidence["unexpected_zips"] == ["19104"]


def test_center_city_found_from_a_flag_column_alone(rubric, probe_payload):
    payload = probe_payload()
    payload["collections"] = []
    result = grade_item(rubric, "center_city_definition", probe=payload)
    assert result.status == STATUS_PASS
    assert "center_city" in result.evidence["matched_from"]


# ---------------------------------------------------------------------------
# Percent change function (hidden tests)
# ---------------------------------------------------------------------------

def test_percent_change_all_tests_pass(rubric, probe_payload):
    result = grade_item(rubric, "percent_change_function", probe=probe_payload())
    assert result.status == STATUS_PASS
    assert result.evidence["tests_passed"] == 5


def test_percent_change_fraction_units_get_partial_credit(rubric, probe_payload):
    payload = probe_payload()
    for call, value in zip(
        payload["hidden_tests"][0]["calls"], [0.2, 0.5, -0.5, 0.0, 0.3142]
    ):
        call["value"] = value
    result = grade_item(rubric, "percent_change_function", probe=payload)
    assert result.status == STATUS_PARTIAL
    assert result.automatic_score == pytest.approx(9.0)  # 15 * 0.6
    assert "fraction" in result.feedback


def test_percent_change_sign_flip_is_recognised(rubric, probe_payload):
    payload = probe_payload()
    for call, value in zip(
        payload["hidden_tests"][0]["calls"], [-20.0, -50.0, 50.0, 0.0, -31.42]
    ):
        call["value"] = value
    result = grade_item(rubric, "percent_change_function", probe=payload)
    assert "inverted" in result.feedback


def test_percent_change_partial_failure(rubric, probe_payload):
    payload = probe_payload()
    payload["hidden_tests"][0]["calls"][2]["value"] = 50.0  # 200 -> 100 should be -50
    result = grade_item(rubric, "percent_change_function", probe=payload)
    assert result.status == STATUS_PARTIAL
    assert result.evidence["tests_failed"] == 1


def test_percent_change_raises_are_captured(rubric, probe_payload):
    payload = probe_payload()
    payload["hidden_tests"][0]["calls"][0] = {
        "label": "100 → 120", "ok": False, "error": "ZeroDivisionError: division by zero"
    }
    result = grade_item(rubric, "percent_change_function", probe=payload)
    assert result.evidence["cases"][0]["error"].startswith("ZeroDivisionError")


def test_ambiguous_function_lowers_confidence(rubric, probe_payload):
    payload = probe_payload()
    payload["hidden_tests"][0]["ambiguous"] = True
    result = grade_item(rubric, "percent_change_function", probe=payload)
    assert result.confidence == 0.75  # below the review threshold


def test_missing_function(rubric, probe_payload):
    payload = probe_payload()
    payload["hidden_tests"][0] = {"id": "percent_change_function", "found": False,
                                  "candidates": [], "calls": []}
    result = grade_item(rubric, "percent_change_function",
                        probe=payload, analysis=_analysis(functions=[]))
    assert result.status == STATUS_NOT_FOUND
    assert result.automatic_score == 0


# ---------------------------------------------------------------------------
# Final answer
# ---------------------------------------------------------------------------

def test_final_answer_match(rubric, probe_payload):
    result = grade_item(rubric, "final_answer", probe=probe_payload())
    assert result.status == STATUS_PASS
    assert result.evidence["matched_variables"][0]["value"] == 31.42


def test_final_answer_as_a_fraction(rubric, probe_payload):
    payload = probe_payload()
    payload["scalars"] = [{"name": "answer", "type": "float", "value": 0.3142}]
    result = grade_item(rubric, "final_answer", probe=payload)
    assert result.status == STATUS_PARTIAL
    assert "fraction" in result.feedback


def test_final_answer_missing_reports_nearest_values(rubric, probe_payload):
    payload = probe_payload()
    payload["scalars"] = [{"name": "answer", "type": "float", "value": 12.0}]
    result = grade_item(rubric, "final_answer", probe=payload)
    assert result.status == STATUS_FAIL
    assert result.evidence["closest_values"][0]["value"] == 12.0


# ---------------------------------------------------------------------------
# Written interpretation
# ---------------------------------------------------------------------------

def test_interpretation_is_scored_but_always_reviewed(rubric, probe_payload):
    result = grade_item(rubric, "interpretation", probe=probe_payload())
    assert result.status == "manual_review"
    assert result.automatic_score > 10
    assert result.confidence < 0.8


def test_the_prompt_is_not_mistaken_for_the_answer(rubric):
    analysis = _analysis(
        markdown_cells=[
            "## Interpretation\n\nIn a short paragraph, describe what happened to "
            "home values in Center City between 2010 and 2020.",
            "*Your answer here*",
        ]
    )
    result = grade_item(rubric, "interpretation", analysis=analysis)
    assert result.status == STATUS_NOT_FOUND


def test_short_answer_is_scored_low(rubric):
    analysis = _analysis(
        markdown_cells=["## Interpretation\n\nDescribe the trend.", "Prices went up."]
    )
    result = grade_item(rubric, "interpretation", analysis=analysis)
    assert result.automatic_score < 3
    assert "short" in result.feedback


def test_llm_grading_low_confidence_is_routed_to_review(rubric):
    class StubGrader:
        enabled = True

        def grade(self, question, student_response, rubric):
            return {"score": 12.0, "max_score": 15, "confidence": 0.4,
                    "feedback": "unsure", "manual_review": False}

    grader = get_grader(rubric)
    item = rubric.item("interpretation")
    ctx = make_context(rubric)
    ctx.qualitative_grader = StubGrader()
    result = grader.check_interpretation(ctx, item)
    assert result.status == "manual_review"
    assert result.confidence == 0.4


# ---------------------------------------------------------------------------
# Behaviour when nothing ran
# ---------------------------------------------------------------------------

def test_no_probe_means_review_not_a_silent_zero(rubric):
    execution = ExecutionRecord(success=False, attempted=True, error_cell=1,
                                error_message="ImportError")
    grader = get_grader(rubric)
    results = grader.grade(make_context(rubric, probe=None, execution=execution))
    by_id = {r.rubric_id: r for r in results}
    assert by_id["philadelphia_subset"].status == STATUS_EXECUTION_ERROR
    assert by_id["philadelphia_subset"].confidence == 0.0


def test_markdown_extraction_ignores_boilerplate():
    analysis = NotebookAnalysis(path="x", markdown_cells=["# Title", "your answer here"])
    response = extract_markdown_responses(analysis, ["interpret"], 40)
    assert response["found"] is False
