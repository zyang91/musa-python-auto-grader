"""The grading service the UI talks to.

Streamlit never calls the executor or the rubric engine directly (design.md §4):
it hands a source and a config to this service and receives progress snapshots
and a ``GradingSession`` back.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .discovery import (
    SubmissionCandidate,
    discover_submissions,
    extract_zip,
    prepare_workdir,
)
from .executor import MODE_DOCKER, MODE_LOCAL, ExecutionConfig, execute_submission
from .llm import DisabledQualitativeGrader
from .models import ExecutionRecord, GradingProgress, SubmissionResult
from .notebook import analyze_notebook, empty_analysis
from .results import GradingSession, new_session_id
from .rubric import Rubric, load_rubric
from .scoring import DEFAULT_CONFIDENCE_THRESHOLD, apply_review_policy
from .utils import slugify, utc_now_iso

ProgressCallback = Callable[[GradingProgress], None]

STAGE_LABELS = [
    ("execution", "Notebook execution"),
    ("structural", "Structural checks"),
    ("hidden", "Hidden tests"),
    ("feedback", "Feedback generation"),
]


@dataclass
class GraderSettings:
    """Everything the Settings page can change (design.md §33)."""

    execution_mode: str = MODE_DOCKER
    docker_image: str = "musa-grader:latest"
    timeout_seconds: int = 600
    cell_timeout_seconds: int = 300
    memory_limit: str = "2g"
    cpu_limit: str = "1.0"
    # Data files the instructor supplies for every submission (design note: from
    # HW1 onwards students hand in a notebook and nothing else).
    shared_data_paths: list[str] = field(default_factory=list)
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
    # Any deduction goes to the review queue, not just uncertain ones.
    review_below_full_marks: bool = True
    llm_enabled: bool = False
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-5"
    keep_workdirs: bool = False

    def execution_config(self) -> ExecutionConfig:
        return ExecutionConfig(
            mode=self.execution_mode,
            docker_image=self.docker_image,
            timeout_seconds=int(self.timeout_seconds),
            cell_timeout_seconds=int(self.cell_timeout_seconds),
            memory_limit=self.memory_limit,
            cpu_limit=str(self.cpu_limit),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_mode": self.execution_mode,
            "docker_image": self.docker_image,
            "timeout_seconds": self.timeout_seconds,
            "cell_timeout_seconds": self.cell_timeout_seconds,
            "memory_limit": self.memory_limit,
            "cpu_limit": self.cpu_limit,
            "shared_data_paths": list(self.shared_data_paths),
            "confidence_threshold": self.confidence_threshold,
            "review_below_full_marks": self.review_below_full_marks,
            "llm_enabled": self.llm_enabled,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
        }


@dataclass
class LoadedSubmissions:
    source: str
    candidates: list[SubmissionCandidate] = field(default_factory=list)
    extracted_root: Path | None = None

    @property
    def ok_count(self) -> int:
        return sum(1 for c in self.candidates if c.ok)

    @property
    def warning_count(self) -> int:
        return sum(1 for c in self.candidates if c.warnings or not c.ok)


class GradingService:
    def __init__(self, rubric: Rubric, settings: GraderSettings | None = None,
                 qualitative_grader: Any | None = None):
        # Imported here rather than at module scope: `assignments` imports the
        # grading models, so a top-level import makes the two packages circular
        # depending on which one the caller touches first.
        from assignments.base import get_grader

        self.rubric = rubric
        self.settings = settings or GraderSettings()
        self.qualitative_grader = qualitative_grader or DisabledQualitativeGrader()
        self.grader = get_grader(rubric)

    # -- construction ------------------------------------------------------
    @classmethod
    def from_rubric_path(cls, path: str | Path, settings: GraderSettings | None = None,
                         qualitative_grader: Any | None = None) -> "GradingService":
        return cls(load_rubric(path), settings, qualitative_grader)

    # -- configuration checks ---------------------------------------------
    def preflight(self) -> list[str]:
        """Problems that would make a grading run misleading rather than wrong.

        The big one: this assignment's students submit a notebook and nothing
        else, so without instructor-supplied data every notebook fails at
        ``read_csv`` and the whole class looks broken.
        """
        problems: list[str] = []
        if self.rubric.requires_data and not self.settings.shared_data_paths:
            wanted = self.rubric.data.get("description", "the assignment data file")
            problems.append(
                "No assignment data file is set. Students submit only a notebook, "
                f"so the grader has to supply {wanted.strip()} "
                "Upload it in the sidebar before running."
            )
        for path in self.settings.shared_data_paths:
            if not Path(path).is_file():
                problems.append(f"Assignment data file not found: {path}")
        return problems

    # -- step 1: find submissions -----------------------------------------
    def load_submissions(self, source: str | Path, extract_to: str | Path | None = None) -> LoadedSubmissions:
        """Accept a folder or a Canvas ZIP (design.md §16)."""
        source = Path(source)
        extracted_root: Path | None = None
        if source.is_file() and source.suffix.lower() == ".zip":
            extract_to = Path(extract_to or tempfile.mkdtemp(prefix="musa_zip_"))
            extracted_root = extract_zip(source, extract_to)
            root = extracted_root
        else:
            root = source

        candidates = discover_submissions(
            root,
            notebook_hints=self.rubric.discovery.get("notebook_name_hints", []),
            ignore_patterns=self.rubric.discovery.get("ignore_name_patterns", []),
        )
        return LoadedSubmissions(source=str(source), candidates=candidates,
                                 extracted_root=extracted_root)

    # -- step 2: grade -----------------------------------------------------
    def new_session(self, source: str) -> GradingSession:
        return GradingSession(
            session_id=new_session_id(self.rubric.id),
            assignment_id=self.rubric.id,
            assignment_name=self.rubric.name,
            rubric_version=self.rubric.version,
            rubric_path=self.rubric.source_path or "",
            source=source,
            execution_mode=self.settings.execution_mode,
            settings=self.settings.to_dict(),
        )

    def run(
        self,
        candidates: Iterable[SubmissionCandidate],
        session: GradingSession | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
        preserve_overrides: dict[str, Any] | None = None,
        workdir_root: str | Path | None = None,
    ) -> GradingSession:
        candidates = list(candidates)
        session = session or self.new_session("")
        session.save()  # create the directory up front so artifacts have a home

        progress = GradingProgress(total=len(candidates), stage="starting")
        _emit(progress_callback, progress)

        base = Path(workdir_root or tempfile.mkdtemp(prefix="musa_grading_"))
        base.mkdir(parents=True, exist_ok=True)

        try:
            for candidate in candidates:
                if cancel_event is not None and cancel_event.is_set():
                    progress.message = "Grading cancelled."
                    break

                progress.current_student = candidate.student_id
                progress.stages = {key: "waiting" for key, _ in STAGE_LABELS}
                _emit(progress_callback, progress)

                result = self._grade_one(
                    candidate, base / slugify(candidate.student_id), session,
                    progress, progress_callback,
                )
                session.upsert(result)

                progress.completed += 1
                if result.status == "graded" and result.execution.success:
                    progress.successful += 1
                if result.execution.attempted and not result.execution.success:
                    progress.failed += 1
                if result.needs_review:
                    progress.flagged += 1
                _emit(progress_callback, progress)

            if preserve_overrides:
                session.apply_overrides(preserve_overrides)

            session.save()
        finally:
            if not self.settings.keep_workdirs:
                shutil.rmtree(base, ignore_errors=True)

        progress.finished = True
        progress.current_student = None
        progress.stage = "done"
        _emit(progress_callback, progress)
        return session

    # -- one submission ----------------------------------------------------
    def _grade_one(
        self,
        candidate: SubmissionCandidate,
        workdir: Path,
        session: GradingSession,
        progress: GradingProgress,
        progress_callback: ProgressCallback | None,
    ) -> SubmissionResult:
        from assignments.base import GradingContext

        result = SubmissionResult(
            student_id=candidate.student_id,
            display_name=candidate.display_name or candidate.student_id,
            notebook_path=str(candidate.notebook_path) if candidate.notebook_path else None,
            submission_dir=str(candidate.source_dir) if candidate.source_dir else None,
            discovery_warnings=list(candidate.warnings),
            graded_at=utc_now_iso(),
        )

        if not candidate.ok:
            result.status = "skipped"
            result.error = "no notebook found in this submission"
            result.execution = ExecutionRecord(mode=self.settings.execution_mode, attempted=False)
            result.items = self.grader.grade(
                GradingContext(
                    student_id=candidate.student_id,
                    rubric=self.rubric,
                    analysis=empty_analysis(),
                    execution=result.execution,
                    probe=None,
                    discovery_warnings=result.discovery_warnings,
                    qualitative_grader=self.qualitative_grader,
                )
            )
            return apply_review_policy(
                result,
                self.settings.confidence_threshold,
                self.settings.review_below_full_marks,
            )

        try:
            # Static analysis first: it tells us which paths the notebook reads
            # from, and the data has to be in place before the notebook runs.
            _stage(progress, progress_callback, "structural", "running")
            analysis = analyze_notebook(candidate.notebook_path)
            _stage(progress, progress_callback, "structural", "done")

            prepare_workdir(
                candidate,
                workdir,
                shared_data=self.settings.shared_data_paths,
                # Read-call arguments first, then any other path-looking literal.
                referenced_paths=analysis.referenced_files + [
                    literal for literal in analysis.data_path_literals
                    if literal not in analysis.referenced_files
                ],
                fallback_dirs=self.rubric.data.get("fallback_locations", ["data", ""]),
            )

            _stage(progress, progress_callback, "execution", "running")
            execution, probe = execute_submission(
                workdir, self.grader.probe_config(), self.settings.execution_config()
            )
            result.execution = execution
            _stage(progress, progress_callback, "execution",
                   "done" if execution.success else "error")

            if execution.executed_notebook_path:
                stored = session.store_executed_notebook(
                    candidate.student_id, execution.executed_notebook_path
                )
                if stored:
                    result.execution.executed_notebook_path = stored

            result.artifacts = {
                "absolute_paths": analysis.absolute_paths,
                "imports": sorted(analysis.imports),
                "functions": analysis.function_names(),
                "n_code_cells": analysis.n_code_cells,
                "n_markdown_cells": analysis.n_markdown_cells,
                "probe_ok": bool(probe),
                "probe_errors": (probe or {}).get("errors", []),
                "data_placement": candidate.data_placement,
            }

            _stage(progress, progress_callback, "hidden", "running")
            context = GradingContext(
                student_id=candidate.student_id,
                rubric=self.rubric,
                analysis=analysis,
                execution=execution,
                probe=probe,
                workdir=workdir,
                discovery_warnings=result.discovery_warnings,
                qualitative_grader=self.qualitative_grader,
                settings=self.settings.to_dict(),
            )
            result.items = self.grader.grade(context)
            _stage(progress, progress_callback, "hidden", "done")

            _stage(progress, progress_callback, "feedback", "running")
            result.review_reasons = list(candidate.review_reasons)
            result.status = "graded"
            apply_review_policy(
                result,
                self.settings.confidence_threshold,
                self.settings.review_below_full_marks,
            )
            _stage(progress, progress_callback, "feedback", "done")
        except Exception as exc:
            result.status = "error"
            result.error = f"{type(exc).__name__}: {exc}"
            result.artifacts["traceback"] = traceback.format_exc()[:8000]
            result.review_reasons.append(f"Grader error: {result.error}")

        return result

    # -- regrading (design.md §31) ----------------------------------------
    def regrade(
        self,
        session: GradingSession,
        candidates: Iterable[SubmissionCandidate],
        preserve_overrides: bool = True,
        progress_callback: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> GradingSession:
        snapshot = session.collect_overrides() if preserve_overrides else {}
        fresh = self.new_session(session.source)
        fresh.session_id = session.session_id
        fresh.root = session.root
        fresh.created_at = session.created_at
        return self.run(
            candidates,
            session=fresh,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
            preserve_overrides=snapshot,
        )


def _emit(callback: ProgressCallback | None, progress: GradingProgress) -> None:
    if callback is not None:
        try:
            callback(progress)
        except Exception:
            pass  # a failing UI callback must never stop grading


def _stage(
    progress: GradingProgress,
    callback: ProgressCallback | None,
    stage: str,
    state: str,
) -> None:
    progress.stage = stage
    progress.stages[stage] = state
    _emit(callback, progress)
