"""Assignment 2 rubric checks.

The theme of these tests mirrors the theme of the assignment: students pick
their own dataset, so nothing about a chart's *content* is gradeable. What the
checks must get right is the line between fact and judgement — a brush read out
of a compiled chart specification is scored; a paragraph's substance and a
picture's clarity are handed to a person with the evidence attached, never
silently marked.
"""

from __future__ import annotations

import pytest

from assignments.base import GradingContext, get_grader
from grader.charts import (
    ALTAIR,
    MATPLOTLIB,
    SEABORN,
    SOURCE_NONE,
    ChartEvidence,
)
from grader.models import (
    STATUS_FAIL,
    STATUS_MANUAL_REVIEW,
    STATUS_NOT_FOUND,
    STATUS_PARTIAL,
    STATUS_PASS,
    ExecutionRecord,
)
from grader.notebook import NotebookAnalysis

from conftest import (
    BARE_MPL,
    BRUSH_SPEC,
    COUNT_SPEC,
    DASHBOARD_SPEC,
    GOOD_DISCUSSION,
    INTERACTIVE_SPEC,
    PLAIN_SPEC,
    WELL_DRESSED_MPL,
    chart_record,
)


def _analysis(**overrides) -> NotebookAnalysis:
    analysis = NotebookAnalysis(
        path="assignment-2.ipynb",
        n_code_cells=8,
        imports={"pandas", "matplotlib", "seaborn", "altair"},
        read_calls=["read_csv"],
        referenced_files=["data/philly_311_sample.csv"],
        data_path_literals=["data/philly_311_sample.csv"],
    )
    for key, value in overrides.items():
        setattr(analysis, key, value)
    return analysis


def _probe(rows: int = 900) -> dict:
    return {
        "ok": True,
        "errors": [],
        "dataframes": [
            {
                "name": "requests", "rows": rows, "n_columns": 9,
                "columns": ["service_request_id", "requested_datetime", "service_name",
                            "agency_responsible", "zipcode", "status", "days_to_close",
                            "lat", "lon"],
                "dtypes": {}, "head": [], "index_names": [], "numeric_summary": {},
                "value_samples": {}, "nunique": {}, "id_columns": [],
                "boolean_columns": [], "boolean_group_values": {},
            }
        ],
        "series": [], "collections": [], "scalars": [], "functions": [],
        "modules": ["pandas"], "figures": 0, "hidden_tests": [],
    }


def make_context(rubric, evidence=None, analysis=None, execution=None, probe=None,
                 workdir=None, qualitative_grader=None) -> GradingContext:
    context = GradingContext(
        student_id="student_test",
        rubric=rubric,
        analysis=analysis or _analysis(),
        execution=execution or ExecutionRecord(success=True, attempted=True,
                                               execution_time_seconds=4.0, mode="local"),
        probe=probe,
        workdir=workdir,
        qualitative_grader=qualitative_grader,
    )
    if evidence is not None:
        context.cache["chart_evidence"] = evidence
    return context


def grade_item(rubric, rubric_id, **kwargs):
    grader = get_grader(rubric)
    check = getattr(grader, f"check_{rubric_id}")
    return check(make_context(rubric, **kwargs), rubric.item(rubric_id))


# ---------------------------------------------------------------------------
# The rubric itself
# ---------------------------------------------------------------------------

def test_every_rubric_item_has_a_check(hw2_rubric):
    grader = get_grader(hw2_rubric)
    missing = [i.id for i in hw2_rubric.items if not hasattr(grader, f"check_{i.id}")]
    assert missing == []


def test_extra_credit_carries_no_points_in_the_maximum(hw2_rubric):
    """Bonus marks must not inflate the denominator every student is graded on."""
    item = hw2_rubric.item("altair_dashboard_extra_credit")
    assert item.points == 0
    assert hw2_rubric.total_points == 100


