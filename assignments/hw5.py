"""Assignment 5 autograder — Yelp restaurants and census income.

Like Assignment 4, this assignment is graded **without running the notebook**
(``execution: never`` in ``rubrics/hw5.yaml``). 1.1 queries the Census API
through cenpy and 1.2 downloads TIGER tracts through pygris, so a re-run would
repeat both downloads once per student. And the restaurants come from the Yelp
Dataset Challenge, 8 GB in full: a notebook that reads the full dump rather
than the 400 KB Philadelphia extract would take minutes and exhaust the grading
machine's memory. Nothing here opens a data file — not the extract, not the
dump. A notebook that reads the dump is named in 1.3's feedback, not penalised.

What is graded is the file the student handed in, read the way HW4 reads it
(``HW4Grader`` supplies the shared machinery): the code they wrote, and the
outputs their own run saved. The one difference is how code is assigned to a
step. The template has a ``### 1.x`` heading above each step's empty cell, so
each code cell is graded under the heading it sits beneath — otherwise the
``merge`` written for 1.5 would also satisfy 1.2's merge.

Reference numbers — 7,350 restaurants, Philadelphia's ~408 tracts — only raise
confidence; a number outside its range sends an item to a person.
"""

from __future__ import annotations

import re
from typing import Any

import nbformat

from grader import charts as chartlib
from grader.models import STATUS_FAIL, STATUS_PARTIAL, STATUS_PASS, RubricItemResult
from grader.rubric import RubricItem

from .base import GradingContext, register
from .hw4 import (
    CORROBORATED_CONFIDENCE,
    DOUBT_CONFIDENCE,
    CodeCell,
    HW4Grader,
    strip_comments,
)

# "### 1.3 Load the restaurants data" -> "1.3".
SECTION_RE = re.compile(r"^\s*#{1,6}\s*(?:\*\*)?\s*(\d+\.\d+)\b", re.M)


def _normalise(text: str) -> str:
    return " ".join((text or "").split())


