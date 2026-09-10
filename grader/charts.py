"""Chart evidence for visualization assignments (design.md §23, §25).

Assignment 2 grades charts, so the gradeable facts are not variable values but
*what was drawn*: which library drew it, whether it actually rendered, and — for
Altair — what the chart specification says it does.

Where the evidence comes from
-----------------------------
An Altair chart compiles to a Vega-Lite specification, and that specification is
in the notebook's own output. So a transformation, a brush selection and a
cross-filter are not guessed from source text: they are read out of the spec the
student's code actually produced. Three output shapes are handled, because the
mime type depends on the Altair version the student happens to have:

* ``application/vnd.vegalite.v4+json`` … ``v6+json`` — the spec, directly,
* ``text/html`` carrying a ``vegaEmbed(...)`` call — the spec is the first
  argument of the embedded script (Altair 6's default renderer),
* ``text/plain`` reading ``alt.Chart(...)`` — the chart rendered, but this
  notebook was saved without the rich output, so only its presence is known.

Matplotlib and seaborn have no specification, only a picture. For those the
evidence is the rendered image plus what the source says about labelling and
colour — enough to tell a TA where to look, never enough to score aesthetics
automatically.

Which notebook the evidence comes from
--------------------------------------
Two notebooks may hold the same chart: the one this grading run executed, and
the one the student handed in with its outputs already saved. Neither is
reliably the better source.

For Assignment 2 the students choose their own dataset and do not hand it in, so
the grading run has nothing to read and every cell after ``read_csv`` fails — the
*submitted* outputs are usually the only place a chart exists. But when an
instructor does supply data, a freshly executed chart is the stronger evidence,
because a saved output can be stale or hand-edited.

So the two are merged cell by cell rather than ranked: for each chart, whichever
notebook actually produced it wins, and the record says which one that was.
``ChartRecord.output_source`` and ``ChartEvidence.source`` carry that through to
the rubric evidence, and the checks lower their confidence for a chart only seen
in the student's own file.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import nbformat

MATPLOTLIB = "matplotlib"
SEABORN = "seaborn"
ALTAIR = "altair"

SOURCE_EXECUTED = "executed"
SOURCE_SUBMITTED = "submitted"
# Some charts from each: the usual case when students do not hand in their data.
SOURCE_MERGED = "merged"
SOURCE_NONE = "none"

# ---------------------------------------------------------------------------
# Library attribution
# ---------------------------------------------------------------------------

# Seaborn helpers that style a figure without drawing one; a cell holding only
# these is setup, not a chart.
SEABORN_NON_PLOTTING = (
    "set", "set_theme", "set_style", "set_context", "set_palette", "color_palette",
    "axes_style", "plotting_context", "despine", "load_dataset", "move_legend",
    "diverging_palette", "light_palette", "dark_palette", "cubehelix_palette",
)
SEABORN_PLOT_RE = re.compile(
    r"\b(?:sns|seaborn)\.(?!(?:" + "|".join(SEABORN_NON_PLOTTING) + r")\b)(\w+)\s*\("
)

# Matplotlib Axes/pyplot methods that put marks on a canvas.
MATPLOTLIB_PLOT_METHODS = (
    "plot", "scatter", "bar", "barh", "hist", "hist2d", "boxplot", "pie", "imshow",
    "contour", "contourf", "fill_between", "fill_betweenx", "stackplot", "step",
    "errorbar", "violinplot", "hexbin", "pcolormesh", "pcolor", "stem", "quiver",
    "semilogx", "semilogy", "loglog", "matshow", "tripcolor", "eventplot",
    "broken_barh", "streamplot", "spy", "acorr", "angle_spectrum",
)
MATPLOTLIB_PLOT_RE = re.compile(
    r"\b(?:plt|pyplot|ax|axs|axes|axis|ax\d+|ax_\w+|axs\[[^\]]*\]|axes\[[^\]]*\])"
    r"\.(?:" + "|".join(MATPLOTLIB_PLOT_METHODS) + r")\s*\("
)
# ``df.plot(...)``, ``df.plot.bar(...)``, ``gdf.plot(column=...)`` — pandas and
# geopandas draw through matplotlib, and students count these as matplotlib.
PANDAS_PLOT_RE = re.compile(r"\.plot\s*\(|\.plot\.\w+\s*\(")

ALTAIR_RE = re.compile(r"\balt\.\w+|\baltair\.\w+|\.mark_\w+\s*\(")

# Altair calls that only exist to draw, so a cell holding one is a chart cell
# even when the chart is assigned to a name and shown later.
ALTAIR_CHART_RE = re.compile(r"\b(?:alt|altair)\.(?:Chart|layer|hconcat|vconcat|concat)\s*\(|\.mark_\w+\s*\(")


def libraries_in_source(source: str) -> list[str]:
    """Which plotting libraries this cell draws with, most specific first.

    Seaborn shadows matplotlib deliberately: ``sns.boxplot(...)`` followed by
    ``plt.title(...)`` is one seaborn chart, not a seaborn chart plus a
    matplotlib chart. Grading the two requirements separately depends on it.
    """
    found: list[str] = []
    if ALTAIR_CHART_RE.search(source):
        found.append(ALTAIR)
    if SEABORN_PLOT_RE.search(source):
        found.append(SEABORN)
    elif MATPLOTLIB_PLOT_RE.search(source) or PANDAS_PLOT_RE.search(source):
        found.append(MATPLOTLIB)
    return found


# ---------------------------------------------------------------------------
# Vega-Lite spec extraction
# ---------------------------------------------------------------------------

VEGALITE_MIME_RE = re.compile(r"^application/vnd\.vega(?:lite)?\.v\d+\+json$")
# Altair's HTML renderer ends with `})(<spec>, <embedOpt>);` inside a <script>.
VEGA_EMBED_MARKER = "})("

_DECODER = json.JSONDecoder()


def _output_text(value: Any) -> str:
    if isinstance(value, list):
        return "".join(str(v) for v in value)
    return str(value or "")


def extract_specs(output: dict[str, Any]) -> list[dict[str, Any]]:
    """Vega-Lite specifications carried by one notebook output."""
    data = output.get("data") or {}
    specs: list[dict[str, Any]] = []
    for mime, payload in data.items():
        if VEGALITE_MIME_RE.match(str(mime)) and isinstance(payload, dict):
            specs.append(payload)
    if specs:
        return specs

    html = _output_text(data.get("text/html"))
    if "vegaEmbed" not in html and "vega-lite" not in html:
        return specs
    start = html.find(VEGA_EMBED_MARKER)
    while start != -1:
        remainder = html[start + len(VEGA_EMBED_MARKER):].lstrip()
        if remainder.startswith("{"):
            try:
                spec, _ = _DECODER.raw_decode(remainder)
            except ValueError:
                spec = None
            if isinstance(spec, dict) and ("mark" in spec or _has_composition(spec)):
                specs.append(spec)
                break
        start = html.find(VEGA_EMBED_MARKER, start + 1)
    return specs


COMPOSITION_KEYS = ("hconcat", "vconcat", "concat", "layer", "facet", "repeat", "spec")


def _has_composition(spec: dict[str, Any]) -> bool:
    return any(key in spec for key in COMPOSITION_KEYS)


def strip_spec_data(node: Any, depth: int = 0) -> Any:
    """Drop inlined rows so a spec can be stored as rubric evidence.

    A student's chart embeds their whole dataset in the spec; keeping it would
    put megabytes of their data into every results file.
    """
    if depth > 12:
        return "..."
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key == "datasets":
                out[key] = {k: f"<{len(v) if isinstance(v, list) else '?'} rows>"
                            for k, v in (value or {}).items()}
            elif key == "values" and isinstance(value, list):
                out[key] = f"<{len(value)} rows>"
            else:
                out[key] = strip_spec_data(value, depth + 1)
        return out
    if isinstance(node, list):
        return [strip_spec_data(v, depth + 1) for v in node[:60]]
    return node


# ---------------------------------------------------------------------------
# Spec analysis
# ---------------------------------------------------------------------------

# "A transformation (mean, count, binning, etc)". A bare filter is a subset, not
# a transformation of the values, so it is deliberately not in this set.
TRANSFORM_OPS = {
    "aggregate", "bin", "calculate", "density", "flatten", "fold", "impute",
    "joinaggregate", "loess", "lookup", "pivot", "quantile", "regression",
    "sample", "stack", "timeUnit", "window", "extent",
}
ENCODING_TRANSFORM_KEYS = ("aggregate", "bin", "timeUnit")


@dataclass
class SpecFacts:
    """What one Vega-Lite specification says the chart does."""

    marks: list[str] = field(default_factory=list)
    transform_ops: list[str] = field(default_factory=list)
    encoding_transforms: list[str] = field(default_factory=list)
    selections: list[dict[str, Any]] = field(default_factory=list)
    filter_params: list[str] = field(default_factory=list)
    condition_params: list[str] = field(default_factory=list)
    composition: list[str] = field(default_factory=list)
    view_count: int = 0
    channels: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    color_schemes: list[str] = field(default_factory=list)
    has_tooltip: bool = False

    @property
    def brushes(self) -> list[dict[str, Any]]:
        """Interval selections a viewer can drag — pan/zoom bindings excluded.

        ``.interactive()`` also compiles to an interval selection, but with
        ``bind: "scales"``: it zooms the axes rather than selecting data. Counting
        it as a brush would give the mark to every student who added pan/zoom.
        """
        return [s for s in self.selections
                if s.get("type") == "interval" and s.get("bind") != "scales"]

    @property
    def has_brush(self) -> bool:
        return bool(self.brushes)

    @property
    def has_transformation(self) -> bool:
        return bool(self.transform_ops or self.encoding_transforms)

    @property
    def is_multi_view(self) -> bool:
        return bool(self.composition) or self.view_count > 1

    @property
    def cross_filter_params(self) -> list[str]:
        """Selections that a *different* view filters on — a real cross-filter."""
        names = {s.get("name") for s in self.selections}
        return [p for p in self.filter_params if p in names]

    @property
    def has_cross_filter(self) -> bool:
        return bool(self.cross_filter_params) and self.is_multi_view

    def to_dict(self) -> dict[str, Any]:
        return {
            "marks": self.marks,
            "transform_ops": self.transform_ops,
            "encoding_transforms": self.encoding_transforms,
            "selections": self.selections,
            "brush_count": len(self.brushes),
            "filter_params": self.filter_params,
            "condition_params": self.condition_params,
            "cross_filter_params": self.cross_filter_params,
            "composition": self.composition,
            "view_count": self.view_count,
            "channels": self.channels,
            "fields": self.fields,
            "titles": self.titles,
            "color_schemes": self.color_schemes,
            "has_tooltip": self.has_tooltip,
            "has_transformation": self.has_transformation,
            "has_brush": self.has_brush,
            "has_cross_filter": self.has_cross_filter,
        }


def _add(values: list[str], value: Any) -> None:
    text = str(value)
    if text and text not in values:
        values.append(text)


def analyze_spec(spec: dict[str, Any]) -> SpecFacts:
    """Read one Vega-Lite spec, at any level of composition."""
    facts = SpecFacts()
    for key in COMPOSITION_KEYS:
        if key in (spec or {}) and key != "spec":
            _add(facts.composition, key)
        elif key == "spec" and key in (spec or {}):
            _add(facts.composition, "repeat/facet")
    _walk_spec(spec, facts)
    return facts


def _walk_spec(node: Any, facts: SpecFacts, depth: int = 0) -> None:
    if depth > 14:
        return
    if isinstance(node, list):
        for item in node:
            _walk_spec(item, facts, depth + 1)
        return
    if not isinstance(node, dict):
        return

    mark = node.get("mark")
    if isinstance(mark, str):
        _add(facts.marks, mark)
        facts.view_count += 1
    elif isinstance(mark, dict) and mark.get("type"):
        _add(facts.marks, mark["type"])
        facts.view_count += 1

    for entry in _as_list(node.get("transform")):
        if not isinstance(entry, dict):
            continue
        for key in entry:
            if key in TRANSFORM_OPS:
                _add(facts.transform_ops, key)
        if "filter" in entry:
            _collect_filter(entry["filter"], facts)

    encoding = node.get("encoding")
    if isinstance(encoding, dict):
        for channel, definition in encoding.items():
            _add(facts.channels, channel)
            if channel == "tooltip":
                facts.has_tooltip = True
            for definition in _as_list(definition):
                if not isinstance(definition, dict):
                    continue
                if definition.get("field"):
                    _add(facts.fields, _short(definition["field"], 40))
                for key in ENCODING_TRANSFORM_KEYS:
                    value = definition.get(key)
                    if value in (None, False):
                        continue
                    _add(facts.encoding_transforms,
                         f"{channel}.{key}={_short(value)}")
                condition = definition.get("condition")
                for entry in _as_list(condition):
                    if isinstance(entry, dict):
                        for key in ("param", "selection"):
                            if entry.get(key):
                                _add(facts.condition_params, entry[key])
                scale = definition.get("scale")
                if isinstance(scale, dict) and scale.get("scheme"):
                    _add(facts.color_schemes, _short(scale["scheme"]))

    # Vega-Lite 5+ params, and the Vega-Lite 4 `selection` block.
    for param in _as_list(node.get("params")):
        if isinstance(param, dict) and param.get("name"):
            facts.selections.append(_selection_entry(param["name"], param))
    selection = node.get("selection")
    if isinstance(selection, dict):
        for name, definition in selection.items():
            if isinstance(definition, dict):
                facts.selections.append(
                    _selection_entry(name, {"select": definition, **definition})
                )

    title = node.get("title")
    if isinstance(title, str):
        _add(facts.titles, title)
    elif isinstance(title, dict) and title.get("text"):
        _add(facts.titles, _short(title["text"]))

    for key, value in node.items():
        if key in ("datasets", "values", "transform", "encoding", "params", "selection"):
            continue
        _walk_spec(value, facts, depth + 1)


def _selection_entry(name: str, param: dict[str, Any]) -> dict[str, Any]:
    select = param.get("select")
    if isinstance(select, str):
        kind = select
    elif isinstance(select, dict):
        kind = select.get("type", "point")
    else:
        kind = "value" if "value" in param or "bind" in param else "unknown"
    entry: dict[str, Any] = {"name": str(name), "type": str(kind)}
    if param.get("bind") is not None:
        entry["bind"] = _short(param["bind"])
    if isinstance(select, dict) and select.get("encodings"):
        entry["encodings"] = [str(e) for e in select["encodings"]][:4]
    if param.get("views"):
        entry["views"] = [str(v) for v in _as_list(param["views"])][:4]
    return entry


def _collect_filter(predicate: Any, facts: SpecFacts) -> None:
    if isinstance(predicate, str):
        return  # an expression filter, e.g. "datum.year > 2000"
    if isinstance(predicate, dict):
        for key in ("param", "selection"):
            if predicate.get(key):
                _add(facts.filter_params, str(predicate[key]))
        for key in ("and", "or", "not"):
            for entry in _as_list(predicate.get(key)):
                _collect_filter(entry, facts)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _short(value: Any, limit: int = 60) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


def merge_facts(specs: Iterable[dict[str, Any]]) -> SpecFacts:
    """One view of a cell that displayed more than one chart."""
    merged = SpecFacts()
    for spec in specs:
        facts = analyze_spec(spec)
        for name in ("marks", "transform_ops", "encoding_transforms", "filter_params",
                     "condition_params", "composition", "channels", "fields",
                     "titles", "color_schemes"):
            for value in getattr(facts, name):
                _add(getattr(merged, name), value)
        merged.selections.extend(facts.selections)
        merged.view_count += facts.view_count
        merged.has_tooltip = merged.has_tooltip or facts.has_tooltip
    return merged


# ---------------------------------------------------------------------------
# Static aesthetic signals (matplotlib / seaborn)
# ---------------------------------------------------------------------------

AESTHETIC_PATTERNS: dict[str, re.Pattern[str]] = {
    "title": re.compile(r"\.set_title\s*\(|\bplt\.title\s*\(|\.suptitle\s*\(|\btitle\s*="),
    "x_label": re.compile(r"\.set_xlabel\s*\(|\bplt\.xlabel\s*\(|\.set\s*\([^)]*xlabel"),
    "y_label": re.compile(r"\.set_ylabel\s*\(|\bplt\.ylabel\s*\(|\.set\s*\([^)]*ylabel"),
    "legend": re.compile(r"\.legend\s*\(|\blegend\s*=\s*(?!False)"),
    "explicit_colors": re.compile(r"\bcolor\s*=|\bc\s*=|\bcolors\s*=|\bcmap\s*=|"
                                  r"\bpalette\s*=|\bhue\s*=|\bcolormap\s*="),
    "figure_size": re.compile(r"\bfigsize\s*=|\bset_size_inches\s*\(|\bheight\s*=|\baspect\s*="),
    "tick_control": re.compile(r"\.set_xticks\s*\(|\.set_yticks\s*\(|\bplt\.xticks\s*\(|"
                               r"\bplt\.yticks\s*\(|\.tick_params\s*\("),
    "grid_or_style": re.compile(r"\.grid\s*\(|\bsns\.set\w*\s*\(|\bplt\.style\.use\s*\(|"
                                r"\bdespine\s*\("),
    "annotation": re.compile(r"\.annotate\s*\(|\.text\s*\(|\baxhline\s*\(|\baxvline\s*\("),
    "colorbar": re.compile(r"\.colorbar\s*\(|\bcolorbar\s*="),
}


def aesthetic_signals(source: str) -> dict[str, bool]:
    """Presence of the labelling and colour choices a TA would look for.

    These are signals, never a score: a chart can set every label and still be
    unreadable, and the assignment says a person grades the aesthetics.
    """
    return {name: bool(pattern.search(source)) for name, pattern in AESTHETIC_PATTERNS.items()}


# ---------------------------------------------------------------------------
# Notebook walk
# ---------------------------------------------------------------------------

IMAGE_MIMES = ("image/png", "image/jpeg", "image/svg+xml")
# Altair's plain-text fallback when a notebook was saved without rich output.
ALTAIR_REPR_RE = re.compile(r"^\s*alt\.(?:Chart|LayerChart|HConcatChart|VConcatChart|"
                            r"ConcatChart|FacetChart|RepeatChart)")


@dataclass
class ChartRecord:
    """One chart, as drawn by one cell."""

    library: str
    code_cell: int
    cell_index: int
    source: str
    rendered: bool = False
    errored: bool = False
    error: str = ""
    output_mimes: list[str] = field(default_factory=list)
    specs: list[dict[str, Any]] = field(default_factory=list)
    facts: SpecFacts = field(default_factory=SpecFacts)
    discussion: str = ""
    discussion_words: int = 0
    preamble: str = ""
    preamble_words: int = 0
    aesthetics: dict[str, bool] = field(default_factory=dict)
    # Which notebook these outputs were read from.
    output_source: str = SOURCE_NONE

    @property
    def ok(self) -> bool:
        """Drew something, and the cell that drew it did not fail.

        These are separate facts on purpose. The inline backend flushes any
        figure a cell created even when that cell then raised, so a seaborn call
        that died on a NameError still leaves an empty PNG in the notebook —
        ``rendered`` records that an image exists, ``ok`` records that it is a
        chart rather than the wreckage of one.
        """
        return self.rendered and not self.errored

    @property
    def has_discussion(self) -> bool:
        return self.discussion_words > 0

    def summary(self, max_source: int = 700) -> dict[str, Any]:
        """Compact, TA-readable evidence (design.md §12)."""
        data: dict[str, Any] = {
            "library": self.library,
            "code_cell": self.code_cell,
            "rendered": self.rendered,
            "cell_errored": self.errored,
            "output_source": self.output_source,
            "source": self.source[:max_source],
            "discussion_words": self.discussion_words,
            "discussion": self.discussion[:600],
            "preamble": self.preamble[:600],
        }
        if self.errored:
            data["error"] = self.error
        if self.library == ALTAIR:
            data["spec"] = self.facts.to_dict()
        else:
            data["aesthetics"] = self.aesthetics
        return data


@dataclass
class ChartEvidence:
    """Every chart found in a submission, in the order the cells appear."""

    source: str = SOURCE_NONE
    notebook_path: str | None = None
    charts: list[ChartRecord] = field(default_factory=list)
    n_code_cells: int = 0
    error: str | None = None

    @property
    def from_execution(self) -> bool:
        """Every chart that came out was produced by this grading run."""
        drawn = [c for c in self.charts if c.ok]
        return bool(drawn) and all(c.output_source == SOURCE_EXECUTED for c in drawn)

    def verified(self, records: list["ChartRecord"]) -> bool:
        """Were these particular charts produced here, rather than by the student?"""
        drawn = [c for c in records if c.ok]
        return bool(drawn) and all(c.output_source == SOURCE_EXECUTED for c in drawn)

    def by_library(self, library: str) -> list[ChartRecord]:
        return [c for c in self.charts if c.library == library]

    def rendered(self, library: str) -> list[ChartRecord]:
        return [c for c in self.by_library(library) if c.ok]

    def summary(self) -> dict[str, Any]:
        return {
            "evidence_source": self.source,
            "notebook": self.notebook_path,
            "charts": [c.summary() for c in self.charts],
        }


def collect_charts(
    executed_path: str | Path | None,
    submitted_path: str | Path | None = None,
) -> ChartEvidence:
    """Chart evidence, taking each chart from whichever notebook drew it.

    The executed notebook is the instrumented copy of the submitted one, so their
    code cells line up one to one and a chart can be matched across the two by
    its cell number and library. Where both drew it, the executed run wins; where
    only the student's saved output has it, that is used and recorded as such.
    """
    executed = _read(executed_path, SOURCE_EXECUTED)
    submitted = _read(submitted_path, SOURCE_SUBMITTED)
    if executed is None and submitted is None:
        return ChartEvidence()
    if executed is None:
        return submitted
    if submitted is None:
        return executed

    fallback = {(c.code_cell, c.library): c for c in submitted.charts}
    merged: list[ChartRecord] = []
    used_submitted = False
    for record in executed.charts:
        other = fallback.pop((record.code_cell, record.library), None)
        if not record.ok and other is not None and other.ok:
            # The student's own run drew this chart; ours could not.
            other.discussion = record.discussion or other.discussion
            other.discussion_words = max(record.discussion_words, other.discussion_words)
            other.preamble = record.preamble or other.preamble
            other.preamble_words = max(record.preamble_words, other.preamble_words)
            merged.append(other)
            used_submitted = True
        else:
            merged.append(record)
    # A cell the executed copy never reached at all.
    for record in fallback.values():
        merged.append(record)
        used_submitted = used_submitted or record.ok

    merged.sort(key=lambda c: (c.code_cell, c.library))
    source = SOURCE_MERGED if used_submitted else SOURCE_EXECUTED
    return ChartEvidence(
        source=source,
        notebook_path=executed.notebook_path,
        charts=merged,
        n_code_cells=max(executed.n_code_cells, submitted.n_code_cells),
    )


def _read(path: str | Path | None, label: str) -> ChartEvidence | None:
    if not path or not Path(path).is_file():
        return None
    evidence = _collect_from(Path(path), label)
    return evidence if evidence.source != SOURCE_NONE else None


def _collect_from(path: Path, label: str) -> ChartEvidence:
    evidence = ChartEvidence(source=label, notebook_path=str(path))
    try:
        nb = nbformat.read(str(path), as_version=4)
    except Exception as exc:
        evidence.source = SOURCE_NONE
        evidence.error = f"{type(exc).__name__}: {exc}"
        return evidence

    cells = [c for c in nb.cells if not (c.get("metadata") or {}).get("musa_probe")]
    code_number = 0
    for index, cell in enumerate(cells):
        if cell.get("cell_type") != "code":
            continue
        code_number += 1
        source = cell.get("source") or ""
        libraries = libraries_in_source(source)
        if not libraries:
            continue
        outputs = cell.get("outputs") or []
        discussion, words = _markdown_run(cells, index, step=1)
        preamble, preamble_words = _markdown_run(cells, index, step=-1)
        for library in libraries:
            record = ChartRecord(
                library=library,
                code_cell=code_number,
                cell_index=index,
                source=source,
                discussion=discussion,
                discussion_words=words,
                preamble=preamble,
                preamble_words=preamble_words,
                output_source=evidence.source,
            )
            _attach_outputs(record, outputs)
            if library != ALTAIR:
                record.aesthetics = aesthetic_signals(source)
            evidence.charts.append(record)
    evidence.n_code_cells = code_number
    return evidence


def _attach_outputs(record: ChartRecord, outputs: list[dict[str, Any]]) -> None:
    specs: list[dict[str, Any]] = []
    for output in outputs:
        kind = output.get("output_type")
        if kind == "error":
            record.errored = True
            record.error = f"{output.get('ename', 'Error')}: {output.get('evalue', '')}"[:300]
            continue
        data = output.get("data") or {}
        for mime in data:
            if str(mime) not in record.output_mimes:
                record.output_mimes.append(str(mime))
        if record.library == ALTAIR:
            found = extract_specs(output)
            specs.extend(found)
            if found or any("vega" in str(m) for m in data):
                record.rendered = True
            elif ALTAIR_REPR_RE.match(_output_text(data.get("text/plain"))):
                # Rendered once, but this notebook was saved without the spec.
                record.rendered = True
        elif any(mime in data for mime in IMAGE_MIMES):
            record.rendered = True

    if specs:
        record.specs = [strip_spec_data(s) for s in specs]
        record.facts = merge_facts(specs)


def _markdown_run(cells: list[Any], index: int, step: int) -> tuple[str, int]:
    """The unbroken run of markdown next to a chart cell, in reading order.

    The assignment asks for the conclusion "in a markdown cell below each
    chart", so position is part of the requirement: prose two charts later does
    not satisfy it. Walking backwards (``step=-1``) finds the markdown that
    introduces a chart, which is where a rationale for choosing a library
    usually lives.
    """
    pieces: list[str] = []
    position = index + step
    while 0 <= position < len(cells):
        cell = cells[position]
        kind = cell.get("cell_type")
        if kind == "code":
            break
        if kind == "markdown":
            text = (cell.get("source") or "").strip()
            if text:
                pieces.append(text)
        position += step
    if step < 0:
        pieces.reverse()
    joined = "\n\n".join(pieces)
    return joined, prose_word_count(joined)


HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")
PLACEHOLDER_RE = re.compile(
    r"^\s*(?:\*{0,2})(?:your (?:answer|discussion|conclusion|response) here|"
    r"todo|tbd|write your|conclusion:?|discussion:?)(?:\*{0,2})\s*$",
    re.IGNORECASE,
)


def prose_word_count(text: str) -> int:
    """Words of actual discussion — headings and placeholders do not count."""
    words = 0
    for line in (text or "").splitlines():
        if HEADING_RE.match(line) or PLACEHOLDER_RE.match(line):
            continue
        words += len(re.findall(r"[A-Za-z][A-Za-z'’\-]*", line))
    return words