def test_every_judgement_item_is_typed_qualitative(hw2_rubric):
    judgement = {"matplotlib_rationale", "matplotlib_aesthetics", "seaborn_rationale",
                 "chart_conclusions"}
    assert {i.id for i in hw2_rubric.items if i.type == "qualitative"} == judgement


# ---------------------------------------------------------------------------
# Part 1: loading the data
#
# Students pick their own dataset and do not hand it in, so the only gradeable
# facts are that a dataset is read at all and that it is read the way the
# instructions ask. Nothing about its contents is checked.
# ---------------------------------------------------------------------------

def test_data_loading_pass(hw2_rubric):
    result = grade_item(hw2_rubric, "data_loading")
    assert result.status == STATUS_PASS
    assert result.automatic_score == 10


def test_data_loading_does_not_require_the_data_to_be_present(hw2_rubric):
    """No probe, no workdir, no dataset — still full marks for loading it right."""
    result = grade_item(hw2_rubric, "data_loading", probe=None, workdir=None)
    assert result.status == STATUS_PASS


def test_a_missing_read_call_is_penalised(hw2_rubric):
    result = grade_item(hw2_rubric, "data_loading",
                        analysis=_analysis(read_calls=[], referenced_files=[]))
    assert result.status == STATUS_PARTIAL
    assert "no pandas read_* call" in result.feedback


def test_absolute_path_is_penalised(hw2_rubric):
    analysis = _analysis(absolute_paths=["/Users/student/Desktop/311.csv"])
    result = grade_item(hw2_rubric, "data_loading", analysis=analysis)
    assert "absolute file path" in result.feedback
    assert result.automatic_score == 6


def test_downloading_the_data_is_penalised(hw2_rubric):
    """"submit your data ... using relative path" — a URL is not a relative path."""
    analysis = _analysis(
        referenced_files=["https://opendataphilly.invalid/311.csv"],
        data_path_literals=["https://opendataphilly.invalid/311.csv"],
        code_source='pd.read_csv("https://opendataphilly.invalid/311.csv")',
    )
    result = grade_item(hw2_rubric, "data_loading", analysis=analysis)
    assert "downloaded at run time" in result.feedback
    assert result.evidence["remote_reads"]


# ---------------------------------------------------------------------------
# Execution — graded from the notebook the student saved, not from our run
# ---------------------------------------------------------------------------

def _ran_cleanly(**overrides) -> NotebookAnalysis:
    defaults = {"stored_outputs": {"execute_result": 4, "display_data": 5, "image": 5},
                "stored_errors": []}
    return _analysis(**{**defaults, **overrides})


def _failed_run() -> ExecutionRecord:
    """What the grading run always looks like without the student's dataset."""
    return ExecutionRecord(
        success=False, attempted=True, error_cell=1, mode="local",
        error_message="FileNotFoundError: 'data/philly_311.csv'",
    )


def test_a_notebook_saved_with_a_clean_run_passes(hw2_rubric):
    result = grade_item(hw2_rubric, "notebook_execution",
                        analysis=_ran_cleanly(), execution=_failed_run())
    assert result.status == STATUS_PASS
    assert result.automatic_score == 10
    assert result.evidence["verified_by"] == "the submitted notebook's saved state"


def test_a_missing_dataset_is_never_charged_to_the_student(hw2_rubric):
    """The grading run fails for everyone; that is the grader's gap, not theirs."""
    result = grade_item(hw2_rubric, "notebook_execution",
                        analysis=_ran_cleanly(), execution=_failed_run())
    assert result.automatic_score == 10
    assert "cannot be re-executed" in result.evidence["note"]


def test_a_notebook_submitted_without_outputs_loses_most_of_the_mark(hw2_rubric):
    analysis = _analysis(stored_outputs={}, stored_errors=[])
    result = grade_item(hw2_rubric, "notebook_execution", analysis=analysis,
                        execution=_failed_run())
    assert result.status == STATUS_PARTIAL
    assert result.automatic_score == 3
    assert "no saved output at all" in result.feedback


