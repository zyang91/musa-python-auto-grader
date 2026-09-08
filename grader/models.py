"""Structured result types shared by the engine, the store and the UI.

The contract in design.md section 24 is the source of truth for the on-disk shape:
every rubric item keeps both ``automatic_score`` and ``final_score`` so a manual
override never destroys the automated result.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Statuses (design.md section 24)
# ---------------------------------------------------------------------------

STATUS_PASS = "pass"
STATUS_PARTIAL = "partial"
STATUS_FAIL = "fail"
STATUS_WARNING = "warning"
STATUS_MANUAL_REVIEW = "manual_review"
STATUS_EXECUTION_ERROR = "execution_error"
STATUS_NOT_FOUND = "not_found"

ALL_STATUSES = (
    STATUS_PASS,
    STATUS_PARTIAL,
    STATUS_FAIL,
    STATUS_WARNING,
    STATUS_MANUAL_REVIEW,
    STATUS_EXECUTION_ERROR,
    STATUS_NOT_FOUND,
)

# Status -> (icon, colour bucket). Colour is never the only signal (section 15).
STATUS_DISPLAY: dict[str, tuple[str, str]] = {
    STATUS_PASS: ("✓", "green"),
    STATUS_PARTIAL: ("⚠", "yellow"),
    STATUS_WARNING: ("⚠", "yellow"),
    STATUS_MANUAL_REVIEW: ("⚠", "yellow"),
    STATUS_FAIL: ("✕", "red"),
    STATUS_EXECUTION_ERROR: ("✕", "red"),
    STATUS_NOT_FOUND: ("—", "gray"),
}


def status_icon(status: str) -> str:
    return STATUS_DISPLAY.get(status, ("—", "gray"))[0]


def status_color(status: str) -> str:
    return STATUS_DISPLAY.get(status, ("—", "gray"))[1]


@dataclass
class ExecutionRecord:
    """Outcome of running one student notebook (design.md section 19)."""

    success: bool = False
    execution_time_seconds: float = 0.0
    timeout: bool = False
    error_cell: int | None = None
    error_message: str | None = None
    traceback: str = ""
    mode: str = "docker"
    attempted: bool = False
    log: str = ""
    executed_notebook_path: str | None = None

    @property
    def status(self) -> str:
        if not self.attempted:
            return STATUS_NOT_FOUND
        return STATUS_PASS if self.success else STATUS_EXECUTION_ERROR

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionRecord":
        return cls(**{k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__})


@dataclass
class RubricItemResult:
    """One graded rubric line (design.md section 24)."""

    rubric_id: str
    name: str
    points_possible: float
    automatic_score: float = 0.0
    status: str = STATUS_NOT_FOUND
    confidence: float = 1.0
    feedback: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    type: str = "deterministic"

    # Human intervention (design.md section 11) — never overwrites the automated value.
    manual_override: bool = False
    manual_score: float | None = None
    override_reason: str = ""

    @property
    def final_score(self) -> float:
        if self.manual_override and self.manual_score is not None:
            return float(self.manual_score)
        return float(self.automatic_score)

    @property
    def needs_review(self) -> bool:
        if self.manual_override:
            return False
        return self.status == STATUS_MANUAL_REVIEW

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["final_score"] = self.final_score
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RubricItemResult":
        payload = {k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__}
        return cls(**payload)


@dataclass
class SubmissionResult:
    """Everything known about one student's submission."""

    student_id: str
    display_name: str = ""
    notebook_path: str | None = None
    submission_dir: str | None = None
    items: list[RubricItemResult] = field(default_factory=list)
    execution: ExecutionRecord = field(default_factory=ExecutionRecord)
    discovery_warnings: list[str] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    reviewed: bool = False
    graded_at: str | None = None
    status: str = "pending"  # pending | graded | error | skipped
    error: str | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)

    # -- scores ------------------------------------------------------------
    @property
    def max_score(self) -> float:
        return round(sum(i.points_possible for i in self.items), 2)

    @property
    def automatic_total(self) -> float:
        return round(sum(i.automatic_score for i in self.items), 2)

    @property
    def total_score(self) -> float:
        return round(sum(i.final_score for i in self.items), 2)

    @property
    def percentage(self) -> float | None:
        if not self.max_score:
            return None
        return round(100.0 * self.total_score / self.max_score, 1)

    @property
    def confidence(self) -> float | None:
        """Lowest item confidence — the weakest link decides trust in the grade."""
        weighted = [i.confidence for i in self.items if i.points_possible > 0]
        if not weighted:
            return None
        return round(min(weighted), 2)

    @property
    def has_manual_override(self) -> bool:
        return any(i.manual_override for i in self.items)

    @property
    def needs_review(self) -> bool:
        if self.reviewed:
            return False
        return bool(self.open_review_reasons())

    def open_review_reasons(self) -> list[str]:
        reasons = list(self.review_reasons)
        for item in self.items:
            if not item.needs_review:
                continue
            # The review policy may already name this item; don't say it twice.
            if any(item.name in reason for reason in reasons):
                continue
            reasons.append(f"{item.name}: {item.feedback or 'needs manual review'}")
        return reasons

    def item(self, rubric_id: str) -> RubricItemResult | None:
        for i in self.items:
            if i.rubric_id == rubric_id:
                return i
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "student_id": self.student_id,
            "display_name": self.display_name,
            "notebook_path": self.notebook_path,
            "submission_dir": self.submission_dir,
            "status": self.status,
            "error": self.error,
            "graded_at": self.graded_at,
            "reviewed": self.reviewed,
            "needs_review": self.needs_review,
            "discovery_warnings": self.discovery_warnings,
            "review_reasons": self.review_reasons,
            "execution": self.execution.to_dict(),
            "total_score": self.total_score,
            "automatic_total": self.automatic_total,
            "max_score": self.max_score,
            "confidence": self.confidence,
            "artifacts": self.artifacts,
            "items": [i.to_dict() for i in self.items],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SubmissionResult":
        return cls(
            student_id=data["student_id"],
            display_name=data.get("display_name", ""),
            notebook_path=data.get("notebook_path"),
            submission_dir=data.get("submission_dir"),
            items=[RubricItemResult.from_dict(i) for i in data.get("items", [])],
            execution=ExecutionRecord.from_dict(data.get("execution", {})),
            discovery_warnings=list(data.get("discovery_warnings", [])),
            review_reasons=list(data.get("review_reasons", [])),
            reviewed=bool(data.get("reviewed", False)),
            graded_at=data.get("graded_at"),
            status=data.get("status", "pending"),
            error=data.get("error"),
            artifacts=dict(data.get("artifacts", {})),
        )


@dataclass
class GradingProgress:
    """Snapshot pushed to the UI while grading runs (design.md section 7)."""

    total: int = 0
    completed: int = 0
    successful: int = 0
    flagged: int = 0
    failed: int = 0
    current_student: str | None = None
    stage: str = "idle"
    stages: dict[str, str] = field(default_factory=dict)
    finished: bool = False
    message: str = ""

    @property
    def remaining(self) -> int:
        return max(self.total - self.completed, 0)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["remaining"] = self.remaining
        return data