@register
class HW5Grader(HW4Grader):
    assignment_id = "hw5"

    # -- which step each cell belongs to ----------------------------------
    def layout(self, ctx: GradingContext) -> dict[str, Any]:
        """Code-cell numbers and the student's own markdown, by ``1.x`` heading.

        Lines copied from the template's markdown are left out of ``markdown``,
        so only what the student wrote — the answer to 1.6's question, in a new
        cell or typed into the template's own — is kept.
        """
        cached = ctx.cache.get("hw5_layout")
        if cached is not None:
            return cached
        template_lines: set[str] = set()
        template = self.template_path()
        if template is not None and template.is_file():
            try:
                for cell in nbformat.read(str(template), as_version=4).cells:
                    if cell.get("cell_type") == "markdown":
                        template_lines |= {
                            _normalise(line) for line in (cell.get("source") or "").splitlines()
                        }
            except Exception:
                pass
        code_cells: dict[str, list[int]] = {}
        markdown: dict[str, list[str]] = {}
        try:
            notebook = nbformat.read(str(ctx.analysis.path), as_version=4)
            cells = notebook.cells
        except Exception:
            cells = []
        section = ""
        number = 0
        for cell in cells:
            source = cell.get("source") or ""
            if cell.get("cell_type") == "markdown":
                headings = SECTION_RE.findall(source)
                if headings:
                    section = headings[-1]
                own = "\n".join(
                    line for line in source.splitlines()
                    if _normalise(line) and _normalise(line) not in template_lines
                    and not SECTION_RE.match(line)
                )
                if own:
                    markdown.setdefault(section, []).append(own)
            elif cell.get("cell_type") == "code":
                number += 1
                code_cells.setdefault(section, []).append(number)
        cached = {"code": code_cells, "markdown": markdown,
                  "has_headings": any(key for key in code_cells)}
        ctx.cache["hw5_layout"] = cached
        return cached

    def section_cells(
        self, ctx: GradingContext, section: str
    ) -> tuple[list[CodeCell], str]:
        """The student's code under a heading, and a note when that failed.

        A notebook whose headings were all deleted is graded on all its code. A
        step with no code under its heading earns nothing from code written for
        other steps — the 1.5 merge must not count as 1.2's — but the note sends
        it to a person, in case the step was done somewhere else.
        """
        cells = self.code(ctx).cells
        layout = self.layout(ctx)
        numbers = set(layout["code"].get(section, []))
        mine = [c for c in cells if c.number in numbers and c.student.strip()]
        if mine:
            return mine, ""
        if not layout["has_headings"]:
            return list(cells), "The notebook has no 1.x headings, so all its code was read."
        return [], (
            f"There is no code under the {section} heading; if the step was done "
            "elsewhere in the notebook, please grade it by hand."
        )

    def section_steps(self, ctx: GradingContext, item: RubricItem) -> RubricItemResult:
        """A step graded on the code under its heading, backed by the saved run."""
        section = str(item.config.get("section", ""))
        cells, placement = self.section_cells(ctx, section)
        deductions, met = self.run_requirements(
            item.config.get("requirements") or [], self.code(ctx).text(cells)
        )
        confidence, note = self.run_state(ctx, cells)
        notes = [n for n in (placement, note) if n]
        if placement:
            confidence = min(confidence, DOUBT_CONFIDENCE)
        evidence: dict[str, Any] = {
            "graded_from": "the submitted notebook's code (not executed)",
            "section": section,
            "requirements_met": met,
            "requirements_missing": [why for _, why in deductions],
            "cells": [cell.number for cell in cells][:8],
            "code": "\n\n".join(cell.student for cell in cells)[:1500],
        }
        if notes:
            evidence["notes"] = notes
        return self.scored(
            item, deductions, evidence, confidence,
            f"All {len(met)} parts of step {section} are in the notebook.", notes,
        )

    def _corroborate_count(
        self, result: RubricItemResult, ctx: GradingContext, item: RubricItem, what: str
    ) -> RubricItemResult:
        """A count the student's run showed, inside the expected range, raises confidence."""
        low, high = item.config.get("count_range") or item.config.get("tract_count_range")
        cells, _ = self.section_cells(ctx, str(item.config.get("section", "")))
        counts = self._counts_near(ctx, cells, span=1)
        in_range = [n for n in counts if low <= n <= high]
        result.evidence[f"{what}_counts_shown"] = counts[:10]
        result.evidence[f"expected_{what}"] = f"{low:,}-{high:,}"
        if in_range and result.confidence >= DOUBT_CONFIDENCE:
            result.confidence = max(result.confidence, CORROBORATED_CONFIDENCE)
            result.feedback += f" The saved run shows {in_range[0]:,} {what}."
        return result

    # =====================================================================
    # Part 1
    # =====================================================================
    check_census_tracts = section_steps
    check_spatial_join = section_steps
    check_income_merge = section_steps

    def check_census_income(self, ctx: GradingContext, item: RubricItem) -> RubricItemResult:
        result = self.section_steps(ctx, item)
        source = "\n".join(c.code for c in self.code(ctx).cells)
        philadelphia = any(
            re.search(p, source) for p in item.config.get("philadelphia_patterns") or []
        )
        result.evidence["philadelphia"] = philadelphia
        if not philadelphia:
            # The template lets students choose a county, but the restaurants
            # are all in Philadelphia, so another county joins to almost none.
            result.feedback += (
                " The query does not name Philadelphia (county 101); the Yelp "
                "restaurants are all in Philadelphia, so please check the county."
            )
            result.confidence = min(result.confidence, DOUBT_CONFIDENCE)
            return result
        return self._corroborate_count(result, ctx, item, "tracts")

    def check_restaurants(self, ctx: GradingContext, item: RubricItem) -> RubricItemResult:
        """The steps, latitude passed as x, and whether the 8 GB dump is read."""
        config = item.config
        result = self.section_steps(ctx, item)
        cells, _ = self.section_cells(ctx, str(config.get("section", "")))
        swapped = self._swapped_coordinates(
            cells, config.get("x_column", "longitude"), config.get("y_column", "latitude")
        )
        if swapped:
            penalty = float(config.get("swapped_coordinates_penalty", 2))
            score = max(result.automatic_score - penalty, 0.0)
            result.evidence["swapped_coordinates"] = swapped
            note = (
                f"Latitude is passed as x: `{swapped}`. points_from_xy takes longitude "
                f"as x and latitude as y (-{penalty:g})."
            )
            result = self.result(
                item, score, STATUS_PARTIAL if score > 0 else STATUS_FAIL,
                result.confidence,
                note if result.status == STATUS_PASS else f"{result.feedback} {note}",
                result.evidence,
            )

        full_dump = sorted({
            match.group(0)
            for cell in self.code(ctx).cells
            for pattern in config.get("full_dataset_patterns") or []
            for match in [re.search(pattern, strip_comments(cell.source))]
            if match
        })
        if full_dump:
            result.evidence["reads_full_yelp_dataset"] = full_dump
            result.feedback += (
                " The notebook reads the full Yelp dataset ("
                + ", ".join(full_dump)
                + ") rather than the provided restaurants_philly.json.gz; that is not "
                "penalised, but it is 8 GB and the grader does not open it."
            )
        return self._corroborate_count(result, ctx, item, "restaurants")

    # -- 1.6 ----------------------------------------------------------------
    def check_stars_income_plot(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        config = item.config
        section = str(config.get("section", "1.6"))
        cells, placement = self.section_cells(ctx, section)
        plot_cells = [
            c for c in cells
            if any(re.search(p, c.student) for p in config.get("plot_any") or [])
        ]
        text = "\n".join(c.student for c in plot_cells)
        deductions: list[tuple[float, str]] = []

        if not plot_cells:
            deductions.append((float(config.get("plot_points", 3))
                               + float(config.get("seaborn_points", 1)),
                               "a line plot of average income by star rating"))
        elif not any(re.search(p, text) for p in config.get("seaborn_any") or []):
            deductions.append((float(config.get("seaborn_points", 1)),
                               "the plot drawn with seaborn.lineplot"))
        if not any(re.search(p, text) for p in config.get("stars_x") or []):
            deductions.append((float(config.get("stars_x_points", 2)), "stars on the x axis"))
        income_y = re.search(r"\by\s*=\s*[\"'](?!stars[\"'])\w", text) or re.search(
            r"groupby\(\s*[\"']stars[\"']\s*\)\s*\[", text
        )
        if not income_y:
            deductions.append((float(config.get("income_y_points", 2)),
                               "median household income on the y axis"))

        rendered = []
        for cell in plot_cells:
            answer = self.answer_cell(ctx, cell.number)
            if answer is not None and answer.images and not answer.errored:
                rendered.append(cell.number)
        if not rendered:
            deductions.append((float(config.get("rendered_points", 4)),
                               "the rendered plot in the submitted notebook's output"))

        labels = chartlib.aesthetic_signals(text) if text else {}
        labelled = [k for k in ("title", "x_label", "y_label") if labels.get(k)]
        if len(labelled) < 2:
            deductions.append((float(config.get("labels_points", 1)),
                               "a title and axis labels on the figure"))

        min_words = int(config.get("answer_min_words", 12))
        pattern = str(config.get("answer_pattern", "income"))
        written = [
            text_ for text_ in self.layout(ctx)["markdown"].get(section, [])
            if len(text_.split()) >= min_words and re.search(pattern, text_)
        ]
        if not written:
            deductions.append((float(config.get("answer_points", 2)),
                               "a written answer on whether ratings and income are correlated"))

        evidence = {
            "graded_from": "the submitted notebook (not executed)",
            "plot_cells": [c.number for c in plot_cells],
            "rendered_in_cells": rendered,
            "labels": labels,
            "code": text[:1200],
            "written_answer": written[-1][:800] if written else "",
        }
        notes = [placement] if placement else []
        confidence = CORROBORATED_CONFIDENCE if rendered else 0.85
        if placement:
            confidence = min(confidence, DOUBT_CONFIDENCE)
        return self.scored(
            item, deductions, evidence, confidence,
            f"The line plot of income by stars is drawn in code cell "
            f"{rendered[0] if rendered else '?'}, labelled, and the question is answered.",
            notes,
        )