def test_a_notebook_that_errored_everywhere_is_not_charged_twice(hw2_rubric):
    """A traceback is evidence the cell ran; "never run" is a different failure."""
    analysis = _analysis(
        stored_outputs={"error": 5},
        stored_errors=[{"ename": "NameError", "evalue": "'df'", "cell": c}
                       for c in range(1, 6)],
    )
    result = grade_item(hw2_rubric, "notebook_execution", analysis=analysis,
                        execution=_failed_run())
    assert "no saved output at all" not in result.feedback
    assert result.automatic_score == 3  # the error cap only, not both penalties


def test_images_are_not_counted_twice_towards_coverage(hw2_rubric):
    """`stored_outputs["image"]` re-tallies display_data cells that hold a picture."""
    analysis = _analysis(n_code_cells=8, stored_errors=[],
                         stored_outputs={"display_data": 3, "image": 3})
    result = grade_item(hw2_rubric, "notebook_execution", analysis=analysis,
                        execution=_failed_run())
    assert "partly run" in result.feedback


def test_errors_saved_in_the_students_own_run_are_deducted(hw2_rubric):
    analysis = _ran_cleanly(
        stored_errors=[{"ename": "KeyError", "evalue": "'zipcode'", "cell": 6}]
    )
    result = grade_item(hw2_rubric, "notebook_execution", analysis=analysis,
                        execution=_failed_run())
    assert result.status == STATUS_PARTIAL
    assert result.automatic_score == 7
    assert "code cell 6" in result.feedback and "KeyError" in result.feedback


def test_a_partly_run_notebook_is_flagged(hw2_rubric):
    analysis = _analysis(n_code_cells=10, stored_outputs={"execute_result": 2},
                         stored_errors=[])
    result = grade_item(hw2_rubric, "notebook_execution", analysis=analysis,
                        execution=_failed_run())
    assert "partly run" in result.feedback


def test_a_real_execution_takes_over_when_the_data_is_supplied(hw2_rubric):
    """An instructor who does collect the data gets the stronger check back."""
    execution = ExecutionRecord(success=True, attempted=True,
                                execution_time_seconds=6.0, mode="docker")
    result = grade_item(hw2_rubric, "notebook_execution",
                        analysis=_analysis(stored_outputs={}), execution=execution)
    assert result.status == STATUS_PASS
    assert result.evidence["verified_by"] == "grading run"


# ---------------------------------------------------------------------------
# Part 2: chart presence
# ---------------------------------------------------------------------------

def test_charts_pass_when_all_are_present_and_rendered(hw2_rubric, chart_evidence):
    for rubric_id in ("matplotlib_chart", "seaborn_chart", "altair_charts"):
        result = grade_item(hw2_rubric, rubric_id, evidence=chart_evidence())
        assert result.status == STATUS_PASS, rubric_id
        assert result.automatic_score == hw2_rubric.item(rubric_id).points


def test_a_missing_library_is_not_found_rather_than_failed(hw2_rubric, chart_evidence):
    records = [c for c in chart_evidence().charts if c.library != SEABORN]
    result = grade_item(hw2_rubric, "seaborn_chart", evidence=chart_evidence(records))
    assert result.status == STATUS_NOT_FOUND
    assert result.automatic_score == 0


def test_two_altair_charts_of_three_earns_partial_credit(hw2_rubric, chart_evidence):
    records = [c for c in chart_evidence().charts if c.library != ALTAIR][:2] + [
        chart_record(ALTAIR, 4, spec=COUNT_SPEC), chart_record(ALTAIR, 5, spec=BRUSH_SPEC)
    ]
    result = grade_item(hw2_rubric, "altair_charts", evidence=chart_evidence(records))
    assert result.status == STATUS_PARTIAL
    assert 0 < result.automatic_score < 15
    assert "found 2 of the 3 required" in result.feedback.lower()


