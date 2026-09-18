"""Answers read out of a notebook's own saved outputs (design.md §23, §25).

Why this exists
---------------
Assignment 3 has an answer key — everyone runs the same zip — so the grader knows
that Philadelphia has 384 tracts and that the median NDVI inside the city limits
is 0.2025. The question is where to *see* the student's version of those numbers.

Re-running the notebook is one answer, and it is the strongest one when it works.
But it is also the fragile one, and on this assignment it is fragile in a way
that is nobody's fault: five data files instead of one, read from whatever path
each student happened to use, sometimes built with ``os.path.join`` or a variable
the grader cannot resolve. When the placement misses, the notebook dies at the
first ``read_file`` and every step after it is invisible — a submission that was
entirely correct grades as if nothing happened.

The student's own run does not have that problem. They ran it with their data in
the right place, and the notebook they handed in carries what it printed:

    In  [3]: len(phl)
    Out [3]: 384

That ``384`` is the answer to 1.1.2, sitting in the file. So is ``34108``, and
``(368606317.0763259, 462551418.69179374)``, and ``Median NDVI, city: 0.2025``.
This module harvests them, and the checks in ``assignments/hw3.py`` accept either
source: the step counts as done if the executed run shows it *or* the submitted
notebook does. Execution stops being load-bearing and becomes corroboration.

What can be read, and what it is worth
--------------------------------------
======================  ==================================================
Output                  What it yields
======================  ==================================================
``print(...)``          every number in the text — deliberately shown
a bare final expression  every number, when it is short enough to be a
                        result rather than a table
a DataFrame repr        ``5376 rows x 4 columns``, the column names, and
                        nothing else — the cell values of a ``head()`` are
                        not answers, and harvesting them invents matches
``.describe()``         count / mean / median / min / max
``.info()``             row count, column names, dtypes
an hvplot chart         ``:HoloMap [year]`` — the object's own repr, which
                        says whether ``dynamic=False`` was passed, plus the
                        widget's option list from the embedded HTML
matplotlib              ``<Figure size 800x450 with 1 Axes>`` and the PNG
======================  ==================================================

A saved output is the student's claim about their own run, not a fact the grader
established, so a check that rests on one alone says so and grades at lower
confidence — the same caveat ``grader/charts.py`` records for a chart seen only
in the submitted file. Outputs can be stale, and they can be edited by hand.
"""

from __future__ import annotations

import base64
import gzip
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import nbformat

SOURCE_EXECUTED = "executed"
SOURCE_SUBMITTED = "submitted"
SOURCE_MERGED = "merged"
SOURCE_NONE = "none"

# A result short enough to be a result. Tables are excluded by their own markers
# rather than by length (a `head()` repr carries an HTML table, `.info()` and
# `.describe()` have shapes of their own), so this only has to rule out the
# pathological case — a cell that dumps a whole file. It is generous because
# `landsat.count, landsat.crs` prints a full WKT block, and the EPSG code inside
# that block is the answer.
MAX_SCALAR_CHARS = 6000

NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
# pandas prints its shape under a truncated frame: "[5376 rows x 4 columns]" in
# text and "<p>5376 rows × 4 columns</p>" in HTML (a multiplication sign, not x).
SHAPE_TEXT_RE = re.compile(r"\[(\d[\d,]*)\s+rows?\s+x\s+(\d[\d,]*)\s+columns?\]")
SHAPE_HTML_RE = re.compile(r"(\d[\d,]*)\s*rows?\s*[x×]\s*(\d[\d,]*)\s*columns?")
# `.info()`: "RangeIndex: 5376 entries, 0 to 5375"
ENTRIES_RE = re.compile(r"(\d[\d,]*)\s+entries")
# `.info()` column table: " 0   GEOID   5376 non-null   str"
INFO_COLUMN_RE = re.compile(r"^\s*\d+\s+(\S+)\s+\d[\d,]*\s+non-null", re.M)
# `.describe()` rows, in the text repr.
DESCRIBE_RE = re.compile(
    r"^\s*(count|mean|std|min|25%|50%|75%|max)\s+(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*$",
    re.M,
)
FIGURE_RE = re.compile(r"<Figure size (\d+)x(\d+) with (\d+) Axes?>")
HTML_TABLE_RE = re.compile(r"<table\b", re.I)
HTML_HEADER_RE = re.compile(r"<th[^>]*>([^<]{1,60})</th>", re.I)

