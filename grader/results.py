"""Grading session persistence and exports (design.md §28-29).

A session is a directory on disk. Everything the UI shows can be rebuilt from
it, so the app can be closed and reopened mid-review.
"""

from __future__ import annotations

import csv
import io
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .feedback import build_class_report, build_feedback
from .models import SubmissionResult
from .scoring import class_summary, grade_letter, review_queue
from .utils import dump_json, load_json, slugify, utc_now_iso

RESULTS_ROOT = Path(__file__).resolve().parent.parent / "results"

SESSION_FILE = "grading_session.json"
GRADES_CSV = "grades.csv"
SUMMARY_JSON = "summary.json"
FLAGGED_CSV = "flagged_submissions.csv"
FEEDBACK_DIR = "feedback"
EXECUTED_DIR = "executed_notebooks"
RAW_DIR = "raw_results"


@dataclass
class GradingSession:
    session_id: str
    assignment_id: str
    assignment_name: str
    rubric_version: str
    rubric_path: str
    source: str = ""
    execution_mode: str = "docker"
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    settings: dict[str, Any] = field(default_factory=dict)
    results: dict[str, SubmissionResult] = field(default_factory=dict)
    root: Path | None = None

    # -- collection helpers ------------------------------------------------
    def ordered_results(self) -> list[SubmissionResult]:
        return [self.results[key] for key in sorted(self.results)]

    def upsert(self, result: SubmissionResult) -> None:
        self.results[result.student_id] = result
        self.updated_at = utc_now_iso()

    def summary(self) -> dict[str, Any]:
        data = class_summary(self.ordered_results())
        data["assignment"] = self.assignment_name
        data["rubric_version"] = self.rubric_version
        data["session_id"] = self.session_id
        return data

    def queue(self) -> list[dict[str, Any]]:
        return review_queue(self.ordered_results())

    def student_ids(self) -> list[str]:
        return sorted(self.results)

    def neighbour(self, student_id: str, offset: int) -> str | None:
        ids = self.student_ids()
        if student_id not in ids:
            return None
        index = ids.index(student_id) + offset
        if 0 <= index < len(ids):
            return ids[index]
        return None

    # -- manual intervention (design.md §11) -------------------------------
    def set_override(
        self,
        student_id: str,
        rubric_id: str,
        manual_score: float | None,
        reason: str = "",
        enabled: bool = True,
    ) -> bool:
        result = self.results.get(student_id)
        if result is None:
            return False
        item = result.item(rubric_id)
        if item is None:
            return False
        item.manual_override = bool(enabled)
        item.manual_score = None if not enabled else float(manual_score or 0.0)
        item.override_reason = reason
        self.updated_at = utc_now_iso()
        return True

    def mark_reviewed(self, student_id: str, reviewed: bool = True) -> bool:
        result = self.results.get(student_id)
        if result is None:
            return False
        result.reviewed = bool(reviewed)
        self.updated_at = utc_now_iso()
        return True

    def collect_overrides(self) -> dict[str, dict[str, dict[str, Any]]]:
        """Snapshot manual work so a regrade can restore it (design.md §31)."""
        snapshot: dict[str, dict[str, dict[str, Any]]] = {}
        for student_id, result in self.results.items():
            per_item = {
                item.rubric_id: {
                    "manual_score": item.manual_score,
                    "override_reason": item.override_reason,
                }
                for item in result.items
                if item.manual_override
            }
            if per_item or result.reviewed:
                snapshot[student_id] = {"items": per_item, "reviewed": result.reviewed}
        return snapshot

    def apply_overrides(self, snapshot: dict[str, dict[str, Any]]) -> int:
        restored = 0
        for student_id, payload in (snapshot or {}).items():
            result = self.results.get(student_id)
            if result is None:
                continue
            for rubric_id, values in (payload.get("items") or {}).items():
                if self.set_override(
                    student_id, rubric_id, values.get("manual_score"),
                    values.get("override_reason", ""), True,
                ):
                    restored += 1
            if payload.get("reviewed"):
                result.reviewed = True
        return restored

    # -- persistence -------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "assignment_id": self.assignment_id,
            "assignment_name": self.assignment_name,
            "rubric_version": self.rubric_version,
            "rubric_path": self.rubric_path,
            "source": self.source,
            "execution_mode": self.execution_mode,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "settings": self.settings,
            "results": [r.to_dict() for r in self.ordered_results()],
        }

    def save(self, root: str | Path | None = None) -> Path:
        root = Path(root) if root else (self.root or RESULTS_ROOT / self.session_id)
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.updated_at = utc_now_iso()

        dump_json(root / SESSION_FILE, self.to_dict())
        dump_json(root / SUMMARY_JSON, self.summary())
        (root / GRADES_CSV).write_text(self.grades_csv(), encoding="utf-8")
        (root / FLAGGED_CSV).write_text(self.flagged_csv(), encoding="utf-8")

        feedback_dir = root / FEEDBACK_DIR
        feedback_dir.mkdir(exist_ok=True)
        for result in self.ordered_results():
            (feedback_dir / f"{slugify(result.student_id)}.md").write_text(
                build_feedback(result, self.assignment_name), encoding="utf-8"
            )
            dump_json(root / RAW_DIR / f"{slugify(result.student_id)}.json", result.to_dict())

        (root / "class_report.md").write_text(
            build_class_report(self.summary(), self.assignment_name), encoding="utf-8"
        )
        return root

    def store_executed_notebook(self, student_id: str, notebook_path: str | Path) -> str | None:
        """Keep the executed notebook alongside the results (design.md §28)."""
        if self.root is None or not notebook_path:
            return None
        source = Path(notebook_path)
        if not source.exists():
            return None
        target_dir = self.root / EXECUTED_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{slugify(student_id)}.ipynb"
        shutil.copy2(source, target)
        return str(target)

    @classmethod
    def load(cls, root: str | Path) -> "GradingSession":
        root = Path(root)
        data = load_json(root / SESSION_FILE)
        session = cls(
            session_id=data["session_id"],
            assignment_id=data["assignment_id"],
            assignment_name=data.get("assignment_name", data["assignment_id"]),
            rubric_version=data.get("rubric_version", ""),
            rubric_path=data.get("rubric_path", ""),
            source=data.get("source", ""),
            execution_mode=data.get("execution_mode", "docker"),
            created_at=data.get("created_at", utc_now_iso()),
            updated_at=data.get("updated_at", utc_now_iso()),
            settings=data.get("settings", {}),
            root=root,
        )
        for payload in data.get("results", []):
            result = SubmissionResult.from_dict(payload)
            session.results[result.student_id] = result
        return session

    # -- exports (design.md §29) -------------------------------------------
    def grades_csv(self) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "student_id", "display_name", "total_score", "max_score", "percentage",
                "letter", "execution_status", "manual_review", "reviewed",
                "manual_override", "confidence",
            ]
        )
        for result in self.ordered_results():
            writer.writerow(
                [
                    result.student_id,
                    result.display_name,
                    f"{result.total_score:g}",
                    f"{result.max_score:g}",
                    "" if result.percentage is None else f"{result.percentage:g}",
                    grade_letter(result.percentage),
                    "success" if result.execution.success else (
                        "timeout" if result.execution.timeout else "error"
                    ),
                    str(result.needs_review).lower(),
                    str(result.reviewed).lower(),
                    str(result.has_manual_override).lower(),
                    "" if result.confidence is None else f"{result.confidence:g}",
                ]
            )
        return buffer.getvalue()

    def rubric_csv(self) -> str:
        """Long-format per-item scores, useful for item analysis."""
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ["student_id", "rubric_id", "rubric_name", "points_possible",
             "automatic_score", "final_score", "status", "confidence", "manual_override"]
        )
        for result in self.ordered_results():
            for item in result.items:
                writer.writerow(
                    [
                        result.student_id, item.rubric_id, item.name,
                        f"{item.points_possible:g}", f"{item.automatic_score:g}",
                        f"{item.final_score:g}", item.status, f"{item.confidence:g}",
                        str(item.manual_override).lower(),
                    ]
                )
        return buffer.getvalue()

    def flagged_csv(self) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["student_id", "reason", "score", "max_score", "confidence"])
        for entry in self.queue():
            writer.writerow(
                [
                    entry["student_id"], entry["reason"],
                    "" if entry["score"] is None else f"{entry['score']:g}",
                    f"{entry['max_score']:g}",
                    "" if entry["confidence"] is None else f"{entry['confidence']:g}",
                ]
            )
        return buffer.getvalue()

    def feedback_zip(self) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for result in self.ordered_results():
                archive.writestr(
                    f"feedback/{slugify(result.student_id)}.md",
                    build_feedback(result, self.assignment_name),
                )
        return buffer.getvalue()

    def archive_zip(self) -> bytes:
        """The whole session directory, for handing over or archiving."""
        self.save()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            root = self.root
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(root).as_posix())
        return buffer.getvalue()


# ---------------------------------------------------------------------------
# Session discovery
# ---------------------------------------------------------------------------

def list_sessions(root: str | Path = RESULTS_ROOT) -> list[dict[str, Any]]:
    root = Path(root)
    if not root.exists():
        return []
    sessions = []
    for directory in sorted(root.iterdir(), reverse=True):
        session_file = directory / SESSION_FILE
        if not session_file.is_dir() and session_file.exists():
            try:
                data = load_json(session_file)
            except Exception:
                continue
            sessions.append(
                {
                    "session_id": data.get("session_id", directory.name),
                    "assignment_name": data.get("assignment_name", ""),
                    "created_at": data.get("created_at", ""),
                    "updated_at": data.get("updated_at", ""),
                    "submissions": len(data.get("results", [])),
                    "path": str(directory),
                }
            )
    return sessions


def new_session_id(assignment_id: str) -> str:
    from datetime import datetime

    return f"{slugify(assignment_id)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