def test_a_chart_that_never_rendered_earns_half(hw2_rubric, chart_evidence):
    records = [chart_record(MATPLOTLIB, 2, rendered=False, source=WELL_DRESSED_MPL)]
    result = grade_item(hw2_rubric, "matplotlib_chart", evidence=chart_evidence(records))
    assert result.status == STATUS_PARTIAL
    assert result.automatic_score == 5


def test_a_chart_cell_that_errored_did_not_render(hw2_rubric, chart_evidence):
    """The inline backend saves the empty axes of a cell that crashed."""
    record = chart_record(SEABORN, 3, rendered=True, source="sns.boxplot(data=df, x='a')")
    record.errored = True
    record.error = "NameError: name 'df' is not defined"
    result = grade_item(hw2_rubric, "seaborn_chart", evidence=chart_evidence([record]))
    assert result.status == STATUS_PARTIAL
    assert "NameError" in result.feedback


def test_three_copies_of_one_chart_are_not_three_charts(hw2_rubric, chart_evidence):
    records = [chart_record(ALTAIR, cell, spec=COUNT_SPEC) for cell in (4, 5, 6)]
    result = grade_item(hw2_rubric, "altair_charts", evidence=chart_evidence(records))
    assert result.status == STATUS_PARTIAL
    assert "not three distinct charts" in result.feedback


def test_evidence_from_the_students_own_output_is_slightly_less_certain(hw2_rubric,
                                                                          chart_evidence):
    """The normal case here, so the drop is visible but does not flag everyone."""
    from grader.charts import SOURCE_MERGED, SOURCE_SUBMITTED

    theirs = grade_item(hw2_rubric, "matplotlib_chart",
                        evidence=chart_evidence(source=SOURCE_MERGED,
                                                output_source=SOURCE_SUBMITTED))
    ours = grade_item(hw2_rubric, "matplotlib_chart", evidence=chart_evidence())
    assert theirs.status == ours.status == STATUS_PASS
    assert theirs.automatic_score == ours.automatic_score
    assert theirs.confidence == 0.85 < ours.confidence


def test_no_readable_notebook_asks_for_a_human_not_a_zero(hw2_rubric):
    result = grade_item(hw2_rubric, "altair_charts", evidence=ChartEvidence(source=SOURCE_NONE))
    assert result.status == STATUS_MANUAL_REVIEW
    assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# Part 2: what the Altair charts do
# ---------------------------------------------------------------------------

def test_transformation_is_read_from_the_compiled_spec(hw2_rubric, chart_evidence):
    result = grade_item(hw2_rubric, "altair_transformation", evidence=chart_evidence())
    assert result.status == STATUS_PASS
    assert result.automatic_score == 8
    assert result.evidence["operations"]


def test_no_transformation_fails_even_when_charts_exist(hw2_rubric, chart_evidence):
    records = [chart_record(ALTAIR, cell, spec=PLAIN_SPEC) for cell in (4, 5, 6)]
    result = grade_item(hw2_rubric, "altair_transformation", evidence=chart_evidence(records))
    assert result.status == STATUS_FAIL
    assert result.automatic_score == 0


def test_brush_is_read_from_the_compiled_spec(hw2_rubric, chart_evidence):
    result = grade_item(hw2_rubric, "altair_brush_selection", evidence=chart_evidence())
    assert result.status == STATUS_PASS
    assert result.automatic_score == 7


def test_interactive_pan_zoom_does_not_earn_the_brush_mark(hw2_rubric, chart_evidence):
    """The single most common near-miss: `.interactive()` is not a brush."""
    records = [chart_record(ALTAIR, 4, spec=COUNT_SPEC),
               chart_record(ALTAIR, 5, spec=INTERACTIVE_SPEC)]
    result = grade_item(hw2_rubric, "altair_brush_selection", evidence=chart_evidence(records))
    assert result.status == STATUS_FAIL
    assert result.automatic_score == 0
    assert "pans and zooms" in result.feedback


