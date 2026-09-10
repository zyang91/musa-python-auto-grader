"""Assignment 2 autograder — exploratory visualization with matplotlib,
seaborn and altair.

Students choose their own dataset, so there is no answer key: nothing about the
*content* of a chart can be checked. What can be checked is what the code
demonstrably did, and the split runs straight down the middle of the assignment
text:

* **Mechanical, graded automatically.** An Altair chart compiles to a Vega-Lite
  specification and the notebook's own output carries it, so a mean/count/bin
  transformation and an interval brush are read out of the spec rather than
  guessed from source text. Whether a matplotlib or seaborn chart was drawn, and
  whether it rendered, is likewise a fact.
* **Judgement, graded by a person.** The assignment says the matplotlib chart is
  marked on "colour choices and clarity", and asks for written reasoning under
  each chart. A picture's quality and a paragraph's substance are not machine
  facts. Those items come back as ``manual_review`` — always, whatever they
  score — carrying a provisional score built from real signals plus the evidence
  behind it, so a TA confirms or adjusts instead of starting from a blank box.

Students hand in a notebook without their dataset, so the grading run has
nothing to read: it fails at ``read_csv`` and draws nothing. The charts are
therefore read out of the outputs the student already saved in the notebook they
submitted (``grader/charts.py`` merges the two sources cell by cell, so this
still uses a freshly executed chart wherever one exists). What is being marked
is that the student can *produce these elements* — the correctness of their
numbers was never checkable with a dataset of their own choosing.

Where a check cannot see the work at all — no notebook, no outputs — it says so
and asks for a human, rather than recording a zero the student would have to
appeal (design.md §19, §25).
"""

from __future__ import annotations

import re
from typing import Any

from grader import charts as chartlib
from grader.charts import ALTAIR, MATPLOTLIB, SEABORN, ChartEvidence, ChartRecord
from grader.models import (
    STATUS_FAIL,
    STATUS_MANUAL_REVIEW,
    STATUS_NOT_FOUND,
    STATUS_PARTIAL,
    STATUS_PASS,
    RubricItemResult,
)
from grader.rubric import RubricItem

from .base import AssignmentGrader, GradingContext, register

URL_RE = re.compile(r"https?://[^\s'\"<>)]+", re.IGNORECASE)
LIBRARY_LABELS = {
    MATPLOTLIB: "matplotlib",
    SEABORN: "seaborn",
    ALTAIR: "Altair",
}


