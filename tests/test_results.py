"""Session storage, overrides, review policy and exports (design.md §11, §28-31)."""

from __future__ import annotations

import zipfile

from grader.models import ExecutionRecord, RubricItemResult, SubmissionResult
from grader.results import GradingSession
from grader.scoring import apply_review_policy, class_summary, review_queue


def make_result(student_id="student_001", score=15.0, confidence=1.0, success=True):
    return SubmissionResult(
        student_id=student_id,
        display_name=student_id,
        status="graded",
        execution=ExecutionRecord(success=success, attempted=True, mode="local"),
        items=[
            RubricItemResult("a", "Item A", 10, automatic_score=10, status="pass"),
            RubricItemResult("b", "Item B", 20, automatic_score=score, status="partial",
                             confidence=confidence),
        ],
    )


def make_session(tmp_path, results) -> GradingSession:
    session = GradingSession(
        session_id="test_session",
        assignment_id="hw1",
        assignment_name="Assignment 1",
        rubric_version="HW1-v1",
        rubric_path="rubrics/hw1.yaml",
        root=tmp_path / "session",
    )
    for result in results:
        session.upsert(result)
    return session


# ---------------------------------------------------------------------------
# Manual overrides never destroy the automated grade (design.md §11)
# ---------------------------------------------------------------------------

def test_override_keeps_the_automatic_score(tmp_path):
    session = make_session(tmp_path, [make_result()])
    session.set_override("student_001", "b", 18.0, "Alternative valid implementation.")

    item = session.results["student_001"].item("b")
    assert item.automatic_score == 15.0
    assert item.final_score == 18.0
    assert item.manual_override is True
    assert session.results["student_001"].total_score == 28.0
    assert session.results["student_001"].automatic_total == 25.0


def test_disabling_an_override_restores_the_automatic_score(tmp_path):
    session = make_session(tmp_path, [make_result()])
    session.set_override("student_001", "b", 18.0, "note")
    session.set_override("student_001", "b", None, "", enabled=False)
    assert session.results["student_001"].total_score == 25.0


def test_override_clears_the_review_flag_for_that_item():
    result = make_result(confidence=0.5)
    apply_review_policy(result, 0.8)
    assert result.needs_review is True

    result.items[1].manual_override = True
    result.items[1].manual_score = 20.0
    apply_review_policy(result, 0.8)
    assert result.needs_review is False


# ---------------------------------------------------------------------------
# Review policy and queue
# ---------------------------------------------------------------------------

def test_low_confidence_reaches_the_queue():
    result = make_result(confidence=0.71)
    apply_review_policy(result, 0.8)
    assert any("Low confidence" in reason for reason in result.review_reasons)
    assert review_queue([result])[0]["student_id"] == "student_001"


def test_marking_reviewed_empties_the_queue(tmp_path):
    result = make_result(confidence=0.5)
    apply_review_policy(result, 0.8)
    session = make_session(tmp_path, [result])
    assert len(session.queue()) == 1
    session.mark_reviewed("student_001", True)
    assert session.queue() == []


def test_execution_failure_is_its_own_reason():
    result = make_result(success=False)
    result.execution.error_cell = 4
    result.execution.error_message = "KeyError"
    apply_review_policy(result, 0.8)
    assert "execution failed at cell 4" in result.review_reasons[0]


# ---------------------------------------------------------------------------
# Persistence and exports
# ---------------------------------------------------------------------------

def test_session_round_trip(tmp_path):
    session = make_session(tmp_path, [make_result(), make_result("student_002", 20.0)])
    session.set_override("student_001", "b", 17.0, "partial credit for the approach")
    root = session.save()

    reloaded = GradingSession.load(root)
    assert set(reloaded.results) == {"student_001", "student_002"}
    item = reloaded.results["student_001"].item("b")
    assert item.manual_override is True
    assert item.automatic_score == 15.0
    assert item.final_score == 17.0
    assert reloaded.results["student_001"].total_score == 27.0


def test_saved_session_has_the_documented_layout(tmp_path):
    session = make_session(tmp_path, [make_result()])
    root = session.save()
    for name in ("grades.csv", "grading_session.json", "summary.json",
                 "flagged_submissions.csv"):
        assert (root / name).exists()
    assert (root / "feedback" / "student_001.md").exists()
    assert (root / "raw_results" / "student_001.json").exists()


def test_grades_csv_contents(tmp_path):
    session = make_session(tmp_path, [make_result()])
    lines = session.grades_csv().strip().splitlines()
    assert lines[0].startswith("student_id,display_name,total_score,max_score")
    assert lines[1].startswith("student_001,student_001,25,30")


def test_archive_contains_everything(tmp_path):
    session = make_session(tmp_path, [make_result()])
    with zipfile.ZipFile(__import__("io").BytesIO(session.archive_zip())) as archive:
        names = archive.namelist()
    assert "grades.csv" in names
    assert "feedback/student_001.md" in names


def test_overrides_survive_a_regrade(tmp_path):
    session = make_session(tmp_path, [make_result()])
    session.set_override("student_001", "b", 19.0, "kept")
    session.mark_reviewed("student_001", True)
    snapshot = session.collect_overrides()

    fresh = make_session(tmp_path, [make_result()])  # as if regraded from scratch
    assert fresh.results["student_001"].total_score == 25.0
    fresh.apply_overrides(snapshot)
    assert fresh.results["student_001"].total_score == 29.0
    assert fresh.results["student_001"].reviewed is True


def test_class_summary(tmp_path):
    results = [make_result("student_001", 20.0), make_result("student_002", 5.0, 0.5)]
    for result in results:
        apply_review_policy(result, 0.8)
    summary = class_summary(results)
    assert summary["submissions"] == 2
    assert summary["mean_score"] == 22.5
    assert summary["needs_review"] == 1
    assert summary["rubric_breakdown"][0]["name"] == "Item A"


def test_neighbour_navigation(tmp_path):
    session = make_session(
        tmp_path, [make_result("student_001"), make_result("student_002")]
    )
    assert session.neighbour("student_001", 1) == "student_002"
    assert session.neighbour("student_001", -1) is None