# The repr holoviews gives every object:
#     :HoloMap   [year]
#        :Polygons   [x,y]   (evictions,GEOID)
#     :Layout
#        .Polygons.I  :Polygons   [x,y]   (evictions)
HOLOVIEWS_LINE_RE = re.compile(
    r"^(?P<indent>\s*)(?:\.(?P<path>\S+)\s+)?:(?P<kind>[A-Za-z]\w*)"
    r"(?:\s+\[(?P<kdims>[^\]]*)\])?"
    r"(?:\s+\((?P<vdims>[^)]*)\))?\s*$"
)
# The widget Panel renders beside a HoloMap, in the embedded bokeh document.
WIDGET_RE = re.compile(
    r'"title":"(?P<title>[^"]{1,80})","options":\[(?P<options>[^\]]{0,8000})\]'
    r'|"options":\[(?P<options2>[^\]]{0,8000})\],"title":"(?P<title2>[^"]{1,80})"'
)
QUOTED_RE = re.compile(r'"((?:[^"\\]|\\.){0,200})"')
# Bokeh writes a chart's numeric columns into the notebook as a base64 (usually
# gzipped) buffer. This is where "the numbers actually plotted" live once the
# kernel is gone.
NDARRAY_RE = re.compile(
    r'"array":\{"type":"bytes","data":"(?P<data>[A-Za-z0-9+/=]{4,200000})"\}'
    r',"shape":\[(?P<length>\d{1,9})\],"dtype":"(?P<dtype>\w+)"'
)
STRUCT_CODES = {
    "float64": ("d", 8), "float32": ("f", 4),
    "int64": ("q", 8), "int32": ("i", 4), "int16": ("h", 2), "int8": ("b", 1),
    "uint64": ("Q", 8), "uint32": ("I", 4), "uint16": ("H", 2), "uint8": ("B", 1),
}

IMAGE_MIMES = ("image/png", "image/jpeg", "image/svg+xml")

# Containers whose whole point is one chart per value of a dimension.
WIDGET_KINDS = ("HoloMap", "GridSpace", "NdLayout")
# The same thing, never evaluated: what hvplot returns without `dynamic=False`.
LAZY_KINDS = ("DynamicMap",)
LAYOUT_KINDS = ("Layout", "NdLayout")


def _join(value: Any) -> str:
    if isinstance(value, list):
        return "".join(str(v) for v in value)
    return str(value or "")


def _int(text: str) -> int:
    return int(str(text).replace(",", ""))


@dataclass
class HoloviewsRepr:
    """One holoviews object, as its own repr describes it."""

    kind: str
    kdims: list[str] = field(default_factory=list)
    vdims: list[str] = field(default_factory=list)
    children: list[str] = field(default_factory=list)
    # Option list of the widget beside it, read from the embedded bokeh document.
    frame_keys: list[str] = field(default_factory=list)
    widget_dimension: str = ""
    # The numbers the chart actually draws, decoded from that same document.
    values: dict[str, float] = field(default_factory=dict)
    code_cell: int = 0
    source: str = SOURCE_NONE

    @property
    def is_widget(self) -> bool:
        return self.kind in WIDGET_KINDS

    @property
    def is_lazy(self) -> bool:
        """A DynamicMap: the widget exists but no frame was ever computed."""
        return self.kind in LAZY_KINDS

    @property
    def is_layout(self) -> bool:
        return self.kind in LAYOUT_KINDS

    @property
    def element_types(self) -> list[str]:
        return self.children or [self.kind]

    def summary(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "key_dimensions": self.kdims,
            "value_dimensions": self.vdims,
            "children": self.children,
            "frames": len(self.frame_keys) or None,
            "frame_keys": self.frame_keys[:8],
            "plotted_values": self.values or None,
            "code_cell": self.code_cell,
            "source": self.source,
        }