def test_a_point_selection_earns_half_the_brush_mark(hw2_rubric, chart_evidence):
    point_spec = {"mark": "point", "encoding": {"x": {"field": "a", "type": "nominal"}},
                  "params": [{"name": "p", "select": {"type": "point", "fields": ["a"]}}]}
    records = [chart_record(ALTAIR, 4, spec=point_spec)]
    result = grade_item(hw2_rubric, "altair_brush_selection", evidence=chart_evidence(records))
    assert result.status == STATUS_PARTIAL
    assert result.automatic_score == 3.5


def test_source_text_alone_earns_partial_credit_at_low_confidence(hw2_rubric, chart_evidence):
    """No spec captured: the code says brush, but nothing proves it compiled."""
    records = [chart_record(ALTAIR, 4, rendered=False,
                            source="brush = alt.selection_interval()\n"
                                   "alt.Chart(df).mark_point().add_params(brush)")]
    result = grade_item(hw2_rubric, "altair_brush_selection", evidence=chart_evidence(records))
    assert result.status == STATUS_PARTIAL
    assert result.automatic_score == 3.5
    assert result.confidence == 0.4


# ---------------------------------------------------------------------------
# Extra credit
# ---------------------------------------------------------------------------

def test_cross_filtered_dashboard_is_reported_for_a_manual_bonus(hw2_rubric, chart_evidence):
    records = [chart_record(ALTAIR, 7, spec=DASHBOARD_SPEC)]
    result = grade_item(hw2_rubric, "altair_dashboard_extra_credit",
                        evidence=chart_evidence(records))
    assert result.status == STATUS_MANUAL_REVIEW
    assert result.points_possible == 0  # never inflates the maximum
    assert "Extra credit earned" in result.feedback
    assert result.evidence["cross_filter_params"] == ["period"]


def test_no_dashboard_is_silent_rather_than_a_deduction(hw2_rubric, chart_evidence):
    result = grade_item(hw2_rubric, "altair_dashboard_extra_credit", evidence=chart_evidence())
    assert result.status == STATUS_NOT_FOUND
    assert result.automatic_score == 0


def test_extra_credit_never_reaches_the_review_queue_as_a_lost_point(hw2_rubric,
                                                                    chart_evidence):
    """A 0-point item must not read as "not full marks" for every student."""
    from grader.models import SubmissionResult
    from grader.scoring import apply_review_policy

    result = SubmissionResult(student_id="s", status="graded",
                              execution=ExecutionRecord(success=True, attempted=True))
    result.items = [grade_item(hw2_rubric, "altair_dashboard_extra_credit",
                               evidence=chart_evidence())]
    apply_review_policy(result, 0.8, review_below_full_marks=True)
    assert not any("Not full marks" in reason for reason in result.review_reasons)


# ---------------------------------------------------------------------------
# Judgement items
# ---------------------------------------------------------------------------

JUDGEMENT_ITEMS = ["matplotlib_rationale", "seaborn_rationale", "matplotlib_aesthetics",
                   "chart_conclusions"]


@pytest.mark.parametrize("rubric_id", JUDGEMENT_ITEMS)
def test_judgement_items_always_go_to_a_human(hw2_rubric, chart_evidence, rubric_id):
    """Even a perfect submission: a machine does not sign off on these."""
    result = grade_item(hw2_rubric, rubric_id, evidence=chart_evidence())
    assert result.status == STATUS_MANUAL_REVIEW
    assert result.confidence < 0.8
    assert result.evidence["provisional_score"] == result.automatic_score


@pytest.mark.parametrize("rubric_id", JUDGEMENT_ITEMS)
def test_judgement_items_carry_the_evidence_a_ta_needs(hw2_rubric, chart_evidence, rubric_id):
    result = grade_item(hw2_rubric, rubric_id, evidence=chart_evidence())
    blob = repr(result.evidence)
    assert len(blob) > 100
    assert "provisional_basis" in blob


