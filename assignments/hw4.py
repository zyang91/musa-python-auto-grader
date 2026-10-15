"""Assignment 4 autograder — street networks and web scraping.

This assignment is graded **without running the notebook** (``execution: never``
in ``rubrics/hw4.yaml``). Every step of it talks to a server that is not ours —
ArcGIS Open Data for the planning districts, the OpenStreetMap Overpass API for
the street network, and five pages of Craigslist through a real browser — so a
re-run would repeat all of those requests once per student. The service starts
no kernel, container or browser for these submissions in any execution mode.

What is graded instead is the file the student handed in, read two ways:

* **The code they wrote.** Lines the template already provides are set aside
  first, cell by cell (``SubmittedCode``), so the scaffold — the
  ``driver.get(url)`` and ``pd.concat`` inside the provided scraping loop, the
  ``def format_price(price_string):`` stub — earns nothing by being left in
  place. Each step is then a list of requirements in the rubric, a regex each,
  so a TA can widen one without touching Python.
* **The outputs their own run saved.** The crash count, the scraping log, the
  results table, the histograms, the Folium map and the Altair spec are all in
  the notebook as the student ran it. Reference numbers come only from the
  assignment text ("about 3,750 crashes", 120 listings a page) and only raise
  confidence; a number outside its range sends an item to a person, it never
  costs points on its own.

The single exception is 2.5: the three ``format_*`` functions are cut out of the
notebook and called on their own in the network-less Docker sandbox
(``grader/function_sandbox.py``). Nothing else from the notebook goes with them.

Review policy as elsewhere: full marks when the evidence is there, and anything
short of full marks reaches a person (``grader/scoring.py``).
"""

from __future__ import annotations

import ast
import io
import re
import statistics
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import nbformat

from grader import charts as chartlib
from grader.answers import FIGURE_RE, SOURCE_SUBMITTED, NotebookAnswers, read_answers
from grader.function_sandbox import (
    STATUS_RAN,
    STATUS_SKIPPED,
    FunctionTestRun,
    extract_functions,
    matches,
)
from grader.models import (
    STATUS_FAIL,
    STATUS_MANUAL_REVIEW,
    STATUS_NOT_FOUND,
    STATUS_PARTIAL,
    STATUS_PASS,
    RubricItemResult,
)
from grader.notebook import _clean_cell, _parse_cell
from grader.rubric import RubricItem

from .base import AssignmentGrader, GradingContext, register

ROOT = Path(__file__).resolve().parent.parent

# Where Part 2 begins: the first cell that touches the browser or the soup.
PART2_RE = re.compile(r"webdriver|BeautifulSoup|craigslist|page_source")
HIST_RE = re.compile(r"\bhist\s*\(|kind\s*=\s*[\"']hist[\"']|\.plot\.hist\s*\(|histplot\s*\(")
READ_CSV_RE = re.compile(r"read_csv\s*\(")

# Confidence for a step judged from source alone. Above the review threshold:
# the code is the evidence the step asks for. Lower when the student's own run
# shows that step raising.
SOURCE_CONFIDENCE = 0.85
CORROBORATED_CONFIDENCE = 0.95
DOUBT_CONFIDENCE = 0.6


# ---------------------------------------------------------------------------
# The student's code, with the template's scaffold set aside
# ---------------------------------------------------------------------------

def strip_comments(source: str) -> str:
    """Drop comments without touching a ``#`` inside a string (``#search=1~``)."""
    cleaned = _clean_cell(source or "")
    try:
        tokens = [
            token for token in tokenize.generate_tokens(io.StringIO(cleaned).readline)
            if token.type != tokenize.COMMENT
        ]
        return tokenize.untokenize(tokens)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # A cell that does not tokenize (the template's blank `soup = `): drop
        # whole-line comments only.
        return "\n".join(
            line for line in cleaned.splitlines() if not line.lstrip().startswith("#")
        )


def _lines(code: str) -> list[str]:
    return [line.strip() for line in code.splitlines() if line.strip()]


@dataclass
class CodeCell:
    number: int
    source: str
    code: str
    # ``code`` minus the lines of the template cell this cell was filled in from.
    student: str
    parses: bool
    from_template: bool = False


@dataclass
class SubmittedCode:
    cells: list[CodeCell] = field(default_factory=list)
    part2_start: int = 10**9

    @property
    def student_text(self) -> str:
        return "\n".join(cell.student for cell in self.cells)

    def part1(self) -> list[CodeCell]:
        return [c for c in self.cells if c.number < self.part2_start]

    def part2(self) -> list[CodeCell]:
        return [c for c in self.cells if c.number >= self.part2_start]

    def text(self, cells: Iterable[CodeCell]) -> str:
        return "\n".join(cell.student for cell in cells)


def _template_cells(path: Path | None) -> list[list[str]]:
    if path is None or not path.is_file():
        return []
    try:
        notebook = nbformat.read(str(path), as_version=4)
    except Exception:
        return []
    cells = []
    for cell in notebook.cells:
        if cell.get("cell_type") != "code":
            continue
        lines = _lines(strip_comments(cell.get("source") or ""))
        if lines:
            cells.append(lines)
    return cells