@dataclass
class CellAnswers:
    """Everything one code cell's saved output states."""

    code_cell: int
    cell_index: int
    source_code: str
    text: str = ""
    # Numbers the cell deliberately showed: printed, or returned as a short
    # result. Never cell values scraped out of a table repr.
    shown: list[float] = field(default_factory=list)
    shapes: list[tuple[int, int]] = field(default_factory=list)
    row_counts: list[int] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    describe: dict[str, float] = field(default_factory=dict)
    holoviews: list[HoloviewsRepr] = field(default_factory=list)
    figures: int = 0
    images: int = 0
    errored: bool = False
    error: str = ""
    origin: str = SOURCE_NONE

    @property
    def has_output(self) -> bool:
        return bool(
            self.text or self.shown or self.shapes or self.row_counts
            or self.holoviews or self.figures or self.images or self.errored
        )

    @property
    def has_answer(self) -> bool:
        """Output that states something, as opposed to a traceback.

        The distinction decides the merge below. When the grading run cannot
        find the data, every cell after the first `read_file` raises, and a
        raise is output — so ranking cells by "has output" hands every slot to
        the failed run and hides the answers the student actually saved.
        """
        return bool(
            self.shown or self.shapes or self.row_counts or self.columns
            or self.describe or self.holoviews or self.figures or self.images
        )


