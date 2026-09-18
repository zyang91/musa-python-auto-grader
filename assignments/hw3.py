"""Assignment 3 autograder — evictions, code violations and the NDVI.

Graded against ``assignment_template/assignment-3.ipynb``.

Why this grader looks nothing like the other two
------------------------------------------------
Assignments 1 and 2 have no answer key: one class downloads its own Zillow
extract, the other picks its own dataset. Assignment 3 hands out one zip file
and everyone uses it, so for the first time the right answers are *known*.
Philadelphia has 384 census tracts in ``PA-tracts.geojson``; the fifteen listed
violation types cover 34,108 rows of ``li_violations.csv``; the median NDVI
inside the city limits is 0.2025. Those are facts about the shipped data, so the
checks below compare against them rather than inferring intent.

That also changes what confidence means here. In Assignment 1 several frames may
plausibly be "the Philadelphia subset", and the ambiguity is the finding. Here a
frame either carries 384 Philadelphia tracts or it does not; if one does, the
step demonstrably happened, and it does not matter which variable holds it. So a
matched expected value scores at confidence 1.0, and confidence drops only where
the grader is choosing between readings of a partial answer.

Where the evidence comes from
-----------------------------
Two places, and every item is graded on both.

The first is the notebook the student handed in. Re-running is the fragile part
here — five data files read from whatever relative path each student used — and
when the placement misses, the notebook dies at the first ``read_file`` and a
correct submission grades as a column of zeros. Their own run did not have that
problem, and the file carries what it printed: ``384``, ``34108``,
``Median NDVI, city: 0.2025``, and ``:HoloMap [year]`` for the chart in 1.1.5.
``grader/answers.py`` harvests those, and the evaluators at the bottom of this
module read them.

The second is the probe payload, extended for this assignment (see
``grader/probe_runtime.py``): GeoDataFrames now carry their CRS, geometry types
and total area; numpy arrays carry NaN-aware statistics, which is the only way to
describe an NDVI array that is mostly NaN; shapely geometries and open rasterio
datasets are described in place.

The plots are the interesting part. An hvplot call returns a holoviews object
that knows what it is — a HoloMap carries the dimension its widget selects and
one frame per value of it, a Layout carries its row/column shape — and those
objects are read out of the kernel, ``Out`` included, because
``df.hvplot(...)`` on the last line of a cell is never bound to a name. So
``groupby=`` and ``dynamic=False`` are graded by their effect rather than by
searching the source for the keywords.

The matplotlib figures (the hex bin map, the two tree plots) have no such
structure, only a picture, so those reuse ``grader/charts.py`` exactly as
Assignment 2 does — which already merges the executed and submitted notebooks —
and the one item the assignment marks on styling comes back for a person to
confirm.

The two readings are combined in ``grade()`` by taking the better of them: a step
counts as done if either shows the right answer. Neither is reliably better, so
neither is ranked above the other; what differs is the confidence attached, and
whether a TA is told which one carried the item.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from grader import answers as answerlib
from grader import charts as chartlib
from grader.charts import MATPLOTLIB
from grader.models import (
    STATUS_FAIL,
    STATUS_MANUAL_REVIEW,
    STATUS_NOT_FOUND,
    STATUS_PARTIAL,
    STATUS_PASS,
    RubricItemResult,
)
from grader.rubric import RubricItem
from grader.utils import as_float

from .base import AssignmentGrader, GradingContext, register

# holoviews container types that mean "one chart per value of a dimension".
WIDGET_CONTAINERS = ("HoloMap", "GridSpace", "NdLayout")
# The same thing, but never evaluated: hvplot returns this when `dynamic=False`
# is left out, and it holds no frames at all.
LAZY_CONTAINERS = ("DynamicMap",)
LAYOUT_CONTAINERS = ("Layout", "NdLayout")


# ===========================================================================
# The answers the student's own notebook shows
# ===========================================================================
#
# Everything above reads the objects this grading run produced. That is the
# stronger evidence when it exists, and on this assignment it often does not:
# five data files instead of one, read from whatever path each student used, and
# a placement that misses kills the notebook at the first `read_file`. A
# submission that was entirely correct then grades as if nothing happened.
#
# So every item gets a second, independent reading of the notebook the student
# handed in — the numbers their own run printed, the shapes it showed, the repr
# of every chart it drew (see grader/answers.py) — and the two verdicts are
# combined by taking the better of them. A step counts as done if either source
# shows the right answer. Execution stops being load-bearing.
#
# An evaluator returns (ratio, note) — or (None, "") when the saved outputs say
# nothing about this step, which leaves the probe's verdict alone.

class _SavedAnswerChecks:
    """Mixin: one evaluator per rubric item, reading the submitted outputs."""

    # Credit for a step the source plainly performs but whose result the student
    # never displayed. Deliberately not full marks: writing `gpd.sjoin(...)` is
    # not evidence that it returned the right thing, and this assignment has an
    # answer key precisely so that the result can be checked rather than the
    # intention. It goes to a person, like every other deduction.
    SOURCE_ONLY_CREDIT = 0.7

    # -- helpers --------------------------------------------------------
    @staticmethod
    def _polygon_chart(chart: Any, allowed: Iterable[str]) -> bool:
        allowed = {str(a) for a in allowed}
        return bool(set(chart.element_types) & allowed)

    @staticmethod
    def _keys_match(chart: Any, expected: set[str]) -> bool:
        keys = {str(k) for k in chart.frame_keys}
        return bool(expected) and expected <= keys

    def _widget_from_outputs(
        self, answers: Any, item: RubricItem, what: str
    ) -> tuple[float | None, str]:
        """Shared reading for the two "one map per value, with a widget" items."""
        config = item.config
        expected_frames = int(config.get("expected_frames", 0))
        expected_keys = {str(k) for k in config.get("expected_keys", [])}
        hints = [str(h) for h in config.get("key_dimension_hints", [])]
        polygons = config.get("polygon_elements", ["Polygons"])

        charts = answers.charts()
        if not charts:
            return None, ""

        def keyed(chart: Any) -> bool:
            if expected_keys:
                return self._keys_match(chart, expected_keys)
            dimension = " ".join(chart.kdims + [chart.widget_dimension]).lower()
            return any(hint.lower() in dimension for hint in hints)

        widgets = [c for c in charts if c.is_widget]
        good = [
            c for c in widgets
            if keyed(c) and len(c.frame_keys) == expected_frames
            and self._polygon_chart(c, polygons)
        ]
        if good:
            return 1.0, (
                f"{what}: the submitted notebook shows a {good[0].kind} of "
                f"{expected_frames} frames keyed on "
                f"`{', '.join(good[0].kdims) or good[0].widget_dimension}` "
                f"(code cell {good[0].code_cell})."
            )
        lazy = [c for c in charts if c.is_lazy and keyed(c)]
        if lazy:
            return float(config.get("dynamic_map_credit_ratio", 0.6)), (
                f"{what}: the submitted notebook shows a DynamicMap, so "
                "`dynamic=False` was left out — the widget is there but no frame "
                "behind it was ever drawn, so there is nothing to page through."
            )
        if widgets:
            return float(config.get("wrong_dimension_credit_ratio", 0.5)), (
                f"{what}: the submitted notebook shows a {widgets[0].kind} keyed on "
                f"`{', '.join(widgets[0].kdims) or '?'}` with "
                f"{len(widgets[0].frame_keys)} frames, not {expected_frames} on the "
                "dimension the instructions name."
            )
        flat = [c for c in charts if self._polygon_chart(c, polygons) and not c.is_layout]
        if flat:
            return float(config.get("no_widget_credit_ratio", 0.5)), (
                f"{what}: the submitted notebook shows maps, but as single static "
                "charts rather than a series with a widget."
            )
        return None, ""

    # -- execution ------------------------------------------------------
    def _saved_notebook_execution(self, ctx, item, answers):
        """What the submitted file says about the run the student did.

        The grading run's own execution is the better evidence and the base class
        has already used it. This only matters when that execution could not
        happen — no data supplied, or five files the grader could not place — and
        the question becomes the one Assignment 2 asks: does the submitted
        notebook show a complete, clean run?
        """
        config = item.config
        if not answers.cells:
            return None, ""
        total = len(answers.cells)
        answered = answers.cells_with_answers
        errors = answers.error_cells
        # Cells that only ever set a variable produce no output and are not a
        # sign of a partial run, so coverage is measured generously.
        coverage = answered / total if total else 0.0

        if not answered and not errors:
            return 0.0, (
                "The submitted notebook has no saved output at all, so there is no "
                "evidence it was ever run."
            )
        ratio = 1.0
        notes: list[str] = []
        if errors:
            penalty = float(config.get("error_penalty_each", 3)) * len(errors)
            penalty = min(penalty, float(config.get("max_error_penalty", 7)))
            ratio -= penalty / float(item.points)
            notes.append(
                f"{len(errors)} cell(s) errored in the student's own run "
                f"(first: code cell {errors[0].code_cell}, {errors[0].error})"
            )
        if coverage < float(config.get("min_output_coverage", 0.5)):
            ratio -= float(config.get("low_coverage_penalty", 3)) / float(item.points)
            notes.append(
                f"only {answered} of {total} code cells show a result, so the "
                "notebook reads as partly run"
            )
        ratio = max(0.0, min(ratio, 1.0))
        if ratio >= 1.0:
            return 1.0, (
                f"The submitted notebook shows a complete run: {answered} of {total} "
                "code cells carry a result and none of them errored. The grading run "
                "could not reproduce it, which on this assignment usually means the "
                "data did not land where the notebook reads from."
            )
        return ratio, "The student's own saved run: " + "; ".join(notes) + "."

    # -- Part 1.1 -------------------------------------------------------
    def _saved_eviction_data_loading(self, ctx, item, answers):
        expected = int(item.config.get("expected_rows", 3217))
        if answers.shows_rows(expected):
            return 1.0, f"The submitted notebook shows the {expected:,} Pennsylvania tracts."
        # A `head()` shows no row count, but an Eviction Lab frame is unmistakable
        # from its columns, and the geometry column proves geopandas read it.
        frames = answers.frames_with_columns(["GEOID", "geometry"])
        if frames:
            return 1.0, (
                "The submitted notebook shows the tract data loaded with a geometry "
                f"column (code cell {frames[0].code_cell})."
            )
        if answers.frames_with_columns(["GEOID"]):
            return 0.6, (
                "The submitted notebook shows tract data, but no geometry column — "
                "the instructions ask for geopandas."
            )
        return None, ""

    def _saved_philadelphia_tracts(self, ctx, item, answers):
        expected = int(item.config.get("expected_rows", 384))
        cell = answers.shows(expected) or answers.shows_rows(expected)
        if cell:
            return 1.0, (
                f"The submitted notebook shows {expected} Philadelphia tracts "
                f"(code cell {cell.code_cell})."
            )
        return None, ""

    def _saved_tidy_evictions(self, ctx, item, answers):
        config = item.config
        expected_rows = int(config.get("expected_rows", 5376))
        labels = {str(v) for v in config.get("expected_year_labels", [])}
        total = float(config.get("expected_value_sum", 149472))

        cell = answers.shows_rows(expected_rows)
        if cell:
            return 1.0, (
                f"The submitted notebook shows the tidy frame at {expected_rows:,} rows "
                f"(code cell {cell.code_cell})."
            )
        # No row count displayed, but the melt leaves two other marks: a frame
        # carrying GEOID, geometry and a year column, and a chart whose fourteen
        # year labels and eviction total could only come from the right melt.
        frames = answers.frames_with_columns(["GEOID", "geometry"])
        melted = [f for f in frames if len(f.columns) <= 8]
        charted = any(
            labels <= {str(k) for k in chart.frame_keys}
            or abs(float(chart.values.get("sum", 0)) - total) <= total * 0.001
            for chart in answers.charts()
        )
        if melted and charted:
            return 1.0, (
                "The submitted notebook shows a tidy frame of GEOID, geometry, year "
                f"and evictions (code cell {melted[0].code_cell}), and a chart over "
                "the fourteen years it holds."
            )
        if melted:
            return 0.7, (
                "The submitted notebook shows a tidy frame, but neither its row count "
                f"nor the {expected_rows:,} rows the melt should give."
            )
        return None, ""

    def _saved_evictions_by_year_plot(self, ctx, item, answers):
        config = item.config
        points = int(config.get("expected_points", 14))
        total = float(config.get("expected_total", 149472))
        rel_tol = float(config.get("total_rel_tol", 0.001))
        accepted = {str(e) for e in config.get("accepted_elements", [])}

        charts = [c for c in answers.charts() if c.kind in accepted and c.values]
        exact = [
            c for c in charts
            if abs(c.values.get("sum", 0) - total) <= total * rel_tol
            and int(c.values.get("count", 0)) == points
        ]
        if exact:
            return 1.0, (
                f"The submitted notebook plots the yearly totals ({exact[0].kind}, "
                f"{points} points summing to {total:,.0f}, code cell "
                f"{exact[0].code_cell})."
            )
        if charts:
            return float(config.get("wrong_values_credit_ratio", 0.5)), (
                f"The submitted notebook shows an hvplot {charts[0].kind} of "
                f"{int(charts[0].values.get('count', 0))} points summing to "
                f"{charts[0].values.get('sum', 0):,.0f}, not the {total:,.0f} "
                "evictions of 2003-2016."
            )
        bare = [c for c in answers.charts() if c.kind in accepted]
        if bare:
            return 0.8, (
                f"The submitted notebook shows an hvplot {bare[0].kind}, but its saved "
                "output does not carry the values it drew."
            )
        return None, ""

    def _saved_evictions_choropleth(self, ctx, item, answers):
        return self._widget_from_outputs(answers, item, "Evictions by year")

    # -- Part 1.2 -------------------------------------------------------
    def _saved_violations_loading(self, ctx, item, answers):
        expected = int(item.config.get("expected_rows", 434052))
        shown = answers.shows(expected) or answers.shows_rows(expected)
        points = answers.frames_with_columns(["lng", "lat", "geometry"])
        built = self._matches_any(ctx, [r"points_from_xy", r"GeoDataFrame\s*\("])
        if points:
            return 1.0, (
                "The submitted notebook shows the violations as a GeoDataFrame of "
                f"points (code cell {points[0].code_cell})."
            )
        if shown and built:
            return 1.0, (
                f"The submitted notebook shows all {expected:,} violations, and the "
                "source builds point geometries from the lng/lat columns."
            )
        if shown and answers.frames_with_columns(["lng", "lat"]):
            return float(item.config.get("not_geodataframe_credit_ratio", 0.4)), (
                f"The submitted notebook shows the {expected:,} violations, but no "
                "geometry column — they were never converted to a GeoDataFrame."
            )
        if built:
            return self.SOURCE_ONLY_CREDIT, (
                "The source reads the violations and builds point geometries, but the "
                "notebook shows no result from that cell, so the row count could not "
                "be checked."
            )
        return None, ""

    def _saved_violations_subset(self, ctx, item, answers):
        expected = int(item.config.get("expected_rows", 34108))
        cell = answers.shows(expected) or answers.shows_rows(expected)
        if cell:
            return 1.0, (
                f"The submitted notebook shows {expected:,} rows after trimming to the "
                f"fifteen violation types (code cell {cell.code_cell})."
            )
        return None, ""

    def _saved_spatial_join(self, ctx, item, answers):
        expected = int(item.config.get("expected_rows", 34108))
        joined = answers.frames_with_columns(["GEOID", "violationdescription", "geometry"])
        kept = answers.shows_rows(expected) or answers.shows(expected)
        called = self._matches_any(ctx, [r"sjoin\s*\("])
        if joined:
            note = (
                "The submitted notebook shows each violation carrying the GEOID of its "
                f"tract (code cell {joined[0].code_cell})"
            )
            return 1.0, note + (f", with all {expected:,} rows kept." if kept else ".")
        if called and kept:
            return 1.0, (
                f"The source joins the violations to the tracts, and the submitted "
                f"notebook shows all {expected:,} of them surviving it."
            )
        if called:
            return self.SOURCE_ONLY_CREDIT, (
                "The source calls sjoin(), but the notebook shows no result from it, "
                "so whether the join kept all 34,108 violations could not be checked."
            )
        return None, ""

    def _saved_violations_by_tract(self, ctx, item, answers):
        allowed = [int(v) for v in item.config.get("allowed_row_counts", [4000, 5535])]
        hints = [str(h).lower() for h in item.config.get("count_column_hints", ["n"])]
        for cell in answers.cells:
            lowered = [c.lower() for c in cell.columns]
            if "geoid" not in lowered or "violationdescription" not in lowered:
                continue
            if "geometry" in lowered:
                continue  # that is the merge in 1.2.6, not the group-by
            if not any(any(h == c or h in c for h in hints) for c in lowered):
                continue
            counted = any(answers.shows_rows(rows) for rows in allowed)
            return 1.0, (
                "The submitted notebook shows a count per violation type and tract "
                f"(code cell {cell.code_cell})"
                + (", at one of the two row counts the instructions allow." if counted else ".")
            )
        # No frame displayed, but a row count that only this group-by produces.
        if any(answers.shows(rows) or answers.shows_rows(rows) for rows in allowed):
            return 1.0, (
                "The submitted notebook shows the group-by at "
                f"{' or '.join(str(r) for r in allowed)} rows, which is the count per "
                "violation type and tract."
            )
        if self._matches_any(ctx, [r"groupby\s*\(\s*\[", r"value_counts"]):
            return self.SOURCE_ONLY_CREDIT, (
                "The source groups the violations, but the notebook shows no result "
                "from it, so the counts could not be checked."
            )
        return None, ""

    def _saved_merge_geometries(self, ctx, item, answers):
        merged = answers.frames_with_columns(
            ["GEOID", "geometry", "violationdescription"]
        )
        for cell in merged:
            if any(c.lower() in ("n", "count", "size") for c in cell.columns):
                return 1.0, (
                    "The submitted notebook shows the counts merged onto the tract "
                    f"geometries (code cell {cell.code_cell})."
                )
        if self._matches_any(ctx, [r"merge\s*\("]):
            return self.SOURCE_ONLY_CREDIT, (
                "The source merges the counts onto the geometries, but the notebook "
                "shows no result from it, so whether the result is still a "
                "GeoDataFrame could not be checked."
            )
        return None, ""

    def _saved_violations_choropleth(self, ctx, item, answers):
        return self._widget_from_outputs(answers, item, "Violations by type")

    def _saved_side_by_side(self, ctx, item, answers):
        config = item.config
        polygons = config.get("polygon_elements", ["Polygons"])
        layouts = [
            c for c in answers.charts()
            if c.is_layout and len(c.children) >= 2
            and self._polygon_chart(c, polygons)
        ]
        if layouts:
            # The saved repr names the panels but not the grid, so the row/column
            # deduction is left to the executed run rather than guessed at here.
            return 1.0, (
                f"The submitted notebook shows a Layout of {len(layouts[0].children)} "
                f"choropleths (code cell {layouts[0].code_cell})."
            )
        maps = [c for c in answers.charts() if self._polygon_chart(c, polygons)
                and not c.is_layout and not c.is_widget]
        if len(maps) >= 2:
            return float(config.get("not_composed_credit_ratio", 0.5)), (
                "The submitted notebook shows two maps but never composes them into "
                "one layout — `left + right` puts them side by side."
            )
        return None, ""

    # -- Part 2 ---------------------------------------------------------
    def _saved_landsat_loading(self, ctx, item, answers):
        bands = int(item.config.get("expected_band_count", 10))
        epsg = item.config.get("expected_crs_epsg")
        wanted = [bands] + ([float(epsg)] if epsg is not None else [])
        cell = answers.shows_together(wanted)
        if cell:
            return 1.0, (
                f"The submitted notebook shows the scene as {bands} bands in "
                f"EPSG:{epsg} (code cell {cell.code_cell})."
            )
        if self._matches_any(ctx, [r"rasterio\.open", r"rasterio\s*\.\s*open"]):
            return self.SOURCE_ONLY_CREDIT, (
                "The source opens the scene with rasterio, but the notebook shows "
                "nothing about it, so the band count and CRS could not be checked."
            )
        return None, ""

    def _saved_city_suburb_polygons(self, ctx, item, answers):
        config = item.config
        city = float(config.get("expected_city_area", 0))
        suburbs = float(config.get("expected_suburb_area", 0))
        rel_tol = float(config.get("area_rel_tol", 0.02))
        if answers.shows(city, rel_tol) and answers.shows(suburbs, rel_tol):
            return 1.0, (
                f"The submitted notebook shows both areas: {city / 1e6:,.0f} km2 inside "
                f"the city limits and {suburbs / 1e6:,.0f} km2 around it."
            )
        if answers.shows(city, rel_tol) and answers.shows(city + suburbs, rel_tol):
            return float(config.get("envelope_not_differenced_credit_ratio", 0.5)), (
                "The submitted notebook shows the suburbs polygon as the whole "
                "envelope rather than the envelope with the city cut out of it."
            )
        if answers.shows(city, rel_tol):
            return float(config.get("missing_suburbs_credit_ratio", 0.5)), (
                "The submitted notebook shows the city limits polygon, but not a "
                "suburbs polygon built from its envelope."
            )
        return None, ""

    def _saved_ndvi_masking(self, ctx, item, answers):
        config = item.config
        city = float(config.get("expected_city_median", 0))
        suburbs = float(config.get("expected_suburb_median", 0))
        tolerance = float(config.get("median_abs_tol", 0.02))
        # The masked arrays themselves are never displayed, but the medians of
        # both of them are printed in 2.1.4 — and those two numbers cannot exist
        # unless the raster was masked twice and turned into an NDVI.
        if answers.shows(city, abs_tol=tolerance) and answers.shows(suburbs, abs_tol=tolerance):
            return 1.0, (
                "The submitted notebook reports both NDVI medians, which the raster "
                "could not produce unless it was masked to each area first."
            )
        if answers.shows(city, abs_tol=tolerance) or answers.shows(suburbs, abs_tol=tolerance):
            return float(config.get("one_area_credit_ratio", 0.5)), (
                "The submitted notebook reports an NDVI for one of the two areas only."
            )
        if self._ndvi_pair(answers) and self._matches_any(ctx, config.get("mask_patterns", [])):
            return float(config.get("wrong_bands_credit_ratio", 0.5)), (
                "The submitted notebook reports two NDVI-range values from a masked "
                f"raster, but not the {city:.3f} and {suburbs:.3f} this scene gives. "
                "Landsat 8 band 4 is red and band 5 is near-infrared, which are "
                "index 3 and index 4 of the array the mask returns."
            )
        return None, ""

    @staticmethod
    def _ndvi_pair(answers: Any) -> list[float]:
        """Two numbers printed together that could be NDVI medians.

        Bounded by definition, and not the round numbers a shape or a count
        produces — enough to tell "computed something and got it wrong" apart
        from "never computed it".
        """
        for cell in answers.cells:
            values = [
                value for value in cell.shown
                if -1.0 <= value <= 1.0 and value != int(value)
            ]
            if len(values) >= 2:
                return values[:2]
        return []

    def _saved_ndvi_medians(self, ctx, item, answers):
        config = item.config
        city = float(config.get("expected_city_median", 0))
        suburbs = float(config.get("expected_suburb_median", 0))
        tolerance = float(config.get("median_abs_tol", 0.02))
        city_cell = answers.shows(city, abs_tol=tolerance)
        suburb_cell = answers.shows(suburbs, abs_tol=tolerance)
        if city_cell and suburb_cell:
            return 1.0, (
                f"The submitted notebook prints both medians — {city:.4f} in the city "
                f"against {suburbs:.4f} in the suburbs (code cell {city_cell.code_cell})."
            )
        pair = self._ndvi_pair(answers)
        if pair and self._matches_any(ctx, [r"nanmedian", r"median"]):
            if bool(config.get("expect_suburbs_greater", True)) and pair[1] > pair[0]:
                return float(config.get("right_direction_credit_ratio", 0.5)), (
                    f"The submitted notebook prints two medians ({pair[0]:.4f} and "
                    f"{pair[1]:.4f}) and the suburbs come out greener than the city, "
                    f"but the values are not the {city:.4f} and {suburbs:.4f} this "
                    "scene gives."
                )
            return float(config.get("right_direction_credit_ratio", 0.5)) * 0.6, (
                f"The submitted notebook prints two medians ({pair[0]:.4f} and "
                f"{pair[1]:.4f}), but neither matches this scene and the suburbs do "
                "not come out greener than the city."
            )
        return None, ""

    def _saved_tree_data_loading(self, ctx, item, answers):
        expected = int(item.config.get("expected_rows", 2480))
        cell = answers.shows(expected) or answers.shows_rows(expected)
        if cell:
            return 1.0, (
                f"The submitted notebook shows the {expected:,} street tree points "
                f"(code cell {cell.code_cell})."
            )
        if self._matches_any(ctx, [r"tree_canopy", r"ppr_tree"]):
            return self.SOURCE_ONLY_CREDIT, (
                "The source reads the street tree file, but the notebook shows no "
                "result from it, so the 2,480 points could not be confirmed."
            )
        return None, ""

    def _saved_tree_ndvi(self, ctx, item, answers):
        config = item.config
        expected = int(config.get("expected_count", 2480))
        tolerance = int(config.get("count_tolerance", 5))
        median = float(config.get("expected_median", 0))
        median_tol = float(config.get("median_abs_tol", 0.03))
        # `describe()` is the ordinary way students look at these values, and it
        # carries the count and the median in one table.
        cell = answers.describes("50%", median, median_tol)
        if cell:
            count = cell.describe.get("count")
            if count is None or abs(count - expected) <= max(tolerance, expected * 0.02):
                return 1.0, (
                    f"The submitted notebook shows the sampled NDVI with a median of "
                    f"{cell.describe['50%']:.3f} over {int(count or expected):,} trees "
                    f"(code cell {cell.code_cell})."
                )
        if answers.shows(median, abs_tol=median_tol):
            return 1.0, (
                f"The submitted notebook reports a median tree NDVI of {median:.3f}."
            )
        if answers.describes("count", expected, max(tolerance, 50)):
            return float(config.get("wrong_values_credit_ratio", 0.4)), (
                "The submitted notebook shows one value per tree, but not the NDVI at "
                f"those points — the median is not {median:.3f}."
            )
        return None, ""

    def _saved_common_violations_extra_credit(self, ctx, item, answers):
        expected = int(item.config.get("expected_frames", 20))
        wide = [c for c in answers.charts() if len(c.frame_keys) >= expected]
        if wide:
            return 1.0, (
                f"The submitted notebook shows a widget over {len(wide[0].frame_keys)} "
                f"violation types (code cell {wide[0].code_cell})."
            )
        return None, ""


@register
class HW3Grader(_SavedAnswerChecks, AssignmentGrader):
    assignment_id = "hw3"

    # Confidence for a step seen only in the student's own saved output: above
    # the review threshold, so it does not flag a correct submission on its own,
    # but below the 1.0 of a result this grading run produced itself. A saved
    # output is the student's claim about their run — it can be stale, and it can
    # be edited by hand.
    SUBMITTED_CONFIDENCE = 0.9

    # ------------------------------------------------------------------
    # Probe accessors
    # ------------------------------------------------------------------
    @staticmethod
    def _frames(ctx: GradingContext) -> list[dict[str, Any]]:
        return list((ctx.probe or {}).get("dataframes", []) or [])

    @staticmethod
    def _plots(ctx: GradingContext) -> list[dict[str, Any]]:
        return list((ctx.probe or {}).get("plots", []) or [])

    @staticmethod
    def _arrays(ctx: GradingContext) -> list[dict[str, Any]]:
        return list((ctx.probe or {}).get("arrays", []) or [])

    @staticmethod
    def _geometries(ctx: GradingContext) -> list[dict[str, Any]]:
        return list((ctx.probe or {}).get("geometries", []) or [])

    @staticmethod
    def _rasters(ctx: GradingContext) -> list[dict[str, Any]]:
        return list((ctx.probe or {}).get("rasters", []) or [])

    @staticmethod
    def _collections(ctx: GradingContext) -> list[dict[str, Any]]:
        return list((ctx.probe or {}).get("collections", []) or [])

    @staticmethod
    def _series(ctx: GradingContext) -> list[dict[str, Any]]:
        return list((ctx.probe or {}).get("series", []) or [])

    def answers(self, ctx: GradingContext) -> answerlib.NotebookAnswers:
        """What the notebooks show, read once per submission and reused."""
        cached = ctx.cache.get("saved_answers")
        if cached is None:
            cached = answerlib.collect_answers(
                ctx.execution.executed_notebook_path, ctx.analysis.path
            )
            ctx.cache["saved_answers"] = cached
        return cached

    # -- combining the two readings -------------------------------------
    def grade(self, ctx: GradingContext) -> list[RubricItemResult]:
        """Grade on the objects this run produced *and* on what the file shows.

        The two readings are independent and neither is reliably better, so they
        are combined by taking the better of them rather than by ranking them: a
        step counts as done if the executed run shows the right answer or the
        submitted notebook does. That is what stops a data path the grader could
        not resolve from turning a correct submission into a column of zeros.
        """
        results = super().grade(ctx)
        try:
            answers = self.answers(ctx)
        except Exception:  # a bad notebook must not lose the probe's verdict
            return results
        return [self._combine(ctx, result, answers) for result in results]

    def _combine(
        self,
        ctx: GradingContext,
        result: RubricItemResult,
        answers: answerlib.NotebookAnswers,
    ) -> RubricItemResult:
        item = self.rubric.item(result.rubric_id)
        evaluator = getattr(self, f"_saved_{result.rubric_id}", None)
        if item is None or evaluator is None or item.points <= 0:
            return result
        try:
            ratio, note = evaluator(ctx, item, answers)
        except Exception as exc:
            result.evidence["saved_output_error"] = f"{type(exc).__name__}: {exc}"
            return result
        if ratio is None:
            result.evidence.setdefault("saved_output", "says nothing about this step")
            return result

        score = float(item.points) * max(0.0, min(float(ratio), 1.0))
        result.evidence["saved_output"] = {
            "credit": round(ratio, 3),
            "note": note,
            "source": answers.source,
        }
        if score <= result.automatic_score:
            # The executed run already saw at least this much; keep its verdict
            # and leave the corroboration in the evidence.
            if result.status == STATUS_PASS:
                result.evidence["agreement"] = (
                    "confirmed by the submitted notebook"
                    if ratio >= 1.0 else "the submitted notebook shows less"
                )
            return result

        status = STATUS_PASS if ratio >= 1.0 else STATUS_PARTIAL
        confidence = self.SUBMITTED_CONFIDENCE if ratio >= 1.0 else 0.7
        evidence = dict(result.evidence)
        evidence["graded_from"] = "the notebook's own saved output"
        evidence["executed_run_said"] = {
            "score": result.automatic_score,
            "status": result.status,
            "feedback": result.feedback[:300],
        }
        return self.result(item, score, status, confidence, note, evidence)

    def charts(self, ctx: GradingContext) -> chartlib.ChartEvidence:
        """matplotlib figures, read once per submission and reused."""
        cached = ctx.cache.get("chart_evidence")
        if cached is None:
            cached = chartlib.collect_charts(
                ctx.execution.executed_notebook_path, ctx.analysis.path
            )
            ctx.cache["chart_evidence"] = cached
        return cached

    # ------------------------------------------------------------------
    # Small matchers
    # ------------------------------------------------------------------
    @staticmethod
    def _rows(profile: dict[str, Any]) -> int:
        return int(profile.get("rows") or 0)

    @classmethod
    def _rows_match(cls, profile: dict[str, Any], expected: int, tolerance: int = 0) -> bool:
        return abs(cls._rows(profile) - int(expected)) <= int(tolerance)

    @staticmethod
    def _columns(profile: dict[str, Any]) -> list[str]:
        return [str(c) for c in (profile.get("columns") or [])]

    @classmethod
    def _has_columns(cls, profile: dict[str, Any], names: Iterable[str]) -> bool:
        lowered = {c.lower() for c in cls._columns(profile)}
        return all(str(n).lower() in lowered for n in names)

    @staticmethod
    def _samples(profile: dict[str, Any], column: str) -> set[str]:
        values = (profile.get("value_samples") or {}).get(column) or []
        return {str(v) for v in values}

    @classmethod
    def _column_holding(
        cls, profile: dict[str, Any], expected: set[str], exact: bool = True
    ) -> str | None:
        """The column whose distinct values are the expected label set."""
        for column in (profile.get("value_samples") or {}):
            values = cls._samples(profile, column)
            if not values:
                continue
            if values == expected or (not exact and values and values <= expected):
                return str(column)
        return None

    @staticmethod
    def _numeric(profile: dict[str, Any], column: str) -> dict[str, Any]:
        return (profile.get("numeric_summary") or {}).get(column) or {}

    # An Eviction Lab frame carries 399 numeric columns, and across 3,217 tracts
    # one of them will sum to almost any total by coincidence. A result of a
    # group-by or a merge is narrow, so width is the guard: it keeps the raw file
    # out of searches that look for a frame by what its numbers add up to.
    NARROW_FRAME_COLUMNS = 12

    @classmethod
    def _is_narrow(cls, profile: dict[str, Any], limit: int | None = None) -> bool:
        return int(profile.get("n_columns") or 0) <= int(limit or cls.NARROW_FRAME_COLUMNS)

    @classmethod
    def _numeric_columns_matching(
        cls, profile: dict[str, Any], key: str, expected: float, rel_tol: float
    ) -> list[str]:
        found = []
        for column, summary in (profile.get("numeric_summary") or {}).items():
            value = as_float(summary.get(key))
            if value is None:
                continue
            if abs(value - expected) <= abs(expected) * rel_tol + 1e-9:
                found.append(str(column))
        return found

    @staticmethod
    def _geoid(profile: dict[str, Any], prefix: str) -> dict[str, Any] | None:
        """How much of this frame sits in one county, from the prefix histogram.

        ``prefix_counts`` is the probe's compact answer to "is every row in
        Philadelphia?" — a five-row head cannot tell, and 384 GEOIDs are past the
        value-sample cap.
        """
        for column, entry in (profile.get("prefix_counts") or {}).items():
            counts = entry.get("counts") or {}
            total = sum(int(v) for v in counts.values())
            if not total:
                continue
            matching = int(counts.get(str(prefix), 0))
            return {
                "column": str(column),
                "total": total,
                "matching": matching,
                "purity": matching / total,
                "distinct": int((profile.get("nunique") or {}).get(str(column)) or 0),
                "counts": dict(list(counts.items())[:6]),
            }
        return None

    @staticmethod
    def _source(ctx: GradingContext) -> str:
        return ctx.analysis.code_source or ""

    @classmethod
    def _matches_any(cls, ctx: GradingContext, patterns: Iterable[str]) -> str | None:
        source = cls._source(ctx)
        for pattern in patterns or ():
            try:
                if re.search(str(pattern), source):
                    return str(pattern)
            except re.error:
                if str(pattern) in source:
                    return str(pattern)
        return None

    # -- plot matchers --------------------------------------------------
    @staticmethod
    def _is_widget(plot: dict[str, Any]) -> bool:
        return str(plot.get("type")) in WIDGET_CONTAINERS

    @staticmethod
    def _is_lazy(plot: dict[str, Any]) -> bool:
        return str(plot.get("type")) in LAZY_CONTAINERS

    @staticmethod
    def _draws_polygons(plot: dict[str, Any], allowed: Iterable[str]) -> bool:
        allowed = {str(a) for a in allowed}
        return bool(set(plot.get("element_types") or []) & allowed)

    @staticmethod
    def _dimension_matches(plot: dict[str, Any], hints: Iterable[str]) -> bool:
        hints = [str(h).lower() for h in hints]
        for dimension in plot.get("kdims") or []:
            lowered = str(dimension).lower()
            if any(hint == lowered or hint in lowered for hint in hints):
                return True
        return False

    # ------------------------------------------------------------------
    # Result shortcuts
    # ------------------------------------------------------------------
    def _found(
        self, item: RubricItem, feedback: str, evidence: dict[str, Any]
    ) -> RubricItemResult:
        """Full marks for a matched expected value: a fact, so confidence 1.0."""
        return self.result(item, item.points, STATUS_PASS, 1.0, feedback, evidence)

    def _partial(
        self,
        item: RubricItem,
        ratio: float,
        feedback: str,
        evidence: dict[str, Any],
        confidence: float = 0.75,
    ) -> RubricItemResult:
        return self.result(
            item, item.points * max(0.0, min(float(ratio), 1.0)),
            STATUS_PARTIAL, confidence, feedback, evidence,
        )

    def _missing(
        self, ctx: GradingContext, item: RubricItem, what: str,
        evidence: dict[str, Any] | None = None,
    ) -> RubricItemResult:
        """Nothing in the kernel answers this step.

        A notebook that failed earlier explains the absence, so that case is
        reported as an execution error rather than as a wrong answer — and either
        way it reaches a person, because it is not full marks.
        """
        evidence = dict(evidence or {})
        if not ctx.probe_ok:
            return self.no_probe_result(item, ctx)
        evidence.setdefault("execution_success", ctx.execution.success)
        suffix = (
            " The notebook stopped at code cell "
            f"{ctx.execution.error_cell} ({ctx.execution.error_message}), which "
            "may be why."
            if not ctx.execution.success else ""
        )
        return self.result(
            item, 0.0, STATUS_NOT_FOUND, 0.6,
            f"{what}{suffix}", evidence,
        )

    # =================================================================
    # 1.1.1 — load the eviction data
    # =================================================================
    def check_eviction_data_loading(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        config = item.config
        analysis = ctx.analysis
        deductions: list[tuple[float, str]] = []

        missing = [
            library for library in config.get("required_imports", ["geopandas"])
            if library not in analysis.imports
        ]
        if missing:
            deductions.append((1.0, f"missing import: {', '.join(missing)}"))
        if not analysis.read_calls:
            deductions.append(
                (float(config.get("missing_read_penalty", 2)),
                 "no read_file / read_* call was found in the notebook")
            )
        if analysis.absolute_paths:
            deductions.append(
                (float(config.get("absolute_path_penalty", 2)),
                 "the data is read from an absolute path "
                 f"({analysis.absolute_paths[0]}), which only works on one machine")
            )

        expected = int(config.get("expected_rows", 3217))
        tolerance = int(config.get("row_tolerance", 0))
        loaded = [
            profile for profile in self._frames(ctx)
            if self._rows_match(profile, expected, tolerance)
        ]
        geo = [profile for profile in loaded if profile.get("is_geodataframe")]

        if not loaded:
            deductions.append(
                (float(config.get("wrong_size_penalty", 1)),
                 f"no frame in memory holds the {expected:,} Pennsylvania tracts")
            )
        elif not geo:
            deductions.append(
                (float(config.get("not_geodataframe_penalty", 2)),
                 "the tracts were read into a plain DataFrame — the instructions "
                 "ask for geopandas, and the geometry column is needed later")
            )

        evidence = {
            "imports": sorted(analysis.imports & {"geopandas", "pandas", "rasterio",
                                                  "rasterstats", "hvplot", "holoviews",
                                                  "matplotlib", "numpy"}),
            "read_calls": analysis.read_calls[:6],
            "absolute_paths": analysis.absolute_paths[:3],
            "expected_rows": expected,
            "frames_with_expected_rows": [p.get("name") for p in loaded][:4],
            "geodataframe": bool(geo),
            "crs": (geo[0].get("crs_epsg") if geo else None),
        }
        penalty = sum(points for points, _ in deductions)
        score = max(0.0, float(item.points) - penalty)
        if not deductions:
            return self._found(
                item,
                f"PA-tracts.geojson loaded with geopandas: {expected:,} tracts, "
                f"EPSG:{evidence['crs']}.",
                evidence,
            )
        evidence["deductions"] = [{"points": p, "reason": r} for p, r in deductions]
        return self.result(
            item, score, STATUS_PARTIAL if score > 0 else STATUS_FAIL, 0.9,
            "Data loading: " + "; ".join(reason for _, reason in deductions) + ".",
            evidence,
        )

    # =================================================================
    # 1.1.2 — trim to Philadelphia
    # =================================================================
    def check_philadelphia_tracts(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        config = item.config
        expected = int(config.get("expected_rows", 384))
        prefix = str(config.get("geoid_prefix", "42101"))
        min_purity = float(config.get("min_purity", 0.95))

        # Anything descended from the subset counts: a student who melts in one
        # chain never keeps the intermediate frame, but their tidy frame still
        # holds exactly the 384 Philadelphia tracts, which is the same evidence.
        best: dict[str, Any] | None = None
        for profile in self._frames(ctx):
            summary = self._geoid(profile, prefix)
            if not summary or summary["total"] <= 0:
                continue
            # The unfiltered Pennsylvania file is not a candidate subset.
            if summary["purity"] < 0.5:
                continue
            candidate = {"frame": profile.get("name"), "rows": self._rows(profile), **summary}
            key = (candidate["purity"] >= min_purity, candidate["distinct"] == expected,
                   candidate["distinct"])
            if best is None or key > (best["purity"] >= min_purity,
                                      best["distinct"] == expected, best["distinct"]):
                best = candidate

        if best is None:
            return self._missing(
                ctx, item,
                "No frame in memory holds a Philadelphia-only subset of the tracts "
                f"(GEOIDs beginning {prefix}).",
                {"expected_rows": expected, "geoid_prefix": prefix},
            )

        evidence = {
            "expected_tracts": expected,
            "geoid_prefix": prefix,
            "frame": best["frame"],
            "rows": best["rows"],
            "distinct_tracts": best["distinct"],
            "share_in_philadelphia": round(best["purity"], 4),
            "county_prefixes": best["counts"],
        }

        if best["purity"] >= min_purity and best["distinct"] == expected:
            return self._found(
                item,
                f"Trimmed to Philadelphia County: {expected} distinct tracts, every "
                f"GEOID beginning {prefix}.",
                evidence,
            )
        if best["purity"] < min_purity:
            return self._partial(
                item, float(config.get("impure_credit_ratio", 0.4)),
                f"The subset still contains tracts outside Philadelphia County — "
                f"{round(best['purity'] * 100)}% of rows begin {prefix} "
                f"(other counties seen: "
                f"{', '.join(k for k in best['counts'] if k != prefix) or 'none'}). "
                "Philadelphia is a county as well as a city, so `pl` is the column "
                "that separates it.",
                evidence, confidence=0.9,
            )
        return self._partial(
            item, float(config.get("incomplete_credit_ratio", 0.7)),
            f"The subset is Philadelphia-only but holds {best['distinct']} tracts "
            f"rather than {expected}.",
            evidence, confidence=0.9,
        )

    # =================================================================
    # 1.1.3 — melt to tidy
    # =================================================================
    def check_tidy_evictions(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        config = item.config
        expected_rows = int(config.get("expected_rows", 5376))
        labels = {str(v) for v in config.get("expected_year_labels", [])}
        expected_sum = float(config.get("expected_value_sum", 149472))
        rel_tol = float(config.get("value_sum_rel_tol", 0.001))
        id_columns = [str(c) for c in config.get("required_id_columns", ["GEOID"])]

        best: dict[str, Any] | None = None
        for profile in self._frames(ctx):
            year_column = self._column_holding(profile, labels)
            subset_column = None
            if year_column is None:
                # A different year span is still a melt; find the column that
                # looks like the variable column of one.
                for column in (profile.get("value_samples") or {}):
                    values = self._samples(profile, column)
                    if len(values) >= 5 and all(re.fullmatch(r"e[-_]?\d{2}", v) for v in values):
                        subset_column = str(column)
                        break
            column = year_column or subset_column
            if column is None:
                continue
            value_columns = self._numeric_columns_matching(
                profile, "sum", expected_sum, rel_tol
            )
            candidate = {
                "frame": profile.get("name"),
                "rows": self._rows(profile),
                "year_column": column,
                "year_labels": sorted(self._samples(profile, column))[:20],
                "exact_span": year_column is not None,
                "value_columns": value_columns,
                "has_geometry": bool(profile.get("is_geodataframe"))
                or "geometry" in {c.lower() for c in self._columns(profile)},
                "has_ids": self._has_columns(profile, [c for c in id_columns if c != "geometry"]),
            }
            key = (candidate["exact_span"], bool(value_columns),
                   candidate["has_geometry"], candidate["has_ids"],
                   self._rows_match(profile, expected_rows))
            if best is None or key > (
                best["exact_span"], bool(best["value_columns"]),
                best["has_geometry"], best["has_ids"],
                best["rows"] == expected_rows,
            ):
                best = candidate

        if best is None:
            return self._missing(
                ctx, item,
                "No tidy frame was found: nothing in memory has one row per tract "
                "per year with the eviction counts in a single column.",
                {"expected_rows": expected_rows, "expected_year_labels": sorted(labels)},
            )

        evidence = {
            "expected_rows": expected_rows,
            "expected_value_sum": expected_sum,
            **best,
        }
        ratio = 1.0
        notes: list[str] = []
        if not best["exact_span"] or not best["value_columns"]:
            ratio *= float(config.get("wrong_year_span_credit_ratio", 0.6))
            notes.append(
                "the melted columns are not exactly e-03 to e-16 "
                f"(found {len(best['year_labels'])} labels, and no column sums to "
                f"the {expected_sum:,.0f} evictions those years hold)"
            )
        if not best["has_geometry"]:
            ratio *= float(config.get("missing_geometry_credit_ratio", 0.7))
            notes.append(
                "the geometry column was not kept as an id_var, so the tidy frame "
                "cannot be mapped in 1.1.5"
            )
        if best["rows"] != expected_rows and best["exact_span"]:
            ratio *= 0.8
            notes.append(f"{best['rows']:,} rows rather than {expected_rows:,}")

        if ratio >= 1.0:
            return self._found(
                item,
                f"Melted to tidy format: {best['rows']:,} rows "
                f"(384 tracts x 14 years), evictions in "
                f"`{best['value_columns'][0]}`, years in `{best['year_column']}`.",
                evidence,
            )
        return self._partial(
            item, ratio, "Tidy transformation: " + "; ".join(notes) + ".", evidence
        )

    # =================================================================
    # 1.1.4 — yearly trend
    # =================================================================
    def check_evictions_by_year_plot(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        config = item.config
        expected_points = int(config.get("expected_points", 14))
        expected_total = float(config.get("expected_total", 149472))
        rel_tol = float(config.get("total_rel_tol", 0.001))
        accepted = {str(e) for e in config.get("accepted_elements", [])}

        charts: list[dict[str, Any]] = []
        for plot in self._plots(ctx):
            if plot.get("is_container") or str(plot.get("type")) not in accepted:
                continue
            values = plot.get("values") or {}
            total = as_float(values.get("sum"))
            count = int(values.get("count") or 0)
            charts.append(
                {
                    "plot": plot.get("name"),
                    "element": plot.get("type"),
                    "points": count,
                    "plotted_total": total,
                    "matches": total is not None
                    and abs(total - expected_total) <= expected_total * rel_tol,
                    "right_length": count == expected_points,
                }
            )

        evidence = {
            "expected_points": expected_points,
            "expected_total": expected_total,
            "hvplot_charts": charts[:6],
        }

        exact = [c for c in charts if c["matches"] and c["right_length"]]
        if exact:
            return self._found(
                item,
                f"Yearly eviction totals plotted with hvplot ({exact[0]['element']}, "
                f"{expected_points} points summing to {expected_total:,.0f}).",
                evidence,
            )
        if charts:
            best = max(charts, key=lambda c: (c["right_length"], c["matches"]))
            return self._partial(
                item, float(config.get("wrong_values_credit_ratio", 0.5)),
                f"An hvplot chart is there ({best['element']}, {best['points']} points) "
                f"but the values plotted sum to {best['plotted_total']:,.0f} rather "
                f"than the {expected_total:,.0f} evictions of 2003-2016 — check that "
                "the group by sums the eviction column across tracts.",
                evidence,
            )

        # No hvplot chart at all: did they draw the same thing with matplotlib?
        drawn = [
            record for record in self.charts(ctx).by_library(MATPLOTLIB)
            if re.search(r"group\s*by|groupby", record.source, re.I)
        ]
        if drawn:
            evidence["matplotlib_cell"] = drawn[0].code_cell
            evidence["rendered"] = drawn[0].ok
            return self._partial(
                item, float(config.get("wrong_library_credit_ratio", 0.5)),
                f"The yearly trend is drawn in code cell {drawn[0].code_cell}, but "
                "with matplotlib rather than the hvplot the instructions ask for.",
                evidence,
            )
        return self._missing(
            ctx, item, "No chart of the yearly eviction totals was found.", evidence
        )

    # =================================================================
    # 1.1.5 / 1.2.7 — widget-driven choropleths
    # =================================================================
    def _widget_choropleth(
        self, ctx: GradingContext, item: RubricItem, what: str
    ) -> RubricItemResult:
        """Shared check for the two "one map per value, with a widget" items."""
        config = item.config
        expected_frames = int(config.get("expected_frames", 0))
        hints = [str(h) for h in config.get("key_dimension_hints", [])]
        expected_keys = {str(k) for k in config.get("expected_keys", [])}
        polygons = config.get("polygon_elements", ["Polygons"])

        widgets: list[dict[str, Any]] = []
        lazy: list[dict[str, Any]] = []
        flat: list[dict[str, Any]] = []
        for plot in self._plots(ctx):
            record = {
                "plot": plot.get("name"),
                "type": plot.get("type"),
                "key_dimensions": plot.get("kdims"),
                "frames": plot.get("n_frames"),
                "elements": plot.get("element_types"),
                "keys": (plot.get("keys") or [])[:6],
            }
            if self._is_widget(plot):
                record["right_dimension"] = self._dimension_matches(plot, hints) or bool(
                    expected_keys and expected_keys <= {str(k) for k in (plot.get("keys") or [])}
                )
                record["right_frames"] = int(plot.get("n_frames") or 0) == expected_frames
                record["polygons"] = self._draws_polygons(plot, polygons)
                widgets.append(record)
            elif self._is_lazy(plot):
                record["right_dimension"] = self._dimension_matches(plot, hints)
                lazy.append(record)
            elif self._draws_polygons(plot, polygons):
                flat.append(record)

        evidence = {
            "expected_frames": expected_frames,
            "widget_plots": widgets[:6],
            "lazy_plots": lazy[:4],
            "static_maps": flat[:4],
        }

        good = [w for w in widgets if w["right_dimension"] and w["right_frames"] and w["polygons"]]
        if good:
            return self._found(
                item,
                f"{what}: a {good[0]['type']} with {expected_frames} frames keyed on "
                f"`{', '.join(good[0]['key_dimensions']) or '?'}`, each drawing "
                f"{', '.join(good[0]['elements'])}.",
                evidence,
            )

        if lazy:
            return self._partial(
                item, float(config.get("dynamic_map_credit_ratio", 0.6)),
                f"{what}: the chart is a DynamicMap, so `dynamic=False` was left out "
                "of the hvplot call. It holds no frames, which means nothing renders "
                "in the submitted notebook and there is no map to page through.",
                evidence,
            )
        if widgets:
            best = max(widgets, key=lambda w: (w["polygons"], w["right_dimension"], w["right_frames"]))
            if not best["right_dimension"]:
                return self._partial(
                    item, float(config.get("wrong_dimension_credit_ratio", 0.5)),
                    f"{what}: the widget selects `{', '.join(best['key_dimensions']) or '?'}` "
                    f"rather than {'the year' if 'year' in ' '.join(hints) else 'the violation type'}.",
                    evidence,
                )
            return self._partial(
                item, float(config.get("wrong_dimension_credit_ratio", 0.5)),
                f"{what}: the widget is keyed correctly but holds {best['frames']} "
                f"frames rather than {expected_frames}"
                + ("" if best["polygons"] else ", and the frames are not maps")
                + ".",
                evidence,
            )
        if flat:
            return self._partial(
                item, float(config.get("no_widget_credit_ratio", 0.5)),
                f"{what}: maps were drawn, but as single static charts rather than a "
                "series with a widget — `groupby=` plus `dynamic=False` is what "
                "produces the dropdown.",
                evidence,
            )
        return self._missing(ctx, item, f"{what}: no choropleth was found.", evidence)

    def check_evictions_choropleth(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        return self._widget_choropleth(ctx, item, "Evictions by year")

    def check_violations_choropleth(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        return self._widget_choropleth(ctx, item, "Violations by type")

    # =================================================================
    # 1.2.1 — load the violations
    # =================================================================
    def check_violations_loading(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        config = item.config
        expected_rows = int(config.get("expected_rows", 434052))
        tolerance = int(config.get("row_tolerance", 0))
        expected_bounds = [float(b) for b in config.get("expected_bounds", [])]
        bounds_tolerance = float(config.get("bounds_tolerance", 0.5))

        sized = [
            profile for profile in self._frames(ctx)
            if self._rows_match(profile, expected_rows, tolerance)
        ]
        points = [
            profile for profile in sized
            if profile.get("is_geodataframe")
            and "Point" in (profile.get("geom_types") or [])
        ]
        evidence = {
            "expected_rows": expected_rows,
            "frames_with_expected_rows": [p.get("name") for p in sized][:4],
            "point_geodataframes": [p.get("name") for p in points][:4],
        }

        if not sized:
            return self._missing(
                ctx, item,
                f"No frame in memory holds the {expected_rows:,} rows of "
                "li_violations.csv.",
                evidence,
            )
        if not points:
            return self._partial(
                item, float(config.get("not_geodataframe_credit_ratio", 0.4)),
                f"The {expected_rows:,} violations were read, but never converted to "
                "a GeoDataFrame of points — `gpd.points_from_xy(df.lng, df.lat)` is "
                "what the rest of Part 1 needs.",
                evidence,
            )

        best = points[0]
        bounds = [as_float(b) for b in (best.get("total_bounds") or [])]
        evidence.update(
            {
                "frame": best.get("name"),
                "crs": best.get("crs_epsg") or best.get("crs"),
                "total_bounds": bounds,
                "expected_bounds": expected_bounds,
            }
        )
        # Philadelphia is at roughly (-75.1, 40.0). Passing lat before lng puts
        # every point at (40.0, -75.1), which is in the Indian Ocean — and the
        # spatial join then silently returns nothing.
        if expected_bounds and all(b is not None for b in bounds[:4]):
            swapped = (
                abs(bounds[0] - expected_bounds[1]) <= bounds_tolerance
                and abs(bounds[1] - expected_bounds[0]) <= bounds_tolerance
            )
            if swapped:
                return self._partial(
                    item, float(config.get("swapped_coordinates_credit_ratio", 0.3)),
                    "The points were built with latitude and longitude the wrong way "
                    f"round: the data spans {bounds[:2]} instead of "
                    f"{expected_bounds[:2]}, which places Philadelphia off the coast "
                    "of Somalia and empties the spatial join in 1.2.4.",
                    evidence, confidence=0.9,
                )
            in_place = all(
                abs(bounds[i] - expected_bounds[i]) <= bounds_tolerance for i in range(4)
            )
            if not in_place:
                return self._partial(
                    item, 0.5,
                    f"A point GeoDataFrame of {expected_rows:,} rows exists, but it "
                    f"spans {bounds} rather than the Philadelphia extent "
                    f"{expected_bounds}.",
                    evidence,
                )
        if not best.get("crs_epsg") and not best.get("crs"):
            return self._partial(
                item, float(config.get("missing_crs_credit_ratio", 0.75)),
                "The point GeoDataFrame was built correctly but has no CRS, so every "
                "reprojection and spatial join after this one depends on geopandas "
                "guessing. Pass `crs=\"EPSG:4326\"`.",
                evidence,
            )
        return self._found(
            item,
            f"Violations loaded and converted: {expected_rows:,} points, "
            f"EPSG:{best.get('crs_epsg')}.",
            evidence,
        )

    # =================================================================
    # 1.2.2 — trim to the fifteen types
    # =================================================================
    def check_violations_subset(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        config = item.config
        expected_rows = int(config.get("expected_rows", 34108))
        expected_types = {str(v) for v in config.get("violation_types", [])}
        expected_count = int(config.get("expected_type_count", len(expected_types) or 15))

        best: dict[str, Any] | None = None
        for profile in self._frames(ctx):
            column = self._column_holding(profile, expected_types, exact=False)
            if column is None:
                continue
            kept = self._samples(profile, column)
            candidate = {
                "frame": profile.get("name"),
                "rows": self._rows(profile),
                "column": column,
                "types_kept": len(kept),
                "unexpected_types": sorted(kept - expected_types)[:5],
                "missing_types": sorted(expected_types - kept)[:5],
            }
            key = (candidate["types_kept"] == expected_count,
                   candidate["rows"] == expected_rows, candidate["types_kept"])
            if best is None or key > (
                best["types_kept"] == expected_count,
                best["rows"] == expected_rows, best["types_kept"],
            ):
                best = candidate

        evidence = {
            "expected_rows": expected_rows,
            "expected_types": expected_count,
            **(best or {}),
        }
        if best is None:
            return self._missing(
                ctx, item,
                "No frame in memory is trimmed to the fifteen listed violation types.",
                evidence,
            )
        if best["types_kept"] == expected_count and best["rows"] == expected_rows:
            return self._found(
                item,
                f"Trimmed to the fifteen maintenance violation types: "
                f"{expected_rows:,} rows.",
                evidence,
            )
        return self._partial(
            item, float(config.get("partial_types_credit_ratio", 0.6)),
            f"The subset keeps {best['types_kept']} of the {expected_count} listed "
            f"types and {best['rows']:,} rows rather than {expected_rows:,}"
            + (f"; missing {', '.join(best['missing_types'])}" if best["missing_types"] else "")
            + ".",
            evidence,
        )

    # =================================================================
    # 1.2.3 — hex bin map
    # =================================================================
    def check_hexbin_map(self, ctx: GradingContext, item: RubricItem) -> RubricItemResult:
        config = item.config
        hexbin_pattern = self._matches_any(ctx, config.get("hexbin_patterns", ["hexbin("]))
        records = [
            record for record in self.charts(ctx).by_library(MATPLOTLIB)
            if "hexbin" in record.source
        ]
        # Reprojection is visible twice: as a call in the source, and as a frame
        # in a projected CRS in the kernel. Either is proof.
        projected = [
            profile.get("name") for profile in self._frames(ctx)
            if profile.get("crs_is_projected")
        ]
        reprojected = bool(projected) or bool(
            self._matches_any(ctx, config.get("reprojection_patterns", ["to_crs"]))
        )
        overlaid = bool(self._matches_any(ctx, config.get("overlay_patterns", [])))
        if records:
            overlaid = overlaid or any(
                re.search(r"boundary|ax\s*=\s*ax", record.source) for record in records
            )

        evidence = {
            "hexbin_in_source": bool(hexbin_pattern),
            "hexbin_cells": [record.code_cell for record in records][:3],
            "rendered": any(record.ok for record in records),
            "tracts_overlaid": overlaid,
            "projected_frames": projected[:4],
            "reprojected": reprojected,
        }

        if not hexbin_pattern and not records:
            return self._missing(
                ctx, item, "No hexbin() call was found in the notebook.", evidence
            )

        ratio = 1.0
        notes: list[str] = []
        if records and not evidence["rendered"]:
            ratio *= float(config.get("not_rendered_credit_ratio", 0.5))
            notes.append("the hex bin cell produced no image")
        if not overlaid:
            ratio *= float(config.get("missing_overlay_credit_ratio", 0.6))
            notes.append("the census tract outlines are not drawn over the hex bins")
        if not reprojected:
            ratio *= float(config.get("unprojected_credit_ratio", 0.75))
            notes.append(
                "the data was not reprojected out of EPSG:4326, so the hexagons are "
                "stretched by latitude"
            )

        if ratio >= 1.0:
            return self._found(
                item,
                f"Hex bin map drawn in code cell {evidence['hexbin_cells'][0]} with the "
                "tract outlines overlaid, in a projected CRS.",
                evidence,
            )
        return self._partial(item, ratio, "Hex bin map: " + "; ".join(notes) + ".", evidence)

    # =================================================================
    # 1.2.4 — spatial join
    # =================================================================
    def check_spatial_join(self, ctx: GradingContext, item: RubricItem) -> RubricItemResult:
        config = item.config
        expected_rows = int(config.get("expected_rows", 34108))
        tolerance = int(config.get("row_tolerance", 0))
        unfiltered = int(config.get("unfiltered_expected_rows", 434052))
        prefix = str(config.get("geoid_prefix", "42101"))
        required = [str(c) for c in config.get("requires_columns", ["GEOID"])]

        joined: list[dict[str, Any]] = []
        for profile in self._frames(ctx):
            if not self._has_columns(profile, required):
                continue
            if "Point" not in (profile.get("geom_types") or []):
                continue
            summary = self._geoid(profile, prefix)
            joined.append(
                {
                    "frame": profile.get("name"),
                    "rows": self._rows(profile),
                    "columns": self._columns(profile)[:10],
                    "share_in_philadelphia": round(summary["purity"], 4) if summary else None,
                }
            )

        evidence = {
            "expected_rows": expected_rows,
            "sjoin_in_source": bool(self._matches_any(ctx, [r"sjoin\s*\("])),
            "joined_frames": joined[:4],
        }

        if not joined:
            return self._missing(
                ctx, item,
                "No frame in memory carries a violation point together with the GEOID "
                "of the tract it falls in.",
                evidence,
            )

        exact = [f for f in joined if abs(f["rows"] - expected_rows) <= tolerance]
        if exact:
            return self._found(
                item,
                f"Spatial join complete: all {expected_rows:,} violations matched to a "
                "Philadelphia census tract, none lost.",
                evidence,
            )
        whole_file = [f for f in joined if abs(f["rows"] - unfiltered) <= max(tolerance, 5)]
        if whole_file:
            return self._partial(
                item, float(config.get("unfiltered_join_credit_ratio", 0.7)),
                f"The join ran on all {unfiltered:,} violations rather than on the "
                f"{expected_rows:,} of the fifteen listed types — the right operation "
                "in the wrong order.",
                evidence,
            )
        best = max(joined, key=lambda f: f["rows"])
        return self._partial(
            item, float(config.get("lossy_join_credit_ratio", 0.5)),
            f"The join kept {best['rows']:,} of the {expected_rows:,} violations. Every "
            "one of them is inside the city, so a join that loses rows usually means "
            "the two frames were in different CRSs (or the points were built with "
            "latitude and longitude swapped).",
            evidence,
        )

    # =================================================================
    # 1.2.5 — counts per type and tract
    # =================================================================
    def check_violations_by_tract(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        config = item.config
        allowed = [int(v) for v in config.get("allowed_row_counts", [4000, 5535])]
        expected_sum = float(config.get("expected_count_sum", 34108))
        expected_types = int(config.get("expected_type_count", 15))
        hints = [str(h).lower() for h in config.get("count_column_hints", ["n", "count"])]
        prefix = "42101"

        best: dict[str, Any] | None = None
        for profile in self._frames(ctx):
            if not self._is_narrow(profile):
                continue
            summary = self._geoid(profile, prefix)
            if not summary:
                continue
            counts = self._numeric_columns_matching(profile, "sum", expected_sum, 0.001)
            if not counts:
                continue
            type_column = None
            for column, distinct in (profile.get("nunique") or {}).items():
                if int(distinct or 0) == expected_types and column not in counts:
                    type_column = str(column)
                    break
            candidate = {
                "frame": profile.get("name"),
                "rows": self._rows(profile),
                "count_columns": counts,
                "named_count_column": bool(
                    any(any(h in c.lower() for h in hints) for c in counts)
                ),
                "type_column": type_column,
                "tracts": summary["distinct"],
            }
            key = (bool(type_column), candidate["rows"] in allowed, candidate["named_count_column"])
            if best is None or key > (
                bool(best["type_column"]), best["rows"] in allowed, best["named_count_column"]
            ):
                best = candidate

        evidence = {
            "allowed_row_counts": allowed,
            "expected_count_sum": expected_sum,
            **(best or {}),
        }
        if best is None:
            return self._missing(
                ctx, item,
                "No frame in memory holds a count of violations per type and tract "
                f"summing to {expected_sum:,.0f}.",
                evidence,
            )
        if best["type_column"] and best["tracts"] > 1:
            note = (
                " (the optional unstack/stack fill was applied, so tracts with no "
                "violations of a type are included)"
                if best["rows"] == max(allowed) else ""
            )
            return self._found(
                item,
                f"Counted per violation type and tract: {best['rows']:,} groups "
                f"totalling {expected_sum:,.0f} violations{note}.",
                evidence,
            )
        return self._partial(
            item, float(config.get("partial_grouping_credit_ratio", 0.5)),
            "The counts total correctly but the frame is grouped by only one of the "
            "two keys — the result should have a row per (violation type, tract) pair.",
            evidence,
        )

    # =================================================================
    # 1.2.6 — merge back onto geometries
    # =================================================================
    def check_merge_geometries(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        config = item.config
        allowed = [int(v) for v in config.get("allowed_row_counts", [4000, 5535])]
        expected_sum = 34108.0

        merged: list[dict[str, Any]] = []
        for profile in self._frames(ctx):
            if self._rows(profile) not in allowed or not self._is_narrow(profile):
                continue
            if not self._numeric_columns_matching(profile, "sum", expected_sum, 0.001):
                continue
            merged.append(
                {
                    "frame": profile.get("name"),
                    "rows": self._rows(profile),
                    "geodataframe": bool(profile.get("is_geodataframe")),
                    "geometry_types": profile.get("geom_types"),
                    "columns": self._columns(profile)[:8],
                }
            )

        evidence = {"allowed_row_counts": allowed, "candidates": merged[:4]}
        if not merged:
            return self._missing(
                ctx, item,
                "No frame in memory holds the per-tract violation counts joined to the "
                "tract geometries.",
                evidence,
            )
        geo = [m for m in merged if m["geodataframe"]]
        if geo:
            return self._found(
                item,
                f"Counts merged onto the tract geometries: a GeoDataFrame of "
                f"{geo[0]['rows']:,} rows.",
                evidence,
            )
        return self._partial(
            item, float(config.get("not_geodataframe_credit_ratio", 0.5)),
            "The merge produced a plain DataFrame rather than a GeoDataFrame, so it "
            "cannot be mapped. Put the frame holding the geometries first in "
            "`pd.merge()`.",
            evidence,
        )

    # =================================================================
    # 1.3 — side by side
    # =================================================================
    def check_side_by_side(self, ctx: GradingContext, item: RubricItem) -> RubricItemResult:
        config = item.config
        expected_columns = int(config.get("expected_columns", 2))
        polygons = config.get("polygon_elements", ["Polygons"])
        year_total = float(config.get("expected_eviction_year_total", 10264))
        rel_tol = float(config.get("eviction_total_rel_tol", 0.001))

        layouts: list[dict[str, Any]] = []
        for plot in self._plots(ctx):
            if str(plot.get("type")) not in LAYOUT_CONTAINERS:
                continue
            shape = [int(v) for v in (plot.get("shape") or [0, 0])[:2]]
            children = [str(c) for c in (plot.get("child_types") or [])]
            layouts.append(
                {
                    "plot": plot.get("name"),
                    "shape": shape,
                    "panels": int(plot.get("n_frames") or 0),
                    "elements": plot.get("element_types"),
                    "panel_types": children,
                    "maps": self._draws_polygons(plot, polygons),
                    # The panels of *this* layout, not any widget in the
                    # notebook: 1.1.5 and 1.2.7 leave their own HoloMaps behind.
                    "still_grouped": any(
                        c in WIDGET_CONTAINERS or c in LAZY_CONTAINERS for c in children
                    ),
                }
            )
        # One year, one violation type: the frames the two panels should come from.
        single_year = [
            profile.get("name") for profile in self._frames(ctx)
            if self._is_narrow(profile)
            and self._numeric_columns_matching(profile, "sum", year_total, rel_tol)
        ]

        evidence = {
            "expected_columns": expected_columns,
            "layouts": layouts[:4],
            "frames_for_2016_evictions": single_year[:3],
            "expected_eviction_year_total": year_total,
        }

        if not layouts:
            maps = [
                plot.get("name") for plot in self._plots(ctx)
                if self._draws_polygons(plot, polygons) and not plot.get("is_container")
            ]
            evidence["standalone_maps"] = maps[:4]
            if len(maps) >= 2:
                return self._partial(
                    item, float(config.get("not_composed_credit_ratio", 0.5)),
                    "Two maps were drawn but never composed: `left + right` places them "
                    "side by side in one Layout.",
                    evidence,
                )
            return self._missing(
                ctx, item, "No side-by-side comparison was found.", evidence
            )

        best = max(
            layouts,
            key=lambda L: (L["maps"], not L["still_grouped"], L["panels"] >= 2, L["shape"][1]),
        )
        ratio = 1.0
        notes: list[str] = []
        if not best["maps"]:
            ratio *= 0.5
            notes.append("the composed panels are not choropleths")
        if best["shape"][1] != expected_columns and best["panels"] >= 2:
            ratio *= float(config.get("wrong_orientation_credit_ratio", 0.85))
            notes.append(
                f"the two maps are laid out {best['shape'][0]} x {best['shape'][1]} "
                f"rather than 1 x {expected_columns}"
            )
        if not single_year:
            ratio *= float(config.get("wrong_subset_credit_ratio", 0.75))
            notes.append(
                f"no frame holds a single year of evictions (2016 totals "
                f"{year_total:,.0f} across the city), so the left panel does not look "
                "like the one year the instructions ask for"
            )
        if best["still_grouped"] and best["panels"] >= 2 and not notes:
            ratio *= float(config.get("still_grouped_credit_ratio", 0.75))
            notes.append("the panels still carry their year/type widget")

        if ratio >= 1.0:
            return self._found(
                item,
                f"Side-by-side comparison: a Layout of {best['panels']} choropleths "
                f"in {best['shape'][0]} row x {best['shape'][1]} columns.",
                evidence,
            )
        return self._partial(
            item, ratio, "Side-by-side comparison: " + "; ".join(notes) + ".", evidence
        )

    # =================================================================
    # 2.1.1 — open the Landsat scene
    # =================================================================
    def check_landsat_loading(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        config = item.config
        bands = int(config.get("expected_band_count", 10))
        epsg = config.get("expected_crs_epsg")
        width = int(config.get("expected_width", 0))
        height = int(config.get("expected_height", 0))
        array_shape = [int(v) for v in config.get("expected_array_shape", [])]

        rasters = [
            {
                "name": raster.get("name"),
                "bands": raster.get("count"),
                "width": raster.get("width"),
                "height": raster.get("height"),
                "crs": raster.get("crs"),
                "path": raster.get("path"),
            }
            for raster in self._rasters(ctx)
        ]
        # `with rasterio.open(...) as src:` closes the dataset and leaves nothing
        # in the namespace; the band stack read out of it is the same evidence.
        stacks = [
            array.get("name") for array in self._arrays(ctx)
            if array_shape and list(array.get("shape") or []) == array_shape
        ]
        evidence = {
            "expected": {"bands": bands, "crs_epsg": epsg, "width": width, "height": height},
            "open_datasets": rasters[:4],
            "band_stacks": stacks[:3],
        }

        def right(raster: dict[str, Any]) -> bool:
            return (
                int(raster.get("bands") or 0) == bands
                and int(raster.get("width") or 0) == width
                and int(raster.get("height") or 0) == height
                and (epsg is None or str(epsg) in str(raster.get("crs") or ""))
            )

        matched = [raster for raster in rasters if right(raster)]
        if matched or stacks:
            return self._found(
                item,
                f"Landsat scene opened with rasterio: {bands} bands, {width} x {height}, "
                f"EPSG:{epsg}.",
                evidence,
            )
        if rasters:
            return self._partial(
                item, float(config.get("wrong_raster_credit_ratio", 0.4)),
                "A raster was opened, but it is not the "
                f"{bands}-band {width} x {height} scene that ships with the assignment "
                f"(found {rasters[0]['bands']} bands, "
                f"{rasters[0]['width']} x {rasters[0]['height']}).",
                evidence,
            )
        return self._missing(
            ctx, item, "No raster was opened with rasterio.", evidence
        )

    # =================================================================
    # 2.1.2 — city and suburb polygons
    # =================================================================
    def check_city_suburb_polygons(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        config = item.config
        city_area = float(config.get("expected_city_area", 0))
        suburb_area = float(config.get("expected_suburb_area", 0))
        rel_tol = float(config.get("area_rel_tol", 0.02))

        def close(value: float | None, expected: float) -> bool:
            return value is not None and abs(value - expected) <= expected * rel_tol

        # A polygon may be held as a bare shapely object or as the one-row frame
        # it was read from; both carry an area, so both are graded the same way.
        areas: list[dict[str, Any]] = [
            {
                "name": geometry.get("name"),
                "held_as": "geometry",
                "geom_type": geometry.get("geom_type"),
                "area": as_float(geometry.get("area")),
            }
            for geometry in self._geometries(ctx)
        ]
        areas += [
            {
                "name": profile.get("name"),
                "held_as": "frame",
                "geom_type": ", ".join(profile.get("geom_types") or []),
                "area": as_float(profile.get("geometry_area")),
            }
            for profile in self._frames(ctx)
            if profile.get("geometry_area") is not None and self._rows(profile) <= 10
        ]

        city = [a for a in areas if close(a["area"], city_area)]
        suburbs = [a for a in areas if close(a["area"], suburb_area)]
        envelope = [a for a in areas if close(a["area"], city_area + suburb_area)]
        # Square degrees rather than square metres: the city is ~0.037 of one.
        degrees = [a for a in areas if a["area"] is not None and 0 < a["area"] < 1000]

        evidence = {
            "expected_city_area": city_area,
            "expected_suburb_area": suburb_area,
            "polygons": areas[:8],
            "city_match": [a["name"] for a in city][:3],
            "suburb_match": [a["name"] for a in suburbs][:3],
        }

        if city and suburbs:
            return self._found(
                item,
                f"City and suburb polygons built: {city_area / 1e6:,.0f} km2 inside the "
                f"city limits and {suburb_area / 1e6:,.0f} km2 in the surrounding "
                "envelope.",
                evidence,
            )
        if city and envelope:
            return self._partial(
                item, float(config.get("envelope_not_differenced_credit_ratio", 0.5)),
                "The suburbs polygon is the whole envelope rather than the envelope "
                "with the city cut out of it — `envelope.difference(city)` is the step "
                "that leaves the ring.",
                evidence,
            )
        if city:
            return self._partial(
                item, float(config.get("missing_suburbs_credit_ratio", 0.5)),
                "The city limits polygon is there, but no suburbs polygon was built "
                "from its envelope.",
                evidence,
            )
        if degrees and not city:
            return self._partial(
                item, float(config.get("unprojected_credit_ratio", 0.4)),
                "The city limits polygon is still in degrees rather than in the "
                "raster's UTM CRS. Masking with it selects nothing, so every NDVI "
                "below comes back empty — reproject with "
                "`.to_crs(landsat.crs)` before taking the envelope.",
                evidence,
            )
        return self._missing(
            ctx, item, "No city limits or suburbs polygon was found.", evidence
        )

    # =================================================================
    # 2.1.3 — mask and compute the NDVI
    # =================================================================
    def _ndvi_arrays(self, ctx: GradingContext, valid_range: list[float]) -> list[dict[str, Any]]:
        """Arrays whose values are bounded like an NDVI, with their statistics."""
        low, high = (valid_range + [-1.0, 1.0])[:2]
        found = []
        for array in self._arrays(ctx):
            minimum, maximum = as_float(array.get("min")), as_float(array.get("max"))
            if minimum is None or maximum is None:
                continue
            if minimum < low or maximum > high:
                continue
            if int(array.get("finite_count") or 0) < 1000:
                continue
            found.append(
                {
                    "name": array.get("name"),
                    "shape": array.get("shape"),
                    "pixels": int(array.get("finite_count") or 0),
                    "median": as_float(array.get("median")),
                    "mean": as_float(array.get("mean")),
                    "min": minimum,
                    "max": maximum,
                }
            )
        return found

    def check_ndvi_masking(self, ctx: GradingContext, item: RubricItem) -> RubricItemResult:
        config = item.config
        city_pixels = int(config.get("expected_city_pixels", 0))
        suburb_pixels = int(config.get("expected_suburb_pixels", 0))
        pixel_tol = float(config.get("pixel_rel_tol", 0.05))
        city_median = float(config.get("expected_city_median", 0))
        suburb_median = float(config.get("expected_suburb_median", 0))
        median_tol = float(config.get("median_abs_tol", 0.02))
        valid_range = [float(v) for v in config.get("valid_range", [-1.0, 1.0])]

        candidates = self._ndvi_arrays(ctx, valid_range)
        masked = bool(self._matches_any(ctx, config.get("mask_patterns", ["mask("])))

        def by_pixels(expected: int) -> list[dict[str, Any]]:
            return [
                c for c in candidates
                if abs(c["pixels"] - expected) <= expected * pixel_tol
            ]

        city = [c for c in by_pixels(city_pixels)
                if c["median"] is not None and abs(c["median"] - city_median) <= median_tol]
        suburbs = [c for c in by_pixels(suburb_pixels)
                   if c["median"] is not None and abs(c["median"] - suburb_median) <= median_tol]

        evidence = {
            "expected": {
                "city_pixels": city_pixels, "suburb_pixels": suburb_pixels,
                "city_median": city_median, "suburb_median": suburb_median,
            },
            "mask_call_in_source": masked,
            "ndvi_like_arrays": candidates[:6],
            "city_match": [c["name"] for c in city][:2],
            "suburb_match": [c["name"] for c in suburbs][:2],
        }

        if city and suburbs:
            return self._found(
                item,
                "Raster masked twice and the NDVI computed for each area: "
                f"{city_pixels:,} pixels inside the city and {suburb_pixels:,} outside.",
                evidence,
            )
        if city or suburbs:
            return self._partial(
                item, float(config.get("one_area_credit_ratio", 0.5)),
                "The NDVI was computed for "
                f"{'the city' if city else 'the suburbs'} but not for "
                f"{'the suburbs' if city else 'the city'}.",
                evidence,
            )
        if candidates:
            # Bounded like an NDVI, sized like the mask, but centred nowhere near
            # a vegetation index over Philadelphia: band indexing, almost always.
            seen = ", ".join(
                "{:.3f}".format(c["median"])
                for c in candidates[:2] if c["median"] is not None
            )
            return self._partial(
                item, float(config.get("wrong_bands_credit_ratio", 0.5)),
                f"Masked arrays were produced but their medians ({seen}) are not the "
                f"{city_median:.3f} and {suburb_median:.3f} this scene gives. "
                "Landsat 8 band 4 is red and band 5 is near-infrared, which are "
                "index 3 and index 4 of the array the mask returns.",
                evidence,
            )
        return self._missing(
            ctx, item,
            "No NDVI array was found: nothing in memory is an array of values "
            "between -1 and 1 the size of a masked Landsat scene.",
            evidence,
        )

    # =================================================================
    # 2.1.4 — compare the medians
    # =================================================================
    def check_ndvi_medians(self, ctx: GradingContext, item: RubricItem) -> RubricItemResult:
        config = item.config
        city_median = float(config.get("expected_city_median", 0))
        suburb_median = float(config.get("expected_suburb_median", 0))
        tolerance = float(config.get("median_abs_tol", 0.02))

        scalars = [
            {"name": entry.get("name"), "value": as_float(entry.get("value")),
             "raw": entry.get("value"), "type": entry.get("type")}
            for entry in (ctx.probe or {}).get("scalars", []) or []
            if not isinstance(entry.get("value"), str)
        ]
        city = [s for s in scalars if s["value"] is not None
                and abs(s["value"] - city_median) <= tolerance]
        suburbs = [s for s in scalars if s["value"] is not None
                   and abs(s["value"] - suburb_median) <= tolerance]
        # `print(np.nanmedian(city_ndvi))` computes the answer without binding it,
        # so the arrays themselves stand in when no scalar was kept.
        arrays = self._ndvi_arrays(ctx, [float(v) for v in config.get("valid_range", [-1.0, 1.0])])
        array_city = [a for a in arrays if a["median"] is not None
                      and abs(a["median"] - city_median) <= tolerance]
        array_suburbs = [a for a in arrays if a["median"] is not None
                         and abs(a["median"] - suburb_median) <= tolerance]
        printed = bool(self._matches_any(ctx, config.get("print_patterns", ["print("])))
        nan_medians = [
            s for s in scalars
            if s["value"] is None and "float" in str(s.get("type", "")).lower()
        ]

        evidence = {
            "expected_city_median": city_median,
            "expected_suburb_median": suburb_median,
            "matching_scalars": {
                "city": [s["name"] for s in city][:3],
                "suburbs": [s["name"] for s in suburbs][:3],
            },
            "matching_arrays": {
                "city": [a["name"] for a in array_city][:3],
                "suburbs": [a["name"] for a in array_suburbs][:3],
            },
            "printed": printed,
            "nanmedian_used": bool(self._matches_any(ctx, [r"nanmedian"])),
        }

        if (city or array_city) and (suburbs or array_suburbs):
            return self._found(
                item,
                f"Median NDVI compared: {city_median:.4f} inside the city against "
                f"{suburb_median:.4f} in the suburbs — the suburbs are greener, as "
                "expected.",
                evidence,
            )
        if nan_medians and not evidence["nanmedian_used"]:
            return self._partial(
                item, float(config.get("nan_result_credit_ratio", 0.4)),
                "The medians came back as NaN. A masked NDVI array is mostly NaN "
                "outside its polygon, so `np.median()` returns NaN — `np.nanmedian()` "
                "is the one that ignores them.",
                evidence, confidence=0.85,
            )
        # Two numbers in a plausible NDVI range, ordered the right way, but not
        # the values this scene gives.
        plausible = sorted(
            [s for s in scalars if s["value"] is not None and -1.0 <= s["value"] <= 1.0],
            key=lambda s: s["value"] or 0.0,
        )
        if len(plausible) >= 2 and bool(config.get("expect_suburbs_greater", True)):
            evidence["plausible_scalars"] = [
                {"name": s["name"], "value": s["value"]} for s in plausible[:4]
            ]
            return self._partial(
                item, float(config.get("right_direction_credit_ratio", 0.5)),
                "Two median NDVI values were computed and the suburbs come out greener "
                "than the city, but the values do not match the ones this scene gives "
                f"({city_median:.4f} and {suburb_median:.4f}).",
                evidence,
            )
        return self._missing(
            ctx, item, "No median NDVI was computed for the city and the suburbs.",
            evidence,
        )

    # =================================================================
    # 2.2.1 — street trees
    # =================================================================
    def check_tree_data_loading(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        config = item.config
        expected_rows = int(config.get("expected_rows", 2480))
        tolerance = int(config.get("row_tolerance", 0))
        raster_epsg = config.get("raster_crs_epsg")

        loaded = [
            {
                "frame": profile.get("name"),
                "rows": self._rows(profile),
                "geometry_types": profile.get("geom_types"),
                "crs": profile.get("crs_epsg"),
                "is_geodataframe": bool(profile.get("is_geodataframe")),
            }
            for profile in self._frames(ctx)
            if self._rows_match(profile, expected_rows, tolerance)
            and "Point" in (profile.get("geom_types") or [])
        ]
        evidence = {"expected_rows": expected_rows, "tree_frames": loaded[:4]}

        if not loaded:
            return self._missing(
                ctx, item,
                f"No frame in memory holds the {expected_rows:,} street tree points.",
                evidence,
            )
        if raster_epsg is not None and not any(
            str(frame["crs"]) == str(raster_epsg) for frame in loaded
        ):
            return self._partial(
                item, float(config.get("unprojected_credit_ratio", 0.6)),
                f"The {expected_rows:,} tree points were loaded but never reprojected "
                f"into the raster's CRS (EPSG:{raster_epsg}), so sampling the NDVI at "
                "their coordinates cannot line up with the scene.",
                evidence,
            )
        return self._found(
            item,
            f"Street tree data loaded: {expected_rows:,} points in "
            f"EPSG:{raster_epsg}.",
            evidence,
        )

    # =================================================================
    # 2.2.2 — sample the NDVI at the trees
    # =================================================================
    def check_tree_ndvi(self, ctx: GradingContext, item: RubricItem) -> RubricItemResult:
        config = item.config
        expected_count = int(config.get("expected_count", 2480))
        tolerance = int(config.get("count_tolerance", 5))
        expected_median = float(config.get("expected_median", 0))
        median_tol = float(config.get("median_abs_tol", 0.03))
        low, high = (list(config.get("valid_range", [-1.0, 1.0])) + [-1.0, 1.0])[:2]
        max_nan = float(config.get("max_nan_fraction", 0.05))

        # One value per tree, wherever the student kept it: a column on the tree
        # frame, a bare Series, or the list rasterstats handed back.
        samples: list[dict[str, Any]] = []
        for profile in self._frames(ctx):
            if not self._is_narrow(profile, 40):
                continue
            for column, summary in (profile.get("numeric_summary") or {}).items():
                samples.append(
                    {"held_as": f"{profile.get('name')}[{column}]", **summary,
                     "rows": self._rows(profile)}
                )
        for entry in self._series(ctx):
            summary = entry.get("numeric_summary") or {}
            if summary:
                samples.append({"held_as": entry.get("name"), **summary,
                                "rows": int(entry.get("length") or 0)})
        for entry in self._collections(ctx):
            summary = entry.get("numeric_summary") or {}
            if summary:
                samples.append({"held_as": entry.get("name"), **summary,
                                "rows": int(entry.get("length") or 0)})

        def sized(sample: dict[str, Any]) -> bool:
            count = int(sample.get("count") or 0)
            rows = int(sample.get("rows") or 0)
            return (
                abs(count - expected_count) <= tolerance
                or (abs(rows - expected_count) <= tolerance
                    and count >= expected_count * (1 - max_nan))
            )

        def bounded(sample: dict[str, Any]) -> bool:
            minimum, maximum = as_float(sample.get("min")), as_float(sample.get("max"))
            return (
                minimum is not None and maximum is not None
                and minimum >= low and maximum <= high
            )

        right_size = [s for s in samples if sized(s)]
        ndvi_like = [s for s in right_size if bounded(s)]
        matching = [
            s for s in ndvi_like
            if as_float(s.get("median")) is not None
            and abs(as_float(s.get("median")) - expected_median) <= median_tol
        ]
        used_rasterstats = bool(
            self._matches_any(ctx, config.get("rasterstats_patterns", ["point_query"]))
        )
        used_alternative = bool(
            self._matches_any(ctx, config.get("alternative_patterns", []))
        )

        evidence = {
            "expected_count": expected_count,
            "expected_median": expected_median,
            "rasterstats_used": used_rasterstats,
            "alternative_sampling_used": used_alternative,
            "candidates": [
                {k: v for k, v in s.items() if k in
                 ("held_as", "count", "min", "max", "mean", "median")}
                for s in right_size[:6]
            ],
        }

        if matching:
            note = "" if used_rasterstats else (
                " (sampled without rasterstats, which answers the question all the same)"
            )
            return self._found(
                item,
                f"NDVI sampled at all {expected_count:,} tree locations, median "
                f"{expected_median:.3f}{note}.",
                evidence,
            )
        if ndvi_like or right_size:
            return self._partial(
                item, float(config.get("wrong_values_credit_ratio", 0.4)),
                f"One value per tree was produced, but they are not the NDVI at those "
                f"points — the median is "
                f"{as_float((ndvi_like or right_size)[0].get('median'))}, not "
                f"{expected_median:.3f}. Sample the NDVI array, not a raw band.",
                evidence,
            )
        return self._missing(
            ctx, item,
            f"No set of {expected_count:,} NDVI values at the tree locations was found.",
            evidence,
        )

    # =================================================================
    # 2.2.3 — the two figures
    # =================================================================
    def _tree_figures(
        self, ctx: GradingContext, config: dict[str, Any]
    ) -> tuple[Any, Any]:
        """The histogram and the mapped points, as chart records."""
        records = self.charts(ctx).by_library(MATPLOTLIB)
        histogram = next(
            (r for r in records
             if self._source_matches(r.source, config.get("histogram_patterns", []))),
            None,
        )
        mapped = next(
            (r for r in records
             if r is not histogram
             and self._source_matches(r.source, config.get("point_plot_patterns", []))
             and "column=" in r.source),
            None,
        )
        return histogram, mapped

    @staticmethod
    def _source_matches(source: str, patterns: Iterable[str]) -> bool:
        for pattern in patterns or ():
            try:
                if re.search(str(pattern), source):
                    return True
            except re.error:
                if str(pattern) in source:
                    return True
        return False

    def check_tree_plots(self, ctx: GradingContext, item: RubricItem) -> RubricItemResult:
        config = item.config
        histogram_share = float(config.get("histogram_share", 0.5))
        detail_share = float(config.get("detail_share", 0.35))
        not_rendered = float(config.get("not_rendered_credit_ratio", 0.5))

        histogram, mapped = self._tree_figures(ctx, config)
        parts: list[dict[str, Any]] = []

        def score_part(record, detail_patterns, label, detail_label, share) -> float:
            if record is None:
                parts.append({"figure": label, "found": False, "credit": 0.0})
                return 0.0
            has_detail = self._source_matches(record.source, detail_patterns)
            credit = (1 - detail_share) + (detail_share if has_detail else 0.0)
            if not record.ok:
                credit *= not_rendered
            parts.append(
                {
                    "figure": label,
                    "found": True,
                    "code_cell": record.code_cell,
                    "rendered": record.ok,
                    detail_label: has_detail,
                    "credit": round(credit, 3),
                }
            )
            return credit * share

        ratio = score_part(
            histogram, config.get("zero_line_patterns", []), "histogram",
            "zero_line", histogram_share,
        )
        ratio += score_part(
            mapped, config.get("boundary_patterns", []), "tree points map",
            "city_boundary", 1.0 - histogram_share,
        )

        evidence = {"figures": parts}
        if ratio >= 1.0:
            return self._found(
                item,
                "Both figures drawn: a histogram of the tree NDVI values with the zero "
                "line marked, and the tree points coloured by NDVI over the city limits.",
                evidence,
            )
        missing = [p["figure"] for p in parts if not p["found"]]
        if not any(p["found"] for p in parts):
            return self._missing(
                ctx, item, "Neither of the two required figures was found.", evidence
            )
        return self._partial(
            item, ratio,
            "Tree figures: "
            + (f"{' and '.join(missing)} not found; " if missing else "")
            + "; ".join(
                f"{p['figure']} at {p['credit']:.0%} credit" for p in parts if p["found"]
            )
            + ".",
            evidence,
        )

    def check_tree_plot_styling(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        """The one item on this assignment that a person has to look at.

        The assignment asks for figures that are "clear and well-styled", which is
        a statement about a picture. The signals below say where to look; they
        cannot say whether the picture reads, so this always comes back as manual
        review with a provisional score rather than a silent mark.
        """
        config = item.config
        weights = {str(k): float(v) for k, v in (config.get("weighted_signals") or {}).items()}
        ceiling = float(config.get("provisional_ceiling_ratio", 0.8))
        plots_config = self.rubric.item("tree_plots")
        histogram, mapped = self._tree_figures(
            ctx, plots_config.config if plots_config else {}
        )
        records = [r for r in (histogram, mapped) if r is not None]

        if not records:
            return self.result(
                item, 0.0, STATUS_MANUAL_REVIEW, 0.35,
                "Provisional: neither tree figure was found, so there is nothing to "
                "judge for labelling, legend and colour.",
                {"figures": []},
            )

        total = sum(weights.values()) or 1.0
        detail = []
        ratios = []
        for record in records:
            present = sorted(k for k, v in record.aesthetics.items() if v)
            missing = sorted(k for k, v in record.aesthetics.items() if not v and k in weights)
            earned = sum(weight for name, weight in weights.items() if record.aesthetics.get(name))
            ratio = earned / total
            if not record.ok:
                ratio *= 0.5
            ratios.append(ratio)
            detail.append(
                {
                    "code_cell": record.code_cell,
                    "rendered": record.ok,
                    "signals_present": present,
                    "signals_missing": missing,
                    "source": record.source[:900],
                }
            )

        ratio = min(sum(ratios) / len(ratios), ceiling)
        # Per figure, not pooled: a histogram with axis labels and a map without
        # them are two different notes for a TA, and "missing: x_label" across
        # both would be wrong about the histogram.
        notes = "; ".join(
            f"cell {d['code_cell']} missing {', '.join(d['signals_missing'])}"
            for d in detail if d["signals_missing"]
        )
        feedback = (
            "Provisional from the labelling, legend and colour calls in code cells "
            + ", ".join(str(d["code_cell"]) for d in detail)
            + (f" ({notes})" if notes else "")
            + ". These signals cannot tell whether the figures actually read well — "
            "open the two images and set the mark."
        )
        return self.result(
            item, float(item.points) * ratio, STATUS_MANUAL_REVIEW, 0.35, feedback,
            {"figures": detail, "provisional_score": round(float(item.points) * ratio, 2),
             "provisional_basis": "structural signals"},
        )

    # =================================================================
    # 1.4 — extra credit
    # =================================================================
    def check_common_violations_extra_credit(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        config = item.config
        suggested = float(config.get("suggested_points", 5))
        expected_frames = int(config.get("expected_frames", 20))
        expected_sum = float(config.get("expected_count_sum", 235542))
        min_words = int(config.get("min_discussion_words", 25))

        wide_widgets = [
            {
                "plot": plot.get("name"),
                "frames": int(plot.get("n_frames") or 0),
                "key_dimensions": plot.get("kdims"),
            }
            for plot in self._plots(ctx)
            if self._is_widget(plot) and int(plot.get("n_frames") or 0) >= expected_frames
        ]
        top20_frames = [
            profile.get("name") for profile in self._frames(ctx)
            if any(int(v or 0) == expected_frames for v in (profile.get("nunique") or {}).values())
            or self._numeric_columns_matching(profile, "sum", expected_sum, 0.01)
        ]
        # The written half: three violation types named as not overlapping.
        discussion = [
            cell for cell in ctx.analysis.markdown_cells
            if len(cell.split()) >= min_words
            and re.search(r"overlap|violation|evict", cell, re.I)
        ]

        evidence = {
            "suggested_points": suggested,
            "widgets_with_20_frames": wide_widgets[:3],
            "frames_with_top_20_types": top20_frames[:3],
            "discussion_cells": len(discussion),
            "discussion": (discussion[-1][:600] if discussion else ""),
        }

        if not wide_widgets and not top20_frames:
            return self.result(
                item, 0.0, STATUS_NOT_FOUND, 1.0,
                "Extra credit not attempted.", evidence,
            )
        found = "a widget with 20 frames" if wide_widgets else "the twenty most common types"
        return self.result(
            item, 0.0, STATUS_MANUAL_REVIEW, 0.5,
            f"Extra credit attempted ({found}"
            + (f", with {len(discussion)} markdown cells discussing the overlap"
               if discussion else ", but no written discussion of which three types "
               "do not overlap")
            + f"). Suggested bonus: {suggested:g} points — award it with a manual "
            "override, which adds to the total without changing the maximum.",
            evidence,
        )