def test_a_full_rationale_is_provisionally_worth_full_marks(hw2_rubric, chart_evidence):
    result = grade_item(hw2_rubric, "matplotlib_rationale", evidence=chart_evidence())
    assert result.automatic_score == 5
    assert result.evidence["word_count"] > 25


def test_a_missing_rationale_is_provisionally_zero(hw2_rubric, chart_evidence):
    records = [chart_record(MATPLOTLIB, 2, source=WELL_DRESSED_MPL)]
    result = grade_item(hw2_rubric, "matplotlib_rationale", evidence=chart_evidence(records))
    assert result.automatic_score == 0
    assert result.evidence["text_found_in"] == "not found"


def test_a_rationale_written_away_from_the_chart_still_counts(hw2_rubric, chart_evidence):
    """Prose three cells early is a rationale, not an absence."""
    records = [chart_record(MATPLOTLIB, 2, source=WELL_DRESSED_MPL)]
    analysis = _analysis(markdown_cells=[
        "I used matplotlib here because I needed direct control over the tick spacing "
        "and the annotation on the seasonal peak, which is fiddly in the other libraries."
    ])
    result = grade_item(hw2_rubric, "matplotlib_rationale",
                        evidence=chart_evidence(records), analysis=analysis)
    assert result.automatic_score > 0
    assert "elsewhere" in result.evidence["text_found_in"]


def test_aesthetics_signals_never_reach_full_marks_unreviewed(hw2_rubric, chart_evidence):
    """Labels and colours cannot prove a chart reads well."""
    result = grade_item(hw2_rubric, "matplotlib_aesthetics", evidence=chart_evidence())
    assert 0 < result.automatic_score <= 4  # 80% ceiling of 5
    assert "explicit_colors" in result.evidence["signals_present"]


def test_a_bare_chart_scores_lower_on_aesthetics(hw2_rubric, chart_evidence):
    records = [chart_record(MATPLOTLIB, 2, source=BARE_MPL)]
    bare = grade_item(hw2_rubric, "matplotlib_aesthetics", evidence=chart_evidence(records))
    dressed = grade_item(hw2_rubric, "matplotlib_aesthetics", evidence=chart_evidence())
    assert bare.automatic_score < dressed.automatic_score
    assert "title" in bare.evidence["signals_missing"]


def test_conclusions_are_counted_per_required_chart(hw2_rubric, chart_evidence):
    result = grade_item(hw2_rubric, "chart_conclusions", evidence=chart_evidence())
    assert result.automatic_score == 15
    assert result.evidence["covered"] == 5


def test_a_conclusion_above_the_chart_does_not_count(hw2_rubric, chart_evidence):
    """"in a markdown cell below each chart" — position is the requirement."""
    records = [
        chart_record(MATPLOTLIB, 2, source=WELL_DRESSED_MPL, preamble=GOOD_DISCUSSION),
        chart_record(SEABORN, 3, source="sns.boxplot(data=df, x='a')"),
        chart_record(ALTAIR, 4, spec=COUNT_SPEC),
        chart_record(ALTAIR, 5, spec=BRUSH_SPEC),
        chart_record(ALTAIR, 6, spec=PLAIN_SPEC),
    ]
    result = grade_item(hw2_rubric, "chart_conclusions", evidence=chart_evidence(records))
    assert result.automatic_score == 0
    assert result.evidence["covered"] == 0


def test_extra_altair_charts_do_not_dilute_the_conclusion_coverage(hw2_rubric,
                                                                  chart_evidence):
    """Three discussed charts meet the requirement even alongside two that are not."""
    records = chart_evidence().charts + [
        chart_record(ALTAIR, 7, spec=PLAIN_SPEC),
        chart_record(ALTAIR, 8, spec=PLAIN_SPEC),
    ]
    result = grade_item(hw2_rubric, "chart_conclusions", evidence=chart_evidence(records))
    assert result.automatic_score == 15