@dataclass
class NotebookAnswers:
    """Every answer a notebook shows, with where each one was seen."""

    cells: list[CellAnswers] = field(default_factory=list)
    source: str = SOURCE_NONE

    # -- lookups -------------------------------------------------------
    def shows(
        self, expected: float, rel_tol: float = 0.0, abs_tol: float = 0.0
    ) -> CellAnswers | None:
        """The first cell that printed or returned this number."""
        tolerance = abs(expected) * rel_tol + abs_tol
        for cell in self.cells:
            for value in cell.shown:
                if abs(value - expected) <= tolerance:
                    return cell
        return None

    def shows_all(self, expected: Iterable[float], rel_tol: float = 0.0,
                  abs_tol: float = 0.0) -> bool:
        return all(self.shows(value, rel_tol, abs_tol) for value in expected)

    def shows_together(
        self, expected: Iterable[float], rel_tol: float = 0.0, abs_tol: float = 0.0
    ) -> CellAnswers | None:
        """A single cell that shows all of these numbers at once.

        "10" on its own means nothing — it is in every notebook. "10 and 32618 in
        the same output" is a ten-band scene in UTM zone 18N, which is the file
        this assignment ships.
        """
        wanted = list(expected)
        for cell in self.cells:
            if all(
                any(abs(value - target) <= abs(target) * rel_tol + abs_tol
                    for value in cell.shown)
                for target in wanted
            ):
                return cell
        return None

    def shows_rows(self, expected: int, tolerance: int = 0) -> CellAnswers | None:
        """A frame of this many rows, from a repr footer, `.shape` or `.info()`."""
        for cell in self.cells:
            for count in cell.row_counts:
                if abs(count - expected) <= tolerance:
                    return cell
            for rows, _ in cell.shapes:
                if abs(rows - expected) <= tolerance:
                    return cell
        return None

    def frames_with_columns(self, names: Iterable[str]) -> list[CellAnswers]:
        wanted = {str(n).lower() for n in names}
        return [
            cell for cell in self.cells
            if wanted <= {c.lower() for c in cell.columns}
        ]

    def describes(self, key: str, expected: float, abs_tol: float) -> CellAnswers | None:
        for cell in self.cells:
            value = cell.describe.get(key)
            if value is not None and abs(value - expected) <= abs_tol:
                return cell
        return None

    def charts(self) -> list[HoloviewsRepr]:
        return [chart for cell in self.cells for chart in cell.holoviews]

    @property
    def figures(self) -> int:
        return sum(cell.figures for cell in self.cells)

    @property
    def error_cells(self) -> list[CellAnswers]:
        return [cell for cell in self.cells if cell.errored]

    @property
    def cells_with_output(self) -> int:
        return sum(1 for cell in self.cells if cell.has_output)

    @property
    def cells_with_answers(self) -> int:
        return sum(1 for cell in self.cells if cell.has_answer)

    def note(self) -> dict[str, Any]:
        return {
            "evidence_source": self.source,
            "code_cells": len(self.cells),
            "cells_with_output": self.cells_with_output,
            "cells_that_state_a_result": self.cells_with_answers,
            "errors_in_saved_run": [
                {"code_cell": cell.code_cell, "error": cell.error}
                for cell in self.error_cells[:3]
            ],
        }


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _holoviews_from_text(text: str) -> HoloviewsRepr | None:
    """Parse the repr holoviews gives every object.

    Two shapes, and the difference between them is the whole of 1.1.5::

        :HoloMap   [year]            one frame per year, ready to page through
        :DynamicMap   [year]         the same widget, no frames behind it
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines or not lines[0].lstrip().startswith(":"):
        return None
    head = HOLOVIEWS_LINE_RE.match(lines[0])
    if not head:
        return None
    entry = HoloviewsRepr(
        kind=head.group("kind"),
        kdims=[d.strip() for d in (head.group("kdims") or "").split(",") if d.strip()],
        vdims=[d.strip() for d in (head.group("vdims") or "").split(",") if d.strip()],
    )
    for line in lines[1:]:
        child = HOLOVIEWS_LINE_RE.match(line)
        if child and child.group("kind"):
            entry.children.append(child.group("kind"))
            if not entry.vdims and child.group("vdims"):
                entry.vdims = [
                    d.strip() for d in child.group("vdims").split(",") if d.strip()
                ]
    return entry


def _widget_options(html: str, dimension: str = "") -> tuple[str, list[str]]:
    """The option list of the widget beside a chart, from the embedded document.

    Panel writes the whole bokeh document into the notebook, so the dropdown's
    options are in the file: ``"title":"year","options":["e-03",...,"e-16"]``.
    That is the frame list, independent of any title the student set.
    """
    best: tuple[str, list[str]] = ("", [])
    for match in WIDGET_RE.finditer(html):
        title = match.group("title") or match.group("title2") or ""
        options = match.group("options") or match.group("options2") or ""
        values = [
            value.replace('\\"', '"') for value in QUOTED_RE.findall(options)
        ]
        if not values:
            continue
        if dimension and title.strip().lower() == dimension.strip().lower():
            return title, values
        if len(values) > len(best[1]):
            best = (title, values)
    return best


def _plotted_values(html: str, expected_length: int = 0) -> dict[str, float]:
    """Summarise the numeric column a chart draws, from the embedded document.

    Assignment 1.1.4 is graded on the totals plotted, not on the code that
    produced them, so those totals have to survive into the submitted file. They
    do: bokeh serialises each column as a base64 buffer, gzipped, with its dtype
    and length beside it.
    """
    best: dict[str, float] = {}
    for match in NDARRAY_RE.finditer(html):
        code = STRUCT_CODES.get(match.group("dtype"))
        if code is None:
            continue
        length = int(match.group("length"))
        if not 1 <= length <= 100000:
            continue
        try:
            raw = base64.b64decode(match.group("data"), validate=True)
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            symbol, size = code
            if len(raw) < length * size:
                continue
            values = struct.unpack("<{}{}".format(length, symbol), raw[: length * size])
        except Exception:
            continue
        numbers = [float(v) for v in values if v == v]
        if not numbers:
            continue
        summary = {
            "count": float(len(numbers)),
            "sum": float(sum(numbers)),
            "min": float(min(numbers)),
            "max": float(max(numbers)),
        }
        # A chart draws several columns (x and y, or the polygon coordinates);
        # the one whose length matches the widget's frame list is the series.
        if expected_length and len(numbers) == expected_length:
            return summary
        if not best or summary["count"] > best["count"]:
            best = summary
    return best


def _looks_like_table(output: dict[str, Any], text: str) -> bool:
    data = output.get("data") or {}
    html = _join(data.get("text/html"))
    if html and HTML_TABLE_RE.search(html):
        return True
    # `.info()` and `.describe()` write a table without any HTML.
    return bool(ENTRIES_RE.search(text) or DESCRIBE_RE.search(text))


def _read_cell(cell: Any, index: int, code_cell: int, origin: str) -> CellAnswers:
    answers = CellAnswers(
        code_cell=code_cell,
        cell_index=index,
        source_code="".join(cell.get("source", "")) if isinstance(cell.get("source"), list)
        else str(cell.get("source", "")),
        origin=origin,
    )
    texts: list[str] = []

    for output in cell.get("outputs", []) or []:
        kind = output.get("output_type")
        if kind == "error":
            answers.errored = True
            answers.error = f"{output.get('ename', '')}: {output.get('evalue', '')}"[:300]
            continue
        if kind == "stream":
            text = _join(output.get("text"))
            texts.append(text)
            # Printed on purpose, so every number in it is an answer.
            answers.shown.extend(_numbers(text))
            _read_structure(answers, text, "")
            continue
        if kind not in ("execute_result", "display_data"):
            continue

        data = output.get("data") or {}
        if any(mime in data for mime in IMAGE_MIMES):
            answers.images += 1
        text = _join(data.get("text/plain"))
        html = _join(data.get("text/html"))
        if text:
            texts.append(text)

        figures = FIGURE_RE.findall(text)
        answers.figures += len(figures)

        chart = _holoviews_from_text(text)
        if chart is not None:
            chart.code_cell = code_cell
            chart.source = origin
            if html:
                dimension = chart.kdims[0] if chart.kdims else ""
                title, options = _widget_options(html, dimension)
                chart.widget_dimension = title
                chart.frame_keys = options
                if not chart.children:  # a bare element, not a container of maps
                    chart.values = _plotted_values(html, len(options))
            answers.holoviews.append(chart)
            continue

        _read_structure(answers, text, html)
        # A short result is a result; a frame repr is a table, and its cell
        # values are not answers to anything.
        if not _looks_like_table(output, text) and len(text) <= MAX_SCALAR_CHARS:
            answers.shown.extend(_numbers(text))

    answers.text = "\n".join(texts)[:20000]
    answers.shown = _dedupe(answers.shown)
    answers.row_counts = sorted(set(answers.row_counts))
    answers.columns = _dedupe_strings(answers.columns)
    return answers


def _read_structure(answers: CellAnswers, text: str, html: str) -> None:
    """Shapes, row counts, column names and describe tables."""
    for rows, columns in SHAPE_TEXT_RE.findall(text):
        answers.shapes.append((_int(rows), _int(columns)))
        answers.row_counts.append(_int(rows))
    if html:
        for rows, columns in SHAPE_HTML_RE.findall(html):
            answers.shapes.append((_int(rows), _int(columns)))
            answers.row_counts.append(_int(rows))
        answers.columns.extend(
            name.strip() for name in HTML_HEADER_RE.findall(html)
            # A pandas HTML repr headers the index column too, and its row labels
            # come through as "0", "1", "2" — those are not column names.
            if name.strip() and not name.strip().isdigit()
        )
    for count in ENTRIES_RE.findall(text):
        answers.row_counts.append(_int(count))
    answers.columns.extend(INFO_COLUMN_RE.findall(text))
    for key, value in DESCRIBE_RE.findall(text):
        try:
            answers.describe.setdefault(key, float(value))
        except ValueError:  # pragma: no cover - the regex already restricts this
            continue


def _numbers(text: str) -> list[float]:
    found: list[float] = []
    for match in NUMBER_RE.findall(text or ""):
        try:
            found.append(float(match))
        except ValueError:  # pragma: no cover - defensive
            continue
        if len(found) > 400:
            break
    return found


def _dedupe(values: list[float]) -> list[float]:
    seen: list[float] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen[:400]


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen[:200]


def read_answers(path: str | Path | None, origin: str) -> NotebookAnswers:
    """Harvest one notebook's saved outputs."""
    answers = NotebookAnswers(source=SOURCE_NONE)
    if not path:
        return answers
    path = Path(path)
    if not path.is_file():
        return answers
    try:
        notebook = nbformat.read(str(path), as_version=4)
    except Exception:
        return answers

    code_cell = 0
    for index, cell in enumerate(notebook.get("cells", [])):
        if cell.get("cell_type") != "code":
            continue
        if (cell.get("metadata") or {}).get("musa_probe"):
            continue  # the grader's own cells are not the student's answers
        code_cell += 1
        answers.cells.append(_read_cell(cell, index, code_cell, origin))
    if any(cell.has_output for cell in answers.cells):
        answers.source = origin
    return answers


