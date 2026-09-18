"""YAML rubric loading (design.md section 20).

A rubric file declares the assignment, its point breakdown, and per-item
``config`` blocks. Expected values (Center City ZIPs, tolerances, the final
answer) live here rather than in code so a TA can correct them against the
official solution without touching Python.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

RUBRIC_DIR = Path(__file__).resolve().parent.parent / "rubrics"

VALID_TYPES = {
    "execution",
    "structural",
    "deterministic",
    "hidden_test",
    "qualitative",
}


@dataclass
class RubricItem:
    id: str
    name: str
    points: float
    type: str = "deterministic"
    description: str = ""
    config: dict[str, Any] = field(default_factory=dict)

    @property
    def is_qualitative(self) -> bool:
        return self.type == "qualitative"


@dataclass
class Rubric:
    id: str
    name: str
    version: str
    total_points: float
    items: list[RubricItem]
    settings: dict[str, Any] = field(default_factory=dict)
    probe: dict[str, Any] = field(default_factory=dict)
    discovery: dict[str, Any] = field(default_factory=dict)
    # Data the instructor supplies for every submission (design.md §16-17).
    data: dict[str, Any] = field(default_factory=dict)
    source_path: str | None = None

    def item(self, rubric_id: str) -> RubricItem | None:
        for i in self.items:
            if i.id == rubric_id:
                return i
        return None

    @property
    def requires_data(self) -> bool:
        return bool(self.data.get("required"))

    @property
    def offers_data(self) -> bool:
        """Whether the sidebar should let a TA supply data for this assignment.

        Assignment 3 does not *require* its zip — it is graded from the outputs
        each student saved — but supplying it lets the grader re-run every
        notebook and confirm them, so the option has to be there.
        """
        return bool(self.data.get("required") or self.data.get("optional"))

    @property
    def declared_points(self) -> float:
        return round(sum(i.points for i in self.items), 2)

    def label(self) -> str:
        return f"{self.name} (rubric {self.version})"


class RubricError(ValueError):
    """Raised when a rubric file is missing or structurally invalid."""


def load_rubric(path: str | Path) -> Rubric:
    path = Path(path)
    if not path.exists():
        raise RubricError(f"Rubric file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - depends on user file
        raise RubricError(f"Could not parse {path.name}: {exc}") from exc

    assignment = data.get("assignment") or {}
    if not assignment.get("id"):
        raise RubricError(f"{path.name}: 'assignment.id' is required")

    raw_items = data.get("rubric") or []
    if not raw_items:
        raise RubricError(f"{path.name}: 'rubric' must contain at least one item")

    items: list[RubricItem] = []
    seen: set[str] = set()
    for raw in raw_items:
        item_id = raw.get("id")
        if not item_id:
            raise RubricError(f"{path.name}: every rubric item needs an 'id'")
        if item_id in seen:
            raise RubricError(f"{path.name}: duplicate rubric id '{item_id}'")
        seen.add(item_id)
        item_type = raw.get("type", "deterministic")
        if item_type not in VALID_TYPES:
            raise RubricError(
                f"{path.name}: rubric item '{item_id}' has unknown type '{item_type}'. "
                f"Expected one of {sorted(VALID_TYPES)}"
            )
        items.append(
            RubricItem(
                id=item_id,
                name=raw.get("name", item_id),
                points=float(raw.get("points", 0)),
                type=item_type,
                description=raw.get("description", ""),
                config=raw.get("config") or {},
            )
        )

    rubric = Rubric(
        id=assignment["id"],
        name=assignment.get("name", assignment["id"]),
        version=assignment.get("version", f"{assignment['id']}-v1"),
        total_points=float(assignment.get("total_points", sum(i.points for i in items))),
        items=items,
        settings=data.get("settings") or {},
        probe=data.get("probe") or {},
        discovery=data.get("discovery") or {},
        data=data.get("data") or {},
        source_path=str(path),
    )

    if abs(rubric.declared_points - rubric.total_points) > 1e-6:
        raise RubricError(
            f"{path.name}: rubric items sum to {rubric.declared_points} "
            f"but assignment.total_points is {rubric.total_points}"
        )
    return rubric


def available_rubrics(directory: str | Path = RUBRIC_DIR) -> dict[str, Path]:
    """Map assignment id -> rubric path for every parsable rubric on disk."""
    directory = Path(directory)
    found: dict[str, Path] = {}
    if not directory.exists():
        return found
    for path in sorted(directory.glob("*.y*ml")):
        try:
            rubric = load_rubric(path)
        except RubricError:
            continue
        found[rubric.id] = path
    return found
