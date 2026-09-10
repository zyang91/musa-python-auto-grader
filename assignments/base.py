"""Assignment grader base class and registry.

An assignment module maps rubric ids to check methods. Every check receives the
same context and returns one ``RubricItemResult`` carrying a score, a status, a
confidence and the evidence behind it (design.md §24).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from grader.models import (
    STATUS_EXECUTION_ERROR,
    STATUS_FAIL,
    STATUS_MANUAL_REVIEW,
    STATUS_NOT_FOUND,
    STATUS_PARTIAL,
    STATUS_PASS,
    ExecutionRecord,
    RubricItemResult,
)
from grader.notebook import NotebookAnalysis
from grader.rubric import Rubric, RubricItem


@dataclass
class GradingContext:
    """Everything a check may look at."""

    student_id: str
    rubric: Rubric
    analysis: NotebookAnalysis
    execution: ExecutionRecord
    probe: dict[str, Any] | None = None
    workdir: Path | None = None
    discovery_warnings: list[str] = field(default_factory=list)
    qualitative_grader: Any | None = None
    settings: dict[str, Any] = field(default_factory=dict)
    # Scratch space for work shared between checks on one submission — e.g.
    # HW2 reads the executed notebook once and grades seven items from it.
    cache: dict[str, Any] = field(default_factory=dict)

    @property
    def probe_ok(self) -> bool:
        return bool(self.probe)


class AssignmentGrader:
    """Base grader: dispatches rubric ids to ``check_<rubric_id>`` methods."""

    assignment_id = "base"

    def __init__(self, rubric: Rubric):
        self.rubric = rubric

    # -- execution wiring --------------------------------------------------
    def probe_config(self) -> dict[str, Any]:
        """Config handed to the in-kernel probe (hidden tests included)."""
        config = dict(self.rubric.probe)
        config.setdefault("max_head_rows", 5)
        config.setdefault("max_unique_values", 80)
        config["hidden_tests"] = self.hidden_test_specs()
        return config

    def hidden_test_specs(self) -> list[dict[str, Any]]:
        """Only selectors and call inputs — expected values stay on the host.

        Two call styles: ``scalar_args`` passes literal arguments, ``group_frame``
        asks the probe to build a DataFrame from interpolated anchor points and
        pass that. Either way the container is told what to call the function
        with, never what it should return.
        """
        specs: list[dict[str, Any]] = []
        for item in self.rubric.items:
            if item.type != "hidden_test":
                continue
            config = item.config
            kind = config.get("type", "scalar_args")
            spec: dict[str, Any] = {
                "id": item.id,
                "type": kind,
                "selector": config.get("selector") or {},
            }
            if kind == "group_frame":
                spec["frame"] = config.get("frame") or {}
                spec["cases"] = [
                    {"label": case.get("label", ""), "anchors": case.get("anchors", [])}
                    for case in config.get("cases", [])
                ]
            else:
                spec["cases"] = [
                    {
                        "label": case.get("label", str(case.get("args"))),
                        "args": case.get("args", []),
                        "kwargs": case.get("kwargs", {}),
                    }
                    for case in config.get("cases", [])
                ]
            specs.append(spec)
        return specs

    # -- grading -----------------------------------------------------------
    def grade(self, ctx: GradingContext) -> list[RubricItemResult]:
        results: list[RubricItemResult] = []
        no_submission = ctx.analysis.parse_error == "no notebook submitted"
        for item in self.rubric.items:
            if no_submission and item.type != "execution":
                results.append(
                    self.result(
                        item, 0.0, STATUS_NOT_FOUND, 1.0,
                        "No notebook was submitted, so this item could not be graded.",
                        {"no_submission": True},
                    )
                )
                continue
            check: Callable[[GradingContext, RubricItem], RubricItemResult] | None
            check = getattr(self, f"check_{item.id}", None)
            try:
                if check is None:
                    results.append(self.check_unimplemented(ctx, item))
                else:
                    results.append(check(ctx, item))
            except Exception as exc:  # a broken check must not lose the submission
                results.append(
                    self.result(
                        item,
                        0.0,
                        STATUS_MANUAL_REVIEW,
                        confidence=0.0,
                        feedback=(
                            "This item could not be graded automatically "
                            f"({type(exc).__name__}: {exc}). Please grade it by hand."
                        ),
                        evidence={"grader_error": f"{type(exc).__name__}: {exc}"},
                    )
                )
        return results

    # -- helpers -----------------------------------------------------------
    def result(
        self,
        item: RubricItem,
        score: float,
        status: str,
        confidence: float = 1.0,
        feedback: str = "",
        evidence: dict[str, Any] | None = None,
    ) -> RubricItemResult:
        # Partial credit lands on a grading increment rather than a raw float,
        # so a TA never has to explain a score of 14.28.
        step = float(self.rubric.settings.get("score_rounding", 0.5) or 0)
        score = float(score)
        if step > 0:
            score = round(score / step) * step
        score = max(0.0, min(round(score, 2), float(item.points)))
        return RubricItemResult(
            rubric_id=item.id,
            name=item.name,
            points_possible=float(item.points),
            automatic_score=score,
            status=status,
            confidence=round(float(confidence), 2),
            feedback=feedback,
            evidence=evidence or {},
            type=item.type,
        )

    def check_unimplemented(self, ctx: GradingContext, item: RubricItem) -> RubricItemResult:
        return self.result(
            item,
            0.0,
            STATUS_MANUAL_REVIEW,
            confidence=0.0,
            feedback="No automated check is implemented for this rubric item yet.",
            evidence={"note": f"add a check_{item.id} method to the assignment grader"},
        )

    def no_probe_result(self, item: RubricItem, ctx: GradingContext) -> RubricItemResult:
        """Shared response when the kernel never reported its namespace."""
        reason = (
            "The notebook did not execute, so its objects could not be inspected."
            if not ctx.execution.success
            else "The grading probe returned no data for this submission."
        )
        return self.result(
            item,
            0.0,
            STATUS_EXECUTION_ERROR if not ctx.execution.success else STATUS_MANUAL_REVIEW,
            confidence=0.0,
            feedback=f"{reason} This item needs manual review rather than an automatic zero.",
            evidence={
                "execution_success": ctx.execution.success,
                "error_message": ctx.execution.error_message,
                "error_cell": ctx.execution.error_cell,
            },
        )

    # -- generic checks ----------------------------------------------------
    def check_notebook_execution(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        """Shared execution check (design.md §19). Never an automatic zero."""
        execution = ctx.execution
        partial_ratio = float(item.config.get("partial_credit_ratio", 0.4))

        if not execution.attempted:
            return self.result(
                item, 0.0, STATUS_NOT_FOUND, confidence=0.0,
                feedback="No notebook was available to execute.",
                evidence={"discovery_warnings": ctx.discovery_warnings},
            )

        if execution.success:
            return self.result(
                item, item.points, STATUS_PASS, confidence=1.0,
                feedback=(
                    "Notebook executed successfully in "
                    f"{execution.execution_time_seconds:.1f}s."
                ),
                evidence={
                    "execution_time_seconds": execution.execution_time_seconds,
                    "mode": execution.mode,
                },
            )

        if execution.timeout:
            return self.result(
                item, 0.0, STATUS_EXECUTION_ERROR, confidence=1.0,
                feedback=(
                    "Notebook did not finish within the execution timeout. "
                    "Check for an infinite loop or a very expensive cell."
                ),
                evidence={"timeout": True, "log": execution.log[-2000:]},
            )

        # Failing at the very end is worth more than failing at cell 1.
        total_cells = max(ctx.analysis.n_code_cells, 1)
        error_cell = execution.error_cell or 1
        progress = min(max((error_cell - 1) / total_cells, 0.0), 1.0)
        score = item.points * partial_ratio * progress
        return self.result(
            item, score, STATUS_EXECUTION_ERROR, confidence=1.0,
            feedback=(
                f"Notebook failed at code cell {error_cell} of {total_cells}: "
                f"{execution.error_message}. Grading continued on the cells that ran."
            ),
            evidence={
                "error_cell": error_cell,
                "error_message": execution.error_message,
                "traceback": execution.traceback[-4000:],
                "cells_before_failure": error_cell - 1,
                "total_code_cells": total_cells,
            },
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, type[AssignmentGrader]] = {}


def register(cls: type[AssignmentGrader]) -> type[AssignmentGrader]:
    _REGISTRY[cls.assignment_id] = cls
    return cls


def get_grader(rubric: Rubric) -> AssignmentGrader:
    """Return the grader for a rubric, falling back to the generic base."""
    from . import hw1, hw2  # noqa: F401  (importing registers the graders)

    cls = _REGISTRY.get(rubric.id, AssignmentGrader)
    return cls(rubric)


def registered_assignments() -> list[str]:
    from . import hw1, hw2  # noqa: F401

    return sorted(_REGISTRY)


__all__ = [
    "AssignmentGrader",
    "GradingContext",
    "get_grader",
    "register",
    "registered_assignments",
    "STATUS_PASS",
    "STATUS_PARTIAL",
    "STATUS_FAIL",
    "STATUS_MANUAL_REVIEW",
    "STATUS_NOT_FOUND",
    "STATUS_EXECUTION_ERROR",
]