def build_code(code_cells: list[str], template_path: Path | None) -> SubmittedCode:
    """Each code cell, with any template scaffold it was filled in from removed.

    A cell counts as filled in from a template cell when it keeps at least half
    of that cell's lines. Only then are those lines removed — so a student who
    writes ``driver.get(url)`` in their own 2.1 cell keeps it, even though the
    same line is also part of the provided scraping loop.
    """
    templates = _template_cells(template_path)
    submitted = SubmittedCode()
    for number, source in enumerate(code_cells, start=1):
        code = strip_comments(source)
        lines = _lines(code)
        scaffold: set[str] = set()
        for template in templates:
            shared = set(template) & set(lines)
            if shared and len(shared) >= 0.5 * len(set(template)):
                scaffold |= set(template)
        student = "\n".join(line for line in lines if line not in scaffold)
        parses = not code.strip() or _parse_cell(code) is not None
        submitted.cells.append(
            CodeCell(number, source, code, student, parses, from_template=bool(scaffold))
        )
        if submitted.part2_start == 10**9 and PART2_RE.search(code):
            submitted.part2_start = number
    return submitted


# ---------------------------------------------------------------------------
# Requirements: a list of regexes per step, from the rubric
# ---------------------------------------------------------------------------

def _hit(spec: Any, text: str) -> bool:
    """A pattern, or a list of patterns that must all match."""
    if isinstance(spec, (list, tuple)):
        return all(re.search(p, text) for p in spec)
    return bool(re.search(str(spec), text))


def requirement_met(requirement: dict[str, Any], text: str) -> bool:
    any_of = requirement.get("any") or []
    all_of = requirement.get("all") or []
    return (not any_of or any(_hit(p, text) for p in any_of)) and all(
        re.search(p, text) for p in all_of
    )


def _walk_encodings(spec: Any, found: list[dict[str, Any]], depth: int = 0) -> None:
    if depth > 8 or not isinstance(spec, dict):
        return
    if isinstance(spec.get("encoding"), dict):
        found.append(spec)
    for key in ("layer", "hconcat", "vconcat", "concat"):
        for child in spec.get(key) or []:
            _walk_encodings(child, found, depth + 1)
    if isinstance(spec.get("spec"), dict):
        _walk_encodings(spec["spec"], found, depth + 1)


def _field(definition: Any) -> str:
    if isinstance(definition, dict):
        return str(definition.get("field", "")).split(":")[0]
    if isinstance(definition, str):
        return definition.split(":")[0]
    return ""


def _scales_bound(spec: Any, depth: int = 0) -> bool:
    """``.interactive()``: an interval selection bound to the scales."""
    if depth > 8 or not isinstance(spec, dict):
        return False
    for param in spec.get("params") or []:
        if isinstance(param, dict) and param.get("bind") == "scales":
            return True
    for selection in (spec.get("selection") or {}).values():  # Vega-Lite 4
        if isinstance(selection, dict) and selection.get("bind") == "scales":
            return True
    children = [spec.get("spec")] + list(spec.get("layer") or []) + list(
        spec.get("hconcat") or []) + list(spec.get("vconcat") or [])
    return any(_scales_bound(child, depth + 1) for child in children if child)


def _dataset_rows(spec: dict[str, Any]) -> list[dict[str, Any]]:
    datasets = spec.get("datasets") or {}
    rows: list[dict[str, Any]] = []
    for values in datasets.values():
        if isinstance(values, list) and len(values) > len(rows):
            rows = [r for r in values if isinstance(r, dict)]
    if not rows and isinstance((spec.get("data") or {}).get("values"), list):
        rows = [r for r in spec["data"]["values"] if isinstance(r, dict)]
    return rows