# ---------------------------------------------------------------------------
# Optional LLM assistance
# ---------------------------------------------------------------------------

class _StubGrader:
    def __init__(self, **response):
        self.enabled = True
        self.calls = []
        self.response = {"score": 4.0, "max_score": 5.0, "confidence": 0.9,
                         "feedback": "Clear reasoning about the plot type.",
                         "manual_review": False}
        self.response.update(response)

    def grade(self, question, student_response, rubric):
        self.calls.append((question, student_response, rubric))
        return dict(self.response)


def test_a_confident_llm_judgement_replaces_the_provisional_score(hw2_rubric,
                                                                  chart_evidence):
    stub = _StubGrader()
    result = grade_item(hw2_rubric, "seaborn_rationale", evidence=chart_evidence(),
                        qualitative_grader=stub)
    assert result.status == STATUS_PARTIAL
    assert result.automatic_score == 4.0
    assert result.evidence["provisional_basis"] == "LLM judgement"


def test_an_unsure_llm_judgement_falls_back_to_the_human(hw2_rubric, chart_evidence):
    stub = _StubGrader(manual_review=True, confidence=0.4)
    result = grade_item(hw2_rubric, "seaborn_rationale", evidence=chart_evidence(),
                        qualitative_grader=stub)
    assert result.status == STATUS_MANUAL_REVIEW
    assert result.evidence["provisional_basis"] == "structural signals"


def test_no_student_name_is_sent_to_the_model(hw2_rubric, chart_evidence):
    stub = _StubGrader()
    grade_item(hw2_rubric, "seaborn_rationale", evidence=chart_evidence(),
               qualitative_grader=stub)
    sent = repr(stub.calls)
    assert "student_test" not in sent


def test_aesthetics_are_never_sent_to_the_model(hw2_rubric, chart_evidence):
    """It is a picture: no text the model could read answers the question."""
    stub = _StubGrader()
    result = grade_item(hw2_rubric, "matplotlib_aesthetics", evidence=chart_evidence(),
                        qualitative_grader=stub)
    assert stub.calls == []
    assert result.status == STATUS_MANUAL_REVIEW


# ---------------------------------------------------------------------------
# Degraded submissions
# ---------------------------------------------------------------------------

def test_no_notebook_submitted_scores_nothing_but_explains_itself(hw2_rubric):
    from grader.notebook import empty_analysis

    grader = get_grader(hw2_rubric)
    context = GradingContext(
        student_id="s", rubric=hw2_rubric, analysis=empty_analysis(),
        execution=ExecutionRecord(attempted=False),
    )
    results = grader.grade(context)
    assert all(r.automatic_score == 0 for r in results)
    assert all("No notebook was submitted" in r.feedback for r in results
               if r.rubric_id != "notebook_execution")


def test_a_failed_grading_run_does_not_block_the_chart_checks(hw2_rubric,
                                                              chart_evidence):
    """Every submission's grading run fails; the charts are graded regardless."""
    execution = ExecutionRecord(success=False, attempted=True, error_cell=1,
                                error_message="FileNotFoundError: 'data/311.csv'")
    charts = grade_item(hw2_rubric, "matplotlib_chart", evidence=chart_evidence(),
                        execution=execution)
    assert charts.status == STATUS_PASS


def test_a_broken_check_never_loses_the_submission(hw2_rubric, monkeypatch):
    grader = get_grader(hw2_rubric)
    monkeypatch.setattr(
        type(grader), "evidence",
        lambda self, ctx: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    results = grader.grade(make_context(hw2_rubric))
    broken = [r for r in results if r.rubric_id == "altair_charts"][0]
    assert broken.status == STATUS_MANUAL_REVIEW
    assert "RuntimeError" in broken.evidence["grader_error"]