@register
class HW2Grader(AssignmentGrader):
    assignment_id = "hw2"

    # -- shared evidence ---------------------------------------------------
    def evidence(self, ctx: GradingContext) -> ChartEvidence:
        """Charts found in this submission, read once and reused by every check."""
        cached = ctx.cache.get("chart_evidence")
        if cached is None:
            cached = chartlib.collect_charts(
                ctx.execution.executed_notebook_path,
                ctx.analysis.path,
            )
            ctx.cache["chart_evidence"] = cached
        return cached

    def required_count(self, library: str, default: int = 1) -> int:
        """How many charts of a library the rubric asks for.

        Read back off the rubric so the conclusions check cannot drift out of
        step with the chart checks when a TA edits the YAML.
        """
        for item in self.rubric.items:
            if item.config.get("library") == library:
                return int(item.config.get("required_count", default))
        return default

    def evidence_note(self, evidence: ChartEvidence) -> dict[str, Any]:
        return {
            "evidence_source": evidence.source,
            "evidence_notebook": evidence.notebook_path,
            "chart_cells_found": len(evidence.charts),
        }

    def no_evidence_result(
        self, item: RubricItem, ctx: GradingContext, evidence: ChartEvidence
    ) -> RubricItemResult:
        """No notebook could be read for charts — never an automatic zero."""
        return self.result(
            item, 0.0, STATUS_MANUAL_REVIEW, confidence=0.0,
            feedback=(
                "Neither the executed nor the submitted notebook could be read for "
                "charts, so this item was not graded automatically. Please grade it "
                "by hand."
            ),
            evidence={"read_error": evidence.error, **self.evidence_note(evidence)},
        )

    @staticmethod
    def _confidence(
        evidence: ChartEvidence,
        item: RubricItem,
        base: float = 0.95,
        records: list[ChartRecord] | None = None,
    ) -> float:
        """Slightly less certain when a chart only exists in the student's own file.

        A saved output shows what the student saw rather than what this run
        produced, so it could in principle be stale. For this assignment that is
        the normal case, not a failure, so the drop is small — enough to be
        visible in the evidence without flagging every submission.
        """
        verified = (
            evidence.verified(records) if records is not None else evidence.from_execution
        )
        if verified:
            return base
        return float(item.config.get("submitted_only_confidence", 0.85))

    # -----------------------------------------------------------------
    # Execution — replaced outright, not extended
    # -----------------------------------------------------------------
    def check_notebook_execution(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        """Did the student run their notebook through before handing it in?

        The grader has no copy of the dataset, so it cannot answer this by
        running the notebook: without the data every cell after ``read_csv``
        fails, and a failure caused by the missing file says nothing about the
        student. What it can read is the state the notebook was saved in — which
        cells carry output, and which carry an error — and that is exactly the
        question the assignment cares about here.

        If an instructor does supply the data, a clean execution in this run is
        the stronger answer and takes over.
        """
        analysis = ctx.analysis
        config = item.config

        if not analysis.n_code_cells:
            return self.result(
                item, 0.0, STATUS_NOT_FOUND, 1.0,
                "The notebook contains no code cells.",
                {"n_code_cells": 0},
            )

        # An instructor-supplied dataset makes a real execution possible again.
        if ctx.execution.success:
            return self.result(
                item, item.points, STATUS_PASS, 1.0,
                "Notebook executed successfully in "
                f"{ctx.execution.execution_time_seconds:.1f}s in a clean environment.",
                {"verified_by": "grading run", "mode": ctx.execution.mode},
            )

        outputs = analysis.stored_outputs or {}
        errors = analysis.stored_errors or []
        # "image" is a derived tally of display_data outputs carrying a picture,
        # so counting it here would count those cells twice.
        good_outputs = sum(
            count for kind, count in outputs.items()
            if kind in ("execute_result", "display_data", "stream")
        )
        # A traceback is still evidence the cell was run. Whether it was run and
        # whether it worked are separate deductions, and a notebook that failed
        # in every cell must not be charged for both.
        was_run = bool(good_outputs or errors)
        deductions: list[tuple[float, str]] = []

        if not was_run:
            deductions.append(
                (float(config.get("no_outputs_penalty", 7)),
                 "the notebook was submitted with no saved output at all, so there is "
                 "no evidence it was ever run — and without the dataset the grader "
                 "cannot run it either")
            )
        elif good_outputs:
            coverage = min(good_outputs / max(analysis.n_code_cells, 1), 1.0)
            if coverage < float(config.get("min_output_coverage", 0.5)):
                deductions.append(
                    (float(config.get("low_coverage_penalty", 3)),
                     f"only {good_outputs} of {analysis.n_code_cells} code cells carry "
                     "saved output, so the notebook looks partly run")
                )

        if errors:
            each = float(config.get("error_penalty_each", 3))
            cap = float(config.get("max_error_penalty", 7))
            first = errors[0]
            deductions.append(
                (min(each * len(errors), cap),
                 f"{len(errors)} cell(s) show errors in the submitted notebook, "
                 f"starting at code cell {first.get('cell')}: "
                 f"{first.get('ename')}: {first.get('evalue')}")
            )

        if analysis.has_syntax_error:
            deductions.append((2.0, "some cells could not be parsed as Python"))

        evidence: dict[str, Any] = {
            "verified_by": "the submitted notebook's saved state",
            "n_code_cells": analysis.n_code_cells,
            "stored_outputs": outputs,
            "stored_errors": errors[:5],
            "grading_run_error": ctx.execution.error_message,
            "note": (
                "The grading run cannot be used here: students do not submit their "
                "dataset, so the notebook cannot be re-executed."
            ),
        }
        urls = _remote_reads(ctx)
        if urls:
            evidence["remote_reads"] = urls[:5]

        score = max(float(item.points) - sum(d[0] for d in deductions), 0.0)
        if not deductions:
            return self.result(
                item, score, STATUS_PASS, 0.85,
                f"The submitted notebook shows a complete run: {good_outputs} outputs "
                f"across {analysis.n_code_cells} code cells and no errors.",
                evidence,
            )
        return self.result(
            item, score, STATUS_PARTIAL if score > 0 else STATUS_FAIL, 0.85,
            "Deductions: " + "; ".join(f"{why} (-{pts:g})" for pts, why in deductions),
            evidence,
        )

    # -----------------------------------------------------------------
    # Part 1: the dataset
    # -----------------------------------------------------------------
    def check_data_loading(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        """Is a dataset loaded, and loaded the way the instructions ask?

        Deliberately narrow. Students pick their own dataset and do not hand it
        in, so there is nothing to compare against and nothing about the data's
        contents is graded — only that the notebook reads one, with pandas,
        through a relative path.
        """
        analysis = ctx.analysis
        config = item.config
        deductions: list[tuple[float, str]] = []

        wanted = list(config.get("required_imports", ["pandas"]))
        alternatives = list(config.get("import_alternatives", []))
        if not (set(wanted) & analysis.imports) and not (set(alternatives) & analysis.imports):
            deductions.append((2.0, f"missing import: {', '.join(wanted)}"))

        if not analysis.read_calls:
            deductions.append(
                (float(config.get("missing_read_penalty", 5)),
                 "no pandas read_* call was found, so no dataset appears to be loaded")
            )

        if analysis.absolute_paths:
            deductions.append(
                (float(config.get("absolute_path_penalty", 4)),
                 "absolute file path(s) used instead of a relative path: "
                 + ", ".join(analysis.absolute_paths[:3]))
            )

        urls = _remote_reads(ctx)
        if urls:
            deductions.append(
                (float(config.get("remote_read_penalty", 4)),
                 f"data is downloaded at run time ({urls[0]}) rather than read from a "
                 "relative path")
            )

        evidence: dict[str, Any] = {
            "imports": sorted(analysis.imports),
            "read_calls": analysis.read_calls,
            "referenced_files": analysis.referenced_files,
            "relative_paths": [
                literal for literal in analysis.data_path_literals
                if not URL_RE.match(literal) and literal not in analysis.absolute_paths
            ][:8],
            "absolute_paths": analysis.absolute_paths,
            "remote_reads": urls[:5],
            "note": "Only the loading step is graded; the dataset itself is not submitted.",
        }
        if analysis.unparsed_cells:
            evidence["cells_not_statically_parsed"] = analysis.unparsed_cells

        score = max(float(item.points) - sum(d[0] for d in deductions), 0.0)
        if not deductions:
            path = (analysis.referenced_files or evidence["relative_paths"] or ["?"])[0]
            return self.result(
                item, score, STATUS_PASS, 1.0,
                f"A dataset is loaded with pandas from the relative path `{path}`.",
                evidence,
            )
        return self.result(
            item, score, STATUS_PARTIAL if score > 0 else STATUS_FAIL, 1.0,
            "Deductions: " + "; ".join(f"{why} (-{pts:g})" for pts, why in deductions),
            evidence,
        )

    # -----------------------------------------------------------------
    # Part 2a: the charts themselves
    # -----------------------------------------------------------------
    def check_matplotlib_chart(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        return self._chart_presence(ctx, item, MATPLOTLIB)

    def check_seaborn_chart(self, ctx: GradingContext, item: RubricItem) -> RubricItemResult:
        return self._chart_presence(ctx, item, SEABORN)

    def check_altair_charts(self, ctx: GradingContext, item: RubricItem) -> RubricItemResult:
        return self._chart_presence(ctx, item, ALTAIR)

    def _chart_presence(
        self, ctx: GradingContext, item: RubricItem, library: str
    ) -> RubricItemResult:
        evidence = self.evidence(ctx)
        if evidence.source == chartlib.SOURCE_NONE:
            return self.no_evidence_result(item, ctx, evidence)

        config = item.config
        required = int(config.get("required_count", 1))
        label = LIBRARY_LABELS.get(library, library)
        found = evidence.by_library(library)
        rendered = [c for c in found if c.ok]
        unrendered = [c for c in found if not c.ok]

        payload = {
            **self.evidence_note(evidence),
            "charts_found": len(found),
            "charts_rendered": len(rendered),
            "required": required,
            "chart_details": [c.summary() for c in found[:6]],
        }

        if not found:
            return self.result(
                item, 0.0, STATUS_NOT_FOUND, 0.9,
                f"No {label} chart was found in the notebook.", payload,
            )

        # A chart that ran and produced an image (or a Vega-Lite spec) counts in
        # full; one that only exists as code counts for less, because "the chart"
        # the assignment asks for is the drawn thing.
        partial_ratio = float(config.get("not_rendered_credit_ratio", 0.5))
        credited = min(len(rendered), required) + min(
            max(required - len(rendered), 0), len(unrendered)
        ) * partial_ratio
        ratio = credited / required if required else 1.0

        distinct_note = None
        if library == ALTAIR and len(found) >= required:
            duplicates = _duplicate_charts(found)
            if duplicates:
                penalty = float(config.get("distinctness_penalty_ratio", 0.25))
                ratio = max(ratio - penalty * len(duplicates), 0.0)
                distinct_note = (
                    f"{len(duplicates) + 1} of the charts encode the same fields with "
                    "the same mark, so they are not three distinct charts"
                )
                payload["duplicate_signatures"] = duplicates

        score = float(item.points) * min(ratio, 1.0)
        confidence = self._confidence(evidence, item, records=found)

        problems = []
        if len(found) < required:
            problems.append(f"found {len(found)} of the {required} required {label} charts")
        if unrendered:
            problems.append(
                f"{len(unrendered)} {label} chart(s) produced no output — "
                + "; ".join(
                    (c.error or f"code cell {c.code_cell} drew nothing")
                    for c in unrendered[:2]
                )
            )
        if distinct_note:
            problems.append(distinct_note)

        if not problems:
            return self.result(
                item, item.points, STATUS_PASS, confidence,
                f"{len(rendered)} {label} chart(s) drawn and rendered "
                f"(code cell{'s' if len(rendered) > 1 else ''} "
                + ", ".join(str(c.code_cell) for c in rendered[:5]) + ").",
                payload,
            )
        return self.result(
            item, score, STATUS_PARTIAL if score > 0 else STATUS_FAIL, confidence,
            _sentence("; ".join(problems)), payload,
        )

    # -----------------------------------------------------------------
    # Part 2b: what the Altair charts do
    # -----------------------------------------------------------------
    def check_altair_transformation(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        evidence = self.evidence(ctx)
        if evidence.source == chartlib.SOURCE_NONE:
            return self.no_evidence_result(item, ctx, evidence)

        found = evidence.by_library(ALTAIR)
        with_transform = [c for c in found if c.facts.has_transformation]
        operations: list[str] = []
        for record in with_transform:
            operations.extend(record.facts.transform_ops)
            operations.extend(record.facts.encoding_transforms)

        payload = {
            **self.evidence_note(evidence),
            "charts_with_transformation": [c.code_cell for c in with_transform],
            "operations": sorted(set(operations))[:12],
            "specs_available": sum(1 for c in found if c.specs),
        }

        if with_transform:
            return self.result(
                item, item.points, STATUS_PASS,
                self._confidence(evidence, item, records=with_transform),
                "Transformation found in the compiled chart specification: "
                + ", ".join(sorted(set(operations))[:5]) + ".",
                payload,
            )

        # No spec to read — fall back to what the source says, at reduced credit
        # and reduced confidence, because source text is an intention rather than
        # a result.
        return self._static_fallback(
            ctx, item, evidence, found, payload,
            what="a transformation (mean, count, binning, …)",
        )

    def check_altair_brush_selection(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        evidence = self.evidence(ctx)
        if evidence.source == chartlib.SOURCE_NONE:
            return self.no_evidence_result(item, ctx, evidence)

        config = item.config
        found = evidence.by_library(ALTAIR)
        brushed = [c for c in found if c.facts.has_brush]
        # Distinguished deliberately: a point selection is a selection, and
        # `.interactive()` is neither — it binds an interval to the scales for
        # pan and zoom. Only the first of those is a brush.
        point_only = [
            c for c in found
            if not c.facts.has_brush
            and any(s.get("type") == "point" for s in c.facts.selections)
        ]
        zoom_only = [
            c for c in found
            if not c.facts.has_brush
            and any(s.get("bind") == "scales" for s in c.facts.selections)
        ]

        payload = {
            **self.evidence_note(evidence),
            "charts_with_brush": [c.code_cell for c in brushed],
            "brushes": [b for c in brushed for b in c.facts.brushes][:5],
            "point_selection_only": [c.code_cell for c in point_only],
            "pan_zoom_only": [c.code_cell for c in zoom_only],
            "specs_available": sum(1 for c in found if c.specs),
        }

        if brushed:
            encodings = brushed[0].facts.brushes[0].get("encodings")
            detail = f" over {', '.join(encodings)}" if encodings else ""
            return self.result(
                item, item.points, STATUS_PASS,
                self._confidence(evidence, item, records=brushed),
                f"Interval (brush) selection found on the chart in code cell "
                f"{brushed[0].code_cell}{detail}.",
                payload,
            )

        if point_only:
            ratio = float(config.get("point_selection_credit_ratio", 0.5))
            return self.result(
                item, item.points * ratio, STATUS_PARTIAL,
                self._confidence(evidence, item, records=point_only),
                "A selection is present, but it is a point selection rather than the "
                "interval brush the assignment asks for. `alt.selection_interval()` "
                "creates a brush.",
                payload,
            )

        if zoom_only:
            return self.result(
                item, 0.0, STATUS_FAIL, self._confidence(evidence, item, records=zoom_only),
                "The only interval selection in the notebook is bound to the scales by "
                "`.interactive()`, which pans and zooms rather than selecting data. Add "
                "`alt.selection_interval()` and attach it with `.add_params()`.",
                payload,
            )

        return self._static_fallback(
            ctx, item, evidence, found, payload, what="a brush selection",
        )

    def _static_fallback(
        self,
        ctx: GradingContext,
        item: RubricItem,
        evidence: ChartEvidence,
        found: list[ChartRecord],
        payload: dict[str, Any],
        what: str,
    ) -> RubricItemResult:
        """Grade from source text when no chart specification was captured.

        This is the honest degraded mode: the code says the student tried, but
        nothing proves the chart compiled that way, so it earns partial credit at
        low confidence and goes to a person.
        """
        patterns = list(item.config.get("source_patterns", []))
        source = "\n".join(record.source for record in found) or ctx.analysis.code_source
        hits = [p for p in patterns if p in source]
        payload["source_matches"] = hits[:8]

        if not found:
            return self.result(
                item, 0.0, STATUS_NOT_FOUND, 0.9,
                f"No Altair chart was found, so {what} could not be found either.",
                payload,
            )
        if not hits:
            return self.result(
                item, 0.0, STATUS_FAIL, self._confidence(evidence, item, base=0.9,
                                                        records=found),
                f"No Altair chart uses {what}.", payload,
            )
        ratio = float(item.config.get("static_only_credit_ratio", 0.5))
        return self.result(
            item, item.points * ratio, STATUS_PARTIAL, 0.4,
            f"The code looks like it uses {what} ({', '.join(hits[:3])}), but no chart "
            "specification was captured to confirm it — the chart may not have "
            "rendered. Please confirm by opening the notebook.",
            payload,
        )

    # -----------------------------------------------------------------
    # Extra credit
    # -----------------------------------------------------------------
    def check_altair_dashboard_extra_credit(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        evidence = self.evidence(ctx)
        suggested = item.config.get("suggested_points", 5)
        found = evidence.by_library(ALTAIR)
        dashboards = [c for c in found if c.facts.has_cross_filter]

        payload = {
            **self.evidence_note(evidence),
            "dashboard_cells": [c.code_cell for c in dashboards],
            "cross_filter_params": [
                p for c in dashboards for p in c.facts.cross_filter_params
            ][:5],
            "composition": [c.facts.composition for c in dashboards][:3],
            "suggested_points": suggested,
        }

        if dashboards:
            record = dashboards[0]
            return self.result(
                item, 0.0, STATUS_MANUAL_REVIEW, 0.9,
                f"Extra credit earned: code cell {record.code_cell} composes "
                f"{'/'.join(record.facts.composition) or 'multiple views'} where a "
                "selection cross-filters another chart via transform_filter(). Award "
                f"the bonus (suggested: {suggested} points) with a manual override on "
                "this item — it adds to the total without changing the maximum.",
                payload,
            )

        # A composed chart with a filter that is *not* driven by a selection is
        # the near miss worth telling a TA about.
        near = [
            c for c in found
            if c.facts.is_multi_view and (c.facts.filter_params or c.facts.condition_params)
        ]
        if near:
            payload["near_miss_cells"] = [c.code_cell for c in near]
            return self.result(
                item, 0.0, STATUS_MANUAL_REVIEW, 0.5,
                f"Code cell {near[0].code_cell} composes several charts and references a "
                "selection, but no chart filters on it via transform_filter(). Worth a "
                "look before deciding on the bonus.",
                payload,
            )
        return self.result(
            item, 0.0, STATUS_NOT_FOUND, 0.9,
            "No cross-filtered Altair dashboard was found; no extra credit.", payload,
        )

    # -----------------------------------------------------------------
    # Judgement items — always returned for a human read
    # -----------------------------------------------------------------
    def check_matplotlib_rationale(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        return self._rationale(
            ctx, item, MATPLOTLIB,
            question=(
                "Explain what aspect of the dataset this chart shows and why matplotlib "
                "is the right tool for it."
            ),
        )

    def check_seaborn_rationale(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        return self._rationale(
            ctx, item, SEABORN,
            question=(
                "Explain the motivation for the type of seaborn plot chosen and why it "
                "fits this data."
            ),
        )

    def _rationale(
        self, ctx: GradingContext, item: RubricItem, library: str, question: str
    ) -> RubricItemResult:
        evidence = self.evidence(ctx)
        config = item.config
        label = LIBRARY_LABELS.get(library, library)
        min_words = int(config.get("min_words", 25))
        partial_words = int(config.get("partial_words", 10))
        keywords = [k.lower() for k in config.get("keywords", [])]

        text, where = _rationale_text(evidence, library, ctx)
        words = chartlib.prose_word_count(text)
        hits = [k for k in keywords if k in text.lower()]

        if words >= min_words and len(hits) >= 2:
            ratio, note = 1.0, "a full written rationale"
        elif words >= min_words:
            ratio, note = 0.8, "a rationale of the right length, but it does not clearly give a reason"
        elif words >= partial_words:
            ratio, note = 0.5, f"a short rationale ({words} words)"
        elif words > 0:
            ratio, note = 0.25, f"only a passing mention ({words} words)"
        else:
            ratio, note = 0.0, "no written rationale near the chart"

        payload = {
            **self.evidence_note(evidence),
            "text_found_in": where,
            "word_count": words,
            "keyword_hits": hits,
            "text": text[:1500],
        }
        feedback = (
            f"Provisional: {note} for the {label} chart. "
            "Read the text below and confirm or adjust."
        )
        return self._for_human(ctx, item, ratio, feedback, payload, question, text)

    def check_matplotlib_aesthetics(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        evidence = self.evidence(ctx)
        config = item.config
        weights: dict[str, float] = {
            str(k): float(v) for k, v in (config.get("weighted_signals") or {}).items()
        }
        charts = evidence.by_library(MATPLOTLIB)

        payload: dict[str, Any] = {**self.evidence_note(evidence)}
        if not charts:
            return self._for_human(
                ctx, item, 0.0,
                "Provisional: no matplotlib chart was found, so there is nothing to "
                "judge for colour and clarity.",
                payload,
            )

        # A chart that actually came out wins over a better-dressed one that
        # crashed: the assignment marks the picture, not the intention.
        best = max(charts, key=lambda c: (c.ok, _weighted(c.aesthetics, weights)))
        present = sorted(k for k, v in best.aesthetics.items() if v)
        missing = sorted(k for k, v in best.aesthetics.items() if not v and k in weights)
        total = sum(weights.values()) or 1.0
        ratio = _weighted(best.aesthetics, weights) / total
        ceiling = float(config.get("provisional_ceiling_ratio", 0.8))
        if not best.ok:
            ratio *= 0.5

        payload.update(
            {
                "code_cell": best.code_cell,
                "rendered": best.ok,
                "signals_present": present,
                "signals_missing": missing,
                "source": best.source[:1200],
            }
        )
        feedback = (
            f"Provisional from labelling and colour signals in code cell {best.code_cell} "
            f"(present: {', '.join(present) or 'none'}"
            + (f"; missing: {', '.join(missing)}" if missing else "")
            + "). These signals cannot tell whether the chart actually reads well — "
            "open the rendered image and set the mark for colour choices and clarity."
        )
        # Never LLM-graded: this item is about a picture, and only the rendered
        # image answers the question the assignment asks.
        return self._for_human(ctx, item, min(ratio, ceiling), feedback, payload)

    def check_chart_conclusions(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        evidence = self.evidence(ctx)
        config = item.config
        min_words = int(config.get("min_words", 15))
        partial_words = int(config.get("partial_words", 6))
        expected = int(config.get("expected_charts", 5))

        covered = 0.0
        detail: list[dict[str, Any]] = []
        for library in (MATPLOTLIB, SEABORN, ALTAIR):
            required = self.required_count(library)
            charts = evidence.by_library(library)
            # Best charts first: a student with five Altair charts, three of them
            # discussed, has met the requirement.
            charts = sorted(charts, key=lambda c: c.discussion_words, reverse=True)
            for record in charts[:required]:
                if record.discussion_words >= min_words:
                    credit = 1.0
                elif record.discussion_words >= partial_words:
                    credit = 0.5
                else:
                    credit = 0.0
                covered += credit
                detail.append(
                    {
                        "library": record.library,
                        "code_cell": record.code_cell,
                        "words": record.discussion_words,
                        "credit": credit,
                        "discussion": record.discussion[:400],
                    }
                )
            for _ in range(max(required - len(charts), 0)):
                detail.append({"library": library, "code_cell": None, "words": 0,
                               "credit": 0.0, "discussion": "(no such chart)"})

        ratio = covered / expected if expected else 0.0
        missing = [d for d in detail if d["credit"] < 1.0]
        payload = {
            **self.evidence_note(evidence),
            "expected_charts": expected,
            "covered": round(covered, 2),
            "per_chart": detail,
        }
        feedback = (
            f"Provisional: {covered:g} of {expected} required charts have a written "
            "discussion in the markdown cell below them"
            + (
                "; missing or too short under "
                + ", ".join(
                    f"{d['library']} cell {d['code_cell']}" if d["code_cell"]
                    else f"{d['library']} (chart not found)"
                    for d in missing[:4]
                )
                if missing else ""
            )
            + ". Position and length are checked automatically; whether each "
            "discussion states a conclusion is for you to judge."
        )
        joined = "\n\n---\n\n".join(
            f"[{d['library']} cell {d['code_cell']}] {d['discussion']}"
            for d in detail if d["discussion"] and d["code_cell"]
        )
        return self._for_human(
            ctx, item, ratio, feedback, payload,
            question=(
                "Do these markdown cells each state the main conclusion of the chart "
                "above them?"
            ),
            response=joined,
        )

    # -----------------------------------------------------------------
    # Judgement plumbing
    # -----------------------------------------------------------------
    def _for_human(
        self,
        ctx: GradingContext,
        item: RubricItem,
        ratio: float,
        feedback: str,
        evidence: dict[str, Any],
        question: str | None = None,
        response: str = "",
    ) -> RubricItemResult:
        """Return a judgement item with a provisional score, for a human to confirm.

        The provisional score is a starting point, not a verdict, so the status
        is ``manual_review`` and the confidence is deliberately low: it exists so
        a TA adjusts a number rather than inventing one.

        When LLM grading is switched on and the model is confident enough to
        defend its own judgement, its score replaces the provisional one and the
        item passes through without a human — that is the whole point of the
        setting, and ``grader/llm.py`` routes anything less back here.
        """
        provisional = float(item.points) * max(0.0, min(ratio, 1.0))
        evidence = dict(evidence)
        evidence["provisional_score"] = round(provisional, 2)
        evidence["provisional_basis"] = "structural signals"

        grader = ctx.qualitative_grader
        if question and response.strip() and getattr(grader, "enabled", False):
            judgement = grader.grade(
                question,
                response,
                {
                    "max_score": float(item.points),
                    "criteria": item.config.get("llm_criteria") or [],
                },
            )
            evidence["llm"] = {
                k: v for k, v in judgement.items() if k != "feedback"
            }
            evidence["llm_feedback"] = judgement.get("feedback", "")
            if not judgement.get("manual_review", True) and not judgement.get("error"):
                score = float(judgement.get("score", provisional))
                status = STATUS_PASS if score >= item.points else (
                    STATUS_PARTIAL if score > 0 else STATUS_FAIL
                )
                evidence["provisional_basis"] = "LLM judgement"
                return self.result(
                    item, score, status, float(judgement.get("confidence", 0.8)),
                    (judgement.get("feedback") or "").strip() or feedback,
                    evidence,
                )
            if judgement.get("feedback"):
                feedback += f" LLM note: {judgement['feedback'][:400]}"

        return self.result(item, provisional, STATUS_MANUAL_REVIEW, 0.35, feedback, evidence)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sentence(text: str) -> str:
    """Upper-case the first letter only.

    ``str.capitalize`` lower-cases everything after it, which turns a
    ``NameError`` in a student's traceback into ``nameerror``.
    """
    text = text.strip()
    if not text:
        return ""
    return text[0].upper() + text[1:] + ("" if text.endswith(".") else ".")


def _weighted(signals: dict[str, bool], weights: dict[str, float]) -> float:
    return sum(weight for name, weight in weights.items() if signals.get(name))


def _remote_reads(ctx: GradingContext) -> list[str]:
    """URLs the notebook reads data from, in the order they appear."""
    found: list[str] = []
    for candidate in list(ctx.analysis.referenced_files) + list(ctx.analysis.data_path_literals):
        if URL_RE.match(str(candidate)) and candidate not in found:
            found.append(str(candidate))
    for match in URL_RE.finditer(ctx.analysis.code_source):
        url = match.group(0)
        if any(url.lower().endswith(suffix) for suffix in
               (".csv", ".json", ".geojson", ".xlsx", ".parquet", ".zip")) and url not in found:
            found.append(url)
    return found


def _rationale_text(
    evidence: ChartEvidence, library: str, ctx: GradingContext
) -> tuple[str, str]:
    """Prose a student wrote about one library's chart.

    Looked for beside the chart first (that is where it belongs), then anywhere
    in the notebook that names the library — a rationale written three cells
    early is still a rationale, and should not be scored as absent.
    """
    charts = evidence.by_library(library)
    pieces: list[str] = []
    for record in charts:
        for text in (record.preamble, record.discussion):
            if text and text not in pieces:
                pieces.append(text)
    if pieces:
        return "\n\n".join(pieces), f"markdown beside the {library} chart"

    named = [
        cell for cell in ctx.analysis.markdown_cells
        if library in cell.lower() and chartlib.prose_word_count(cell) >= 5
    ]
    if named:
        return "\n\n".join(named[:3]), f"markdown elsewhere mentioning {library}"
    return "", "not found"


def _duplicate_charts(records: list[ChartRecord]) -> list[str]:
    """Signatures shared by more than one chart — the same chart drawn twice."""
    seen: dict[str, int] = {}
    for record in records:
        marks = ",".join(sorted(record.facts.marks))
        fields = ",".join(sorted(record.facts.fields))
        if not marks and not fields:
            continue  # no spec captured; distinctness cannot be judged
        signature = f"{marks}|{fields}"
        seen[signature] = seen.get(signature, 0) + 1
    return [signature for signature, count in seen.items() if count > 1]