@register
class HW4Grader(AssignmentGrader):
    assignment_id = "hw4"

    # -- shared evidence ---------------------------------------------------
    def template_path(self) -> Path | None:
        configured = self.rubric.settings.get("template_notebook")
        if not configured:
            return None
        path = Path(configured)
        return path if path.is_absolute() else ROOT / path

    def code(self, ctx: GradingContext) -> SubmittedCode:
        cached = ctx.cache.get("hw4_code")
        if cached is None:
            cached = build_code(list(ctx.analysis.code_cells), self.template_path())
            ctx.cache["hw4_code"] = cached
        return cached

    def answers(self, ctx: GradingContext) -> NotebookAnswers:
        cached = ctx.cache.get("hw4_answers")
        if cached is None:
            cached = read_answers(ctx.analysis.path, SOURCE_SUBMITTED)
            ctx.cache["hw4_answers"] = cached
        return cached

    def raw_outputs(self, ctx: GradingContext) -> dict[int, list[dict[str, Any]]]:
        """Saved outputs by code-cell number, for what ``answers`` does not keep."""
        cached = ctx.cache.get("hw4_outputs")
        if cached is None:
            cached = {}
            try:
                notebook = nbformat.read(str(ctx.analysis.path), as_version=4)
            except Exception:
                notebook = None
            number = 0
            for cell in (notebook.cells if notebook is not None else []):
                if cell.get("cell_type") != "code":
                    continue
                number += 1
                cached[number] = list(cell.get("outputs") or [])
            ctx.cache["hw4_outputs"] = cached
        return cached

    def answer_cell(self, ctx: GradingContext, number: int):
        for cell in self.answers(ctx).cells:
            if cell.code_cell == number:
                return cell
        return None

    # -- scoring helpers ----------------------------------------------------
    def scored(
        self,
        item: RubricItem,
        deductions: list[tuple[float, str]],
        evidence: dict[str, Any],
        confidence: float,
        pass_feedback: str,
        notes: list[str] | None = None,
    ) -> RubricItemResult:
        score = max(float(item.points) - sum(points for points, _ in deductions), 0.0)
        suffix = (" " + " ".join(notes)) if notes else ""
        if not deductions:
            return self.result(item, score, STATUS_PASS, confidence,
                               pass_feedback + suffix, evidence)
        feedback = "Not found: " + "; ".join(
            f"{why} (-{points:g})" for points, why in deductions
        ) + "." + suffix
        status = STATUS_PARTIAL if score > 0 else STATUS_FAIL
        return self.result(item, score, status, confidence, feedback, evidence)

    def run_requirements(
        self, requirements: list[dict[str, Any]], text: str
    ) -> tuple[list[tuple[float, str]], list[str]]:
        deductions: list[tuple[float, str]] = []
        met: list[str] = []
        for requirement in requirements:
            label = str(requirement.get("label", "requirement"))
            if requirement_met(requirement, text):
                met.append(label)
            else:
                deductions.append((float(requirement.get("points", 0)), label))
        return deductions, met

    def part_cells(self, ctx: GradingContext, item: RubricItem) -> list[CodeCell]:
        """The cells of the Part this step belongs to (``part:`` in the rubric).

        Without it a Part 1 ``len(crashes)`` would satisfy "the number of
        listings is checked" in Part 2.
        """
        code = self.code(ctx)
        part = item.config.get("part")
        if part == 1:
            return code.part1()
        if part == 2:
            return code.part2()
        return list(code.cells)

    def anchor_cells(self, ctx: GradingContext, item: RubricItem) -> list[CodeCell]:
        patterns = item.config.get("anchor") or []
        return [
            cell for cell in self.part_cells(ctx, item)
            if cell.student and any(re.search(p, cell.student) for p in patterns)
        ]

    def run_state(self, ctx: GradingContext, cells: list[CodeCell]) -> tuple[float, str]:
        """How far the student's own run of these cells backs the source up."""
        answered = [self.answer_cell(ctx, cell.number) for cell in cells]
        answered = [a for a in answered if a is not None]
        if answered and all(a.errored for a in answered):
            first = answered[0]
            return DOUBT_CONFIDENCE, (
                f"In the student's own run, code cell {first.code_cell} raised "
                f"{first.error}, so the step may not have worked as written."
            )
        if any(a.has_output and not a.errored for a in answered):
            return CORROBORATED_CONFIDENCE, ""
        return SOURCE_CONFIDENCE, ""

    def source_steps(self, ctx: GradingContext, item: RubricItem) -> RubricItemResult:
        """A step graded on what the student wrote, backed by their saved run."""
        code = self.code(ctx)
        deductions, met = self.run_requirements(
            item.config.get("requirements") or [], code.text(self.part_cells(ctx, item))
        )
        cells = self.anchor_cells(ctx, item)
        confidence, note = self.run_state(ctx, cells)
        evidence: dict[str, Any] = {
            "graded_from": "the submitted notebook's code (not executed)",
            "requirements_met": met,
            "requirements_missing": [why for _, why in deductions],
            "cells": [cell.number for cell in cells][:6],
            "code": "\n\n".join(cell.student for cell in cells)[:1500],
        }
        if note:
            evidence["saved_run"] = note
        return self.scored(
            item, deductions, evidence, confidence,
            f"All {len(met)} parts of this step are in the notebook.",
            [note] if note else None,
        )

    # =====================================================================
    # Execution: the student's own saved run
    # =====================================================================
    def check_notebook_execution(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        """Was the notebook run through before it was handed in?

        This grader never runs it (see the module docstring), so the question is
        answered from the state it was saved in, exactly as Assignment 2 does.
        """
        config = item.config
        answers = self.answers(ctx)
        n_cells = ctx.analysis.n_code_cells
        if not n_cells:
            return self.result(item, 0.0, STATUS_NOT_FOUND, 1.0,
                               "The notebook contains no code cells.", {"n_code_cells": 0})

        ran = sum(1 for cell in answers.cells if cell.has_output and not cell.errored)
        errors = answers.error_cells
        deductions: list[tuple[float, str]] = []
        if not ran and not errors:
            deductions.append((float(config.get("no_outputs_penalty", 7)),
                               "the notebook was handed in with no saved output at all, "
                               "so there is no record of it being run"))
        elif ran / n_cells < float(config.get("min_output_coverage", 0.3)):
            deductions.append((float(config.get("low_coverage_penalty", 3)),
                               f"only {ran} of {n_cells} code cells carry saved output, "
                               "so the notebook looks partly run"))
        if errors:
            each = float(config.get("error_penalty_each", 2))
            cap = float(config.get("max_error_penalty", 6))
            deductions.append((min(each * len(errors), cap),
                               f"{len(errors)} cell(s) show an error in the student's own "
                               f"run, starting at code cell {errors[0].code_cell}: "
                               f"{errors[0].error}"))

        evidence = {
            "graded_from": "the submitted notebook's saved outputs",
            "executed_by_grader": False,
            "why_not_executed": (
                "Assignment 4 scrapes Craigslist and downloads from OpenStreetMap and "
                "ArcGIS; the rubric forbids re-running it (execution: never)."
            ),
            "n_code_cells": n_cells,
            "cells_with_output": ran,
            "errors_in_saved_run": [
                {"code_cell": c.code_cell, "error": c.error} for c in errors[:5]
            ],
        }
        score = max(float(item.points) - sum(p for p, _ in deductions), 0.0)
        if not deductions:
            return self.result(
                item, score, STATUS_PASS, 0.9,
                f"The submitted notebook shows a complete run: {ran} of {n_cells} code "
                "cells carry output and none shows an error.",
                evidence,
            )
        return self.result(
            item, score, STATUS_PARTIAL if score > 0 else STATUS_FAIL, 0.9,
            "Deductions: " + "; ".join(f"{why} (-{p:g})" for p, why in deductions) + ".",
            evidence,
        )

    # =====================================================================
    # Part 1
    # =====================================================================
    check_district_polygon = source_steps
    check_street_network = source_steps
    check_network_edges = source_steps
    check_crash_data = source_steps
    check_reproject = source_steps
    check_nearest_edges = source_steps
    check_merge_edges = source_steps
    check_crash_index = source_steps
    check_selenium_driver = source_steps
    check_soup = source_steps

    def check_crash_geodataframe(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        """The steps, plus the one mistake worth naming: latitude passed as x."""
        result = self.source_steps(ctx, item)
        swapped = self._swapped_coordinates(self.code(ctx).cells)
        if not swapped:
            return result
        penalty = float(item.config.get("swapped_coordinates_penalty", 2))
        score = max(result.automatic_score - penalty, 0.0)
        result.evidence["swapped_coordinates"] = swapped
        swap_note = (
            f"Latitude is passed as x: `{swapped}`. points_from_xy takes longitude "
            f"(DEC_LONG) as x and latitude (DEC_LAT) as y (-{penalty:g})."
        )
        feedback = swap_note if result.status == STATUS_PASS else f"{result.feedback} {swap_note}"
        return self.result(
            item, score, STATUS_PARTIAL if score > 0 else STATUS_FAIL, result.confidence,
            feedback, result.evidence,
        )

    @staticmethod
    def _swapped_coordinates(cells: list[CodeCell]) -> str:
        for cell in cells:
            parsed = _parse_cell(cell.code)
            if parsed is None:
                continue
            tree, source = parsed
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if name != "points_from_xy":
                    continue
                x_arg = next((k.value for k in node.keywords if k.arg == "x"), None)
                if x_arg is None and node.args:
                    x_arg = node.args[0]
                if x_arg is None:
                    continue
                x_source = ast.get_source_segment(source, x_arg) or ""
                if "DEC_LAT" in x_source and "DEC_LONG" not in x_source:
                    return (ast.get_source_segment(source, node) or "")[:200]
        return ""

    def _counts_near(
        self, ctx: GradingContext, cells: list[CodeCell], span: int = 2
    ) -> list[int]:
        """Whole numbers the student's run showed in or just after these cells."""
        numbers: list[int] = []
        wanted = {c.number + offset for c in cells for offset in range(span + 1)}
        for answer in self.answers(ctx).cells:
            if answer.code_cell not in wanted or answer.errored:
                continue
            for value in list(answer.shown) + list(answer.row_counts) + [
                rows for rows, _ in answer.shapes
            ]:
                if float(value).is_integer() and value >= 10:
                    numbers.append(int(value))
        return numbers

    def check_trim_crashes(self, ctx: GradingContext, item: RubricItem) -> RubricItemResult:
        """The steps; the template's "about 3,750" only decides who looks again."""
        result = self.source_steps(ctx, item)
        low, high = item.config.get("count_range", [3000, 4500])
        counts = self._counts_near(ctx, self.anchor_cells(ctx, item))
        in_range = [n for n in counts if low <= n <= high]
        result.evidence["counts_shown"] = counts[:10]
        result.evidence["expected_count"] = (
            f"about {item.config.get('expected_count', 3750):,} (accepted {low:,}-{high:,})"
        )
        if in_range:
            result.confidence = max(result.confidence, CORROBORATED_CONFIDENCE)
            result.feedback += f" The saved run shows {in_range[0]:,} crashes in Center City."
        elif counts:
            result.confidence = min(result.confidence, DOUBT_CONFIDENCE)
            result.feedback += (
                f" The saved run shows {counts[0]:,} near this step, not the roughly "
                f"{item.config.get('expected_count', 3750):,} the template expects — "
                "please check the trimming."
            )
        return result

    def check_crash_counts(self, ctx: GradingContext, item: RubricItem) -> RubricItemResult:
        result = self.source_steps(ctx, item)
        columns = item.config.get("expected_columns") or []
        shown = self.answers(ctx).frames_with_columns(columns) if columns else []
        if shown:
            result.confidence = max(result.confidence, CORROBORATED_CONFIDENCE)
            result.evidence["frame_shown_in_cell"] = shown[0].code_cell
        return result

    # -- charts ------------------------------------------------------------
    def hist_cells(self, ctx: GradingContext, cells: list[CodeCell]) -> list[dict[str, Any]]:
        """Histogram cells, with how many histograms each saved run shows."""
        found = []
        for cell in cells:
            if not HIST_RE.search(cell.student):
                continue
            answer = self.answer_cell(ctx, cell.number)
            images = answer.images if answer else 0
            axes = sum(int(a) for _, _, a in FIGURE_RE.findall(answer.text)) if answer else 0
            errored = bool(answer and answer.errored)
            drawn = 0 if errored and not images else max(images, axes if images else 0)
            found.append({
                "code_cell": cell.number,
                "histograms_drawn": drawn,
                "errored": errored,
                "error": answer.error if answer and answer.errored else "",
                "source": cell.student[:500],
                "labels": chartlib.aesthetic_signals(cell.student),
            })
        return found

    def check_crash_index_histogram(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        cells = self.hist_cells(ctx, self.code(ctx).part1())
        evidence = {"graded_from": "the submitted notebook's saved outputs",
                    "histogram_cells": cells}
        rendered = [c for c in cells if c["histograms_drawn"]]
        if rendered:
            return self.result(
                item, float(item.config.get("rendered_points", item.points)), STATUS_PASS,
                CORROBORATED_CONFIDENCE,
                f"A histogram of the crash index is drawn in code cell {rendered[0]['code_cell']}.",
                evidence,
            )
        if cells:
            points = float(item.config.get("source_only_points", item.points / 2))
            return self.result(
                item, points, STATUS_PARTIAL, SOURCE_CONFIDENCE,
                f"A histogram is coded in cell {cells[0]['code_cell']}, but the submitted "
                "notebook shows no rendered plot for it.",
                evidence,
            )
        return self.result(item, 0.0, STATUS_FAIL, SOURCE_CONFIDENCE,
                           "No histogram of the crash index was found in Part 1.", evidence)

    def check_crash_index_map(self, ctx: GradingContext, item: RubricItem) -> RubricItemResult:
        config = item.config
        cells = [
            c for c in self.code(ctx).part1()
            if any(re.search(p, c.student) for p in config.get("source_any", []))
        ]
        markers = [m.lower() for m in config.get("saved_markers", [])]
        rendered_in = None
        for cell in cells:
            for output in self.raw_outputs(ctx).get(cell.number, []):
                html = chartlib._output_text((output.get("data") or {}).get("text/html"))
                if html and any(m in html.lower() for m in markers):
                    rendered_in = cell.number
                    break
            if rendered_in:
                break
        deductions: list[tuple[float, str]] = []
        if not cells:
            deductions.append((float(config.get("source_points", 2)),
                               "an interactive Folium map (.explore() or folium) of the streets"))
        if rendered_in is None:
            deductions.append((float(config.get("rendered_points", 2)),
                               "the rendered map in the submitted notebook's output"))
        evidence = {
            "map_cells": [c.number for c in cells],
            "rendered_in_cell": rendered_in,
            "colored_by": re.findall(r"column\s*=\s*([^,)]+)", "\n".join(c.student for c in cells))[:3],
            "code": "\n\n".join(c.student for c in cells)[:1000],
        }
        return self.scored(
            item, deductions, evidence,
            CORROBORATED_CONFIDENCE if rendered_in else SOURCE_CONFIDENCE,
            f"An interactive map is drawn and saved in code cell {rendered_in}.",
        )

    # =====================================================================
    # Part 2
    # =====================================================================
    def check_listing_elements(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        result = self.source_steps(ctx, item)
        low, high = item.config.get("count_range", [20, 1000])
        cells = [c for c in self.anchor_cells(ctx, item) if "len(" in c.student]
        counts = [n for n in self._counts_near(ctx, cells, span=1) if low <= n <= high]
        result.evidence["listing_counts_shown"] = counts[:5]
        if counts:
            result.confidence = max(result.confidence, CORROBORATED_CONFIDENCE)
            result.feedback += f" The saved run shows {counts[0]} listings on the page."
        return result

    def check_first_listing_fields(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        config = item.config
        code = self.code(ctx)
        loop = self._loop_cell(ctx)
        cells = [c for c in code.part2() if loop is None or c.number < loop.number]
        deductions, met = self.run_requirements(
            config.get("requirements") or [], code.text(cells)
        )
        printed = "\n".join(
            a.text for a in self.answers(ctx).cells
            if a.code_cell in {c.number for c in cells} and not a.errored
        )
        hits = {
            name: bool(re.search(pattern, printed))
            for name, pattern in (config.get("printed_patterns") or {}).items()
        }
        if sum(hits.values()) < int(config.get("min_printed", 2)):
            deductions.append((float(config.get("printed_points", 2)),
                               "the printed price, bedrooms and size of the first listing "
                               "in the saved output"))
        evidence = {
            "requirements_met": met,
            "printed_fields_seen": hits,
            "printed_output": printed[:800],
        }
        return self.scored(
            item, deductions, evidence,
            CORROBORATED_CONFIDENCE if printed else SOURCE_CONFIDENCE,
            "The first listing is printed, and its fields are extracted and shown.",
        )

    def check_format_functions(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        """Called in the sandbox when possible; otherwise read, and sent to a TA."""
        config = item.config
        per_function = float(config.get("points_per_function", 3))
        functions: dict[str, Any] = config.get("functions") or {}
        run: FunctionTestRun | None = ctx.function_tests.get(item.id)
        if run is None:
            run = FunctionTestRun(status=STATUS_SKIPPED,
                       reason="The sandbox was not invoked for this grading run.",
                       extracted=extract_functions(ctx.analysis.code_cells, list(functions)))
        extracted = run.extracted

        if run.status != STATUS_RAN:
            return self._format_functions_unrun(item, run, functions, per_function)

        score = 0.0
        lines: list[str] = []
        detail: dict[str, Any] = {}
        for name, spec in functions.items():
            cases = (spec or {}).get("cases", [])
            if name not in extracted.functions:
                reason = extracted.rejected.get(name, "not defined in the notebook")
                lines.append(f"`{name}`: {reason} (0/{per_function:g})")
                detail[name] = {"extracted": False, "reason": reason}
                continue
            outcomes = []
            for index, case in enumerate(cases):
                entry = run.case(f"{name}#{index}")
                ok = matches(entry, case.get("expected"))
                outcomes.append({
                    "input": case.get("input"), "expected": case.get("expected"),
                    "ok": ok,
                    "got": (entry or {}).get("repr") if (entry or {}).get("ok")
                    else (entry or {}).get("error", "no result"),
                })
            passed = sum(1 for o in outcomes if o["ok"])
            earned = per_function * passed / max(len(cases), 1)
            score += earned
            detail[name] = {"extracted": True, "cases": outcomes,
                            "source": extracted.functions[name][:600]}
            if passed == len(cases):
                lines.append(f"`{name}` returns the right number for all {len(cases)} inputs.")
            else:
                failed = next(o for o in outcomes if not o["ok"])
                lines.append(
                    f"`{name}` passes {passed} of {len(cases)}: "
                    f"{failed['input']!r} should give {failed['expected']}, "
                    f"got {failed['got']} ({earned:g}/{per_function:g})."
                )
        evidence = {
            "how": "functions extracted on their own and called in the network-less sandbox",
            "functions": detail,
            "imports_sent": extracted.imports,
        }
        status = STATUS_PASS if score >= float(item.points) else (
            STATUS_PARTIAL if score > 0 else STATUS_FAIL)
        return self.result(item, score, status, CORROBORATED_CONFIDENCE, " ".join(lines), evidence)

    def _format_functions_unrun(
        self, item: RubricItem, run: FunctionTestRun, functions: dict[str, Any],
        per_function: float,
    ) -> RubricItemResult:
        """Not called (local mode, or Docker failed): a provisional score for a TA."""
        extracted = run.extracted
        provisional = 0.0
        detail: dict[str, Any] = {}
        for name in functions:
            source = extracted.functions.get(name)
            if not source:
                detail[name] = {"extracted": False,
                                "reason": extracted.rejected.get(name, "not defined")}
                continue
            stub = _is_stub(source)
            detail[name] = {"extracted": True, "looks_unfinished": stub, "source": source[:600]}
            if not stub:
                provisional += per_function / 2
        return self.result(
            item, provisional, STATUS_MANUAL_REVIEW, 0.4,
            f"The functions were not called: {run.reason} The provisional score only "
            "says which functions look finished; please check them by hand.",
            {"sandbox": run.status, "reason": run.reason, "functions": detail},
        )

    def _loop_cell(self, ctx: GradingContext) -> CodeCell | None:
        cached = ctx.cache.get("hw4_loop")
        if cached is not None:
            return cached or None
        config = self.rubric.item("scraping_loop").config if self.rubric.item("scraping_loop") else {}
        loops = [
            c for c in self.code(ctx).part2()
            if any(re.search(p, c.code) for p in config.get("loop_markers", [r"for\s+\w+\s+in\b"]))
            and any(re.search(p, c.code) for p in config.get("driver_markers", [r"\.get\("]))
        ]
        with_log = [c for c in loops if any(self._run_log(ctx, c, config)[:2])]
        chosen = (with_log or loops or [None])[-1]
        ctx.cache["hw4_loop"] = chosen or False
        return chosen

    def _run_log(
        self, ctx: GradingContext, cell: CodeCell, config: dict[str, Any]
    ) -> tuple[list[int], list[str], str, bool]:
        """What the loop printed: listings per page, pages, its log, and if it raised."""
        answer = self.answer_cell(ctx, cell.number)
        if answer is None:
            return [], [], "", False
        patterns = list(config.get("run_log_patterns") or []) + ["", ""]
        counts = [int(n) for n in re.findall(patterns[0], answer.text)] if patterns[0] else []
        pages = re.findall(patterns[1], answer.text) if patterns[1] else []
        return counts, pages, answer.text, answer.errored

    def check_scraping_loop(self, ctx: GradingContext, item: RubricItem) -> RubricItemResult:
        """The loop must be written *and* shown running; a CSV is not a scrape."""
        config = item.config
        code = self.code(ctx)
        loop = self._loop_cell(ctx)
        deductions: list[tuple[float, str]] = []
        evidence: dict[str, Any] = {"graded_from": "the submitted notebook (not executed)"}

        if loop is None:
            for requirement in config.get("implementation") or []:
                deductions.append((float(requirement.get("points", 0)),
                                   str(requirement.get("label"))))
            evidence["loop_cell"] = None
        else:
            evidence["loop_cell"] = loop.number
            evidence["loop_code"] = loop.student[:1500]
            for requirement in config.get("implementation") or []:
                label = str(requirement.get("label"))
                if requirement.get("parses"):
                    ok = loop.parses and bool(loop.student.strip())
                else:
                    ok = requirement_met(requirement, loop.student)
                if not ok:
                    deductions.append((float(requirement.get("points", 0)), label))

        counts, pages, log, raised = (
            self._run_log(ctx, loop, config) if loop else ([], [], "", False)
        )
        positive = [n for n in counts if n > 0]
        evidence["run_log"] = log[:1200]
        evidence["listings_per_page_printed"] = counts[:10]
        evidence["pages_processed_printed"] = len(pages)
        # A student who dropped the template's count print still shows pages run.
        scraped = bool(positive) or (bool(pages) and not counts and not raised)
        if not scraped:
            deductions.append((float(config.get("run_log_points", 2)),
                               "a saved run of the loop showing pages scraped and listings "
                               "found"))
        elif raised:
            evidence["loop_raised"] = True

        columns = config.get("results_columns") or []
        frames = self.answers(ctx).frames_with_columns(columns)
        frames = [f for f in frames if f.code_cell >= code.part2_start]
        rows = sorted({r for f in frames for r in f.row_counts}, reverse=True)
        altair_rows = len(self._scraped_rows(ctx))
        evidence["results_shown_in_cells"] = [f.code_cell for f in frames][:5]
        evidence["results_rows_shown"] = rows[:3]
        evidence["rows_embedded_in_altair_chart"] = altair_rows
        if not frames and not altair_rows:
            deductions.append((float(config.get("results_points", 2)),
                               "the scraped results (price, size, bedrooms, title) shown in "
                               "the saved output"))
        elif not scraped:
            deductions.append((float(config.get("results_points", 2)),
                               "results produced by the scraping loop (a results table is "
                               "shown, but no saved run of the loop produced it)"))

        csv_reads = [c.number for c in code.part2() if READ_CSV_RE.search(c.student)]
        notes: list[str] = []
        if csv_reads:
            evidence["results_read_from_csv_in_cells"] = csv_reads
            if not scraped:
                notes.append(
                    "The notebook reads its listings from a CSV (code cell "
                    f"{csv_reads[0]}) without a saved run of the scraping loop; loading "
                    "saved results does not count as scraping."
                )
        if raised and positive:
            notes.append("The loop raised partway through its saved run, after scraping "
                         f"{len(positive)} page(s).")
        confidence = CORROBORATED_CONFIDENCE if scraped else SOURCE_CONFIDENCE
        if raised:
            confidence = DOUBT_CONFIDENCE
        pages_run = len(positive) or len(pages)
        return self.scored(
            item, deductions, evidence, confidence,
            f"The loop is completed and its saved run scraped {pages_run} page(s)"
            + (f" ({sum(positive)} listings printed)." if positive else "."),
            notes,
        )

    def check_price_histograms(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        config = item.config
        loop = self._loop_cell(ctx)
        cells = [c for c in self.code(ctx).part2() if loop is None or c.number > loop.number]
        found = self.hist_cells(ctx, cells)
        drawn = sum(c["histograms_drawn"] for c in found)
        required = int(config.get("required_count", 2))
        deductions: list[tuple[float, str]] = []
        rendered_points = float(config.get("rendered_points", 2))
        if drawn < required:
            missing = rendered_points if drawn == 0 else rendered_points / 2
            deductions.append((missing, f"{required} rendered histograms (price, and price "
                                        f"per square foot); the saved output shows {drawn}"))
        labels = {"title": False, "x_label": False, "y_label": False}
        for cell in found:
            for key in labels:
                labels[key] = labels[key] or cell["labels"].get(key, False)
        if not all(labels.values()):
            missing = [k.replace("_", " ") for k, v in labels.items() if not v]
            deductions.append((float(config.get("labels_points", 1)),
                               "axis labels and a title (" + ", ".join(missing) + " missing)"))
        evidence = {"histogram_cells": found, "labels": labels,
                    "price_per_sqft_computed": bool(re.search(
                        r"/\s*[\w.\[\]\"']*size", self.code(ctx).text(cells)))}
        return self.scored(
            item, deductions, evidence,
            CORROBORATED_CONFIDENCE if drawn else SOURCE_CONFIDENCE,
            f"{drawn} labelled histograms are drawn.",
        )

    def _altair_specs(self, ctx: GradingContext) -> list[tuple[int, dict[str, Any]]]:
        cached = ctx.cache.get("hw4_altair")
        if cached is None:
            cached = []
            start = self.code(ctx).part2_start
            for number, outputs in sorted(self.raw_outputs(ctx).items()):
                if number < start:
                    continue
                for output in outputs:
                    for spec in chartlib.extract_specs(output):
                        cached.append((number, spec))
            ctx.cache["hw4_altair"] = cached
        return cached

    def _scraped_rows(self, ctx: GradingContext) -> list[dict[str, Any]]:
        best: list[dict[str, Any]] = []
        for _, spec in self._altair_specs(ctx):
            rows = _dataset_rows(spec)
            if len(rows) > len(best):
                best = rows
        return best

    def check_altair_scatter(self, ctx: GradingContext, item: RubricItem) -> RubricItemResult:
        config = item.config
        wanted = config.get("encodings") or {"x": "price", "y": "size", "color": "bedrooms"}
        best: tuple[int, dict[str, Any], dict[str, Any]] | None = None
        for number, spec in self._altair_specs(ctx):
            views: list[dict[str, Any]] = []
            _walk_encodings(spec, views)
            for view in views:
                encoding = view["encoding"]
                hits = sum(1 for ch, f in wanted.items() if _field(encoding.get(ch)) == f)
                if best is None or hits > sum(
                    1 for ch, f in wanted.items() if _field(best[2].get(ch)) == f
                ):
                    best = (number, spec, encoding)

        evidence: dict[str, Any] = {"graded_from": "the chart's Vega-Lite spec in the saved output"}
        if best is None:
            source = self.code(ctx).text(self.code(ctx).part2())
            if re.search(r"\balt\.Chart\(", source):
                return self.result(
                    item, 0.0, STATUS_MANUAL_REVIEW, 0.4,
                    "An Altair chart is coded, but the submitted notebook carries no "
                    "rendered chart to read. Please check it by hand.",
                    {"code": source[-1200:]},
                )
            return self.result(item, 0.0, STATUS_FAIL, SOURCE_CONFIDENCE,
                               "No Altair chart was found in Part 2.", evidence)

        number, spec, encoding = best
        deductions: list[tuple[float, str]] = []
        wrong = {ch: _field(encoding.get(ch)) for ch, f in wanted.items()
                 if _field(encoding.get(ch)) != f}
        if wrong:
            share = len(wrong) / len(wanted)
            deductions.append((float(config.get("encoding_points", 1.5)) * share,
                               "price on x, size on y and colour by bedrooms (found "
                               + ", ".join(f"{ch}={v or 'none'}" for ch, v in wrong.items())
                               + ")"))
        tooltip = encoding.get("tooltip")
        tooltip_fields = [
            _field(t) for t in (tooltip if isinstance(tooltip, list) else [tooltip]) if t
        ]
        if not tooltip_fields:
            deductions.append((float(config.get("tooltip_points", 0.5)), "a tooltip"))
        if not _scales_bound(spec):
            deductions.append((float(config.get("interactive_points", 1)),
                               "pan and zoom (.interactive())"))

        rows = _dataset_rows(spec)
        evidence.update({
            "chart_cell": number,
            "encoding": {ch: _field(encoding.get(ch)) for ch in ("x", "y", "color")},
            "tooltip_fields": tooltip_fields,
            "interactive": _scales_bound(spec),
            "rows_in_chart": len(rows),
        })
        notes: list[str] = []
        ratios = []
        for row in rows:
            try:
                ratios.append(float(row["price"]) / float(row["size"]))
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                continue
        if ratios:
            median = statistics.median(ratios)
            evidence["median_price_per_sqft"] = round(median, 2)
            low, high = config.get("price_per_sqft_range", [0.5, 5.0])
            if not low <= median <= high:
                notes.append(f"The charted listings have a median of ${median:.2f} per sq ft, "
                             "far from the ~$1.5 the assignment expects; the scraped "
                             "numbers may be mis-parsed.")
        confidence = CORROBORATED_CONFIDENCE if not notes else DOUBT_CONFIDENCE
        return self.scored(
            item, deductions, evidence, confidence,
            f"The chart in code cell {number} plots price against size coloured by "
            "bedrooms, with a tooltip and pan/zoom.",
            notes,
        )


def _is_stub(source: str) -> bool:
    """The template's ``return`` with nothing after it — or no return at all."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return True
    returns = [n for n in ast.walk(tree) if isinstance(n, ast.Return)]
    return not any(
        r.value is not None
        and not (isinstance(r.value, ast.Constant) and r.value.value is None)
        for r in returns
    )