def _has_answers(answers: NotebookAnswers) -> bool:
    return any(cell.has_answer for cell in answers.cells)


def collect_answers(
    executed_path: str | Path | None, submitted_path: str | Path | None
) -> NotebookAnswers:
    """Answers from both notebooks, merged cell by cell.

    Two notebooks may show the same answer: the one this grading run executed,
    and the one the student handed in with its outputs already saved. Neither is
    reliably the better source — the executed run can die on a data path the
    grader could not resolve, and a saved output can be stale or hand-edited — so
    they are merged rather than ranked, and each answer keeps the note of where
    it came from.
    """
    executed = read_answers(executed_path, SOURCE_EXECUTED)
    submitted = read_answers(submitted_path, SOURCE_SUBMITTED)
    if not _has_answers(executed):
        if _has_answers(submitted) or not executed.cells:
            # Neither answered: still hand back the student's file rather than an
            # empty record, so "was this notebook ever run?" can be answered.
            return submitted if submitted.cells else executed
        return executed
    if not _has_answers(submitted):
        return executed

    merged = NotebookAnswers(source=SOURCE_MERGED)

    def rank(cell: CellAnswers) -> tuple:
        """Whichever notebook answered this cell best, with ties to our own run.

        A cell that answered *and* did not raise outranks one that did both,
        which matters more than it sounds: the inline backend flushes a figure
        even when the cell that created it went on to raise, so a failed
        execution leaves an empty PNG in every plotting cell. Ranked on output
        alone, that wreckage would displace the picture the student actually
        produced.
        """
        return (
            cell.has_answer and not cell.errored,
            cell.has_answer,
            cell.has_output,
            cell.origin == SOURCE_EXECUTED,
        )

    by_cell: dict[int, CellAnswers] = {}
    for cell in list(executed.cells) + list(submitted.cells):
        current = by_cell.get(cell.code_cell)
        if current is None or rank(cell) > rank(current):
            by_cell[cell.code_cell] = cell
    merged.cells = [by_cell[key] for key in sorted(by_cell)]
    # The extra cells of whichever notebook is longer still carry their source.
    if not merged.cells:
        return executed
    sources = {cell.origin for cell in merged.cells if cell.has_answer}
    if len(sources) == 1:
        merged.source = sources.pop()
    return merged


__all__ = [
    "CellAnswers",
    "HoloviewsRepr",
    "NotebookAnswers",
    "SOURCE_EXECUTED",
    "SOURCE_MERGED",
    "SOURCE_NONE",
    "SOURCE_SUBMITTED",
    "collect_answers",
    "read_answers",
]
