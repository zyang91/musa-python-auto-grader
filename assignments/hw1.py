"""Assignment 1 autograder — "The Donut Effect for Philadelphia ZIP Codes".

Graded against ``assignment_template/assignment-1.ipynb``.

The class downloads its own Zillow ZHVI extract, and Zillow revises that file
continuously, so absolute row counts, ZIP counts and final percentages are not
gradeable facts. These checks ask whether each step in the instructions *worked*,
and verify it against the student's own data:

* the tidy frame must match the student's own (ZIP x date) grid,
* the two split frames must partition the student's own Philadelphia ZIPs,
* the percent-increase function is called on a frame the grader builds, so the
  right answer is known regardless of what the student loaded,
* the final comparison is checked for shape and direction, never for a value.

The only fixed values live in ``rubrics/hw1.yaml``, and they are the ones the
assignment itself fixes: the Center City ZIP list printed in the template, and
the two comparison dates named in the instructions.
"""

from __future__ import annotations

import ast
import re
import textwrap
from typing import Any

from grader import inspection
from grader.models import (
    STATUS_FAIL,
    STATUS_MANUAL_REVIEW,
    STATUS_NOT_FOUND,
    STATUS_PARTIAL,
    STATUS_PASS,
    RubricItemResult,
)
from grader.rubric import RubricItem
from grader.utils import as_float, is_close, jaccard, normalize_zips

from .base import AssignmentGrader, GradingContext, register

# A Zillow extract's value columns are dates: "2020-03-31", "2020-03", "3/31/20".
DATE_COLUMN_RE = re.compile(r"(19|20)\d{2}[-/_.]?\d{1,2}")


@register
class HW1Grader(AssignmentGrader):
    assignment_id = "hw1"

    # -- shared config -----------------------------------------------------
    @property
    def id_hints(self) -> list[str]:
        return self.rubric.probe.get("id_column_hints", ["zip", "regionname"])

    @property
    def date_hints(self) -> list[str]:
        return self.rubric.probe.get("date_column_hints", ["date", "variable"])

    @property
    def value_hints(self) -> list[str]:
        return self.rubric.probe.get("value_column_hints", ["zhvi", "value"])

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _date_column_count(profile: dict[str, Any]) -> int:
        return sum(1 for c in profile.get("columns", []) if DATE_COLUMN_RE.search(str(c)))

    def _zip_frames(self, ctx: GradingContext) -> list[dict[str, Any]]:
        """Every dataframe in memory that carries recognisable ZIP codes."""
        frames = []
        for profile in inspection.dataframes(ctx.probe):
            zips = inspection.zips_in_profile(profile, self.id_hints)
            if zips:
                frames.append({"profile": profile, "zips": zips})
        return frames

    def _philadelphia_zips(self, ctx: GradingContext, prefix: str = "191") -> set[str]:
        """The student's own Philadelphia ZIP universe — the yardstick for the split."""
        best: set[str] = set()
        for frame in self._zip_frames(ctx):
            local = {z for z in frame["zips"] if z.startswith(prefix)}
            if len(local) > len(best) and len(local) >= 0.6 * len(frame["zips"]):
                best = local
        return best

    @staticmethod
    def _column_values(profile: dict[str, Any], column: str | None) -> list[str]:
        if not column:
            return []
        return [str(v) for v in (profile.get("value_samples") or {}).get(column, [])]

    # -----------------------------------------------------------------
    # 1. Load the data
    # -----------------------------------------------------------------
    def check_data_loading(self, ctx: GradingContext, item: RubricItem) -> RubricItemResult:
        analysis = ctx.analysis
        config = item.config
        deductions: list[tuple[float, str]] = []

        missing = [lib for lib in config.get("required_imports", ["pandas"])
                   if lib not in analysis.imports]
        if missing:
            deductions.append((2.0, f"missing import: {', '.join(missing)}"))

        if not analysis.read_calls:
            deductions.append(
                (float(config.get("missing_read_penalty", 6)),
                 "no pandas read_* call was found in the notebook")
            )

        if analysis.absolute_paths:
            deductions.append(
                (float(config.get("absolute_path_penalty", 4)),
                 "absolute file path(s) used instead of a relative path: "
                 + ", ".join(analysis.absolute_paths[:3]))
            )

        min_dates = int(config.get("min_date_columns", 24))
        wide = inspection.find_dataframe_candidates(
            ctx.probe,
            lambda p: self._date_column_count(p) >= min_dates,
            score=lambda p: self._date_column_count(p),
        )
        if ctx.probe_ok and not wide:
            deductions.append(
                (float(config.get("no_dataframe_penalty", 4)),
                 "no wide ZHVI-style dataframe (many monthly columns) was found in memory")
            )

        evidence: dict[str, Any] = {
            "imports": sorted(analysis.imports),
            "read_calls": analysis.read_calls,
            "referenced_files": analysis.referenced_files,
            "absolute_paths": analysis.absolute_paths,
            "loaded_dataframe": inspection.describe_dataframe(wide[0]) if wide else None,
            "date_columns_detected": self._date_column_count(wide[0]) if wide else 0,
        }

        score = max(float(item.points) - sum(d[0] for d in deductions), 0.0)
        if not deductions:
            return self.result(
                item, score, STATUS_PASS, 1.0,
                "Data loaded with pandas from a relative path.", evidence,
            )
        return self.result(
            item, score, STATUS_PARTIAL if score > 0 else STATUS_FAIL, 1.0,
            "Deductions: " + "; ".join(f"{why} (-{pts:g})" for pts, why in deductions),
            evidence,
        )

    # -----------------------------------------------------------------
    # 2. Trim to Philadelphia
    # -----------------------------------------------------------------
    def check_philadelphia_subset(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        if not ctx.probe_ok:
            return self.no_probe_result(item, ctx)

        config = item.config
        prefix = str(config.get("expected_zip_prefix", "191"))
        min_zips = int(config.get("min_zip_count", 10))
        expected_cities = {
            str(v).lower() for v in config.get("expected_city_values", ["Philadelphia"])
        }
        # "PA" and "Pennsylvania" both name the right state.
        expected_states = {
            str(v).lower() for v in config.get("expected_state_values", ["PA", "Pennsylvania"])
        }

        candidates = []
        for frame in self._zip_frames(ctx):
            zips = frame["zips"]
            philly = {z for z in zips if z.startswith(prefix)}
            if len(philly) < min_zips:
                continue
            candidates.append(
                {
                    "profile": frame["profile"],
                    "zips": zips,
                    "philly": philly,
                    "purity": len(philly) / len(zips),
                    "outside": sorted(zips - philly)[:10],
                }
            )

        if not candidates:
            return self.result(
                item, 0.0, STATUS_NOT_FOUND, 0.6,
                "No dataframe holding Philadelphia ZIP codes was found in the notebook's "
                "namespace, so the trimming step could not be verified.",
                {"dataframes_inspected": len(inspection.dataframes(ctx.probe))},
            )

        # The Philadelphia subset is the widest ZIP coverage; the Center City and
        # remainder frames are deliberate subsets of it, not competing answers.
        candidates.sort(key=lambda c: (len(c["philly"]), c["purity"]), reverse=True)
        best = candidates[0]
        widest = len(best["philly"])
        plausible = [c for c in candidates if len(c["philly"]) >= 0.98 * widest]
        confidence = inspection.confidence_for_candidates(
            len({frozenset(c["philly"]) for c in plausible})
        )

        city_column = inspection.match_column(
            best["profile"], config.get("city_column_hints", ["city"])
        )
        state_column = inspection.match_column(
            best["profile"], config.get("state_column_hints", ["state"])
        )
        cities = self._column_values(best["profile"], city_column)
        states = self._column_values(best["profile"], state_column)
        other_cities = [c for c in cities if c.lower() not in expected_cities]
        other_states = [s for s in states if s.lower() not in expected_states]

        evidence = {
            "dataframe": inspection.describe_dataframe(best["profile"]),
            "philadelphia_zip_count": widest,
            "zip_sample": sorted(best["philly"])[:12],
            "non_philadelphia_zips": best["outside"],
            "city_values": cities[:10],
            "state_values": states[:10],
            "unexpected_cities": other_cities[:10],
            "unexpected_states": other_states[:10],
            "candidate_dataframes": [c["profile"].get("name") for c in plausible][:6],
            "note": "ZIP and row counts vary with the Zillow vintage and are not graded.",
        }

        problems = []
        purity_score = best["purity"]
        if best["purity"] < 0.999:
            problems.append(
                "the subset still contains ZIP codes outside Philadelphia "
                f"({', '.join(best['outside'][:4])})"
            )
        if other_cities:
            problems.append(f"rows from other cities remain: {', '.join(sorted(set(other_cities))[:4])}")
            purity_score = min(purity_score, 0.6)
        if other_states:
            problems.append(f"rows from other states remain: {', '.join(sorted(set(other_states))[:4])}")
            purity_score = min(purity_score, 0.6)

        if not problems:
            return self.result(
                item, item.points, STATUS_PASS, confidence,
                f"Philadelphia subset found ({widest} ZIP codes, all in Philadelphia, PA).",
                evidence,
            )
        score = item.points * purity_score
        return self.result(
            item, score, STATUS_PARTIAL if score > 0 else STATUS_FAIL, confidence,
            "The subset is not restricted to Philadelphia: " + "; ".join(problems) + ".",
            evidence,
        )

    # -----------------------------------------------------------------
    # 3. Melt into tidy format
    # -----------------------------------------------------------------
    def check_tidy_transformation(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        if not ctx.probe_ok:
            return self.no_probe_result(item, ctx)

        config = item.config
        required_name = str(config.get("required_value_column", "ZHVI"))
        alternatives = [a.lower() for a in config.get("value_column_alternatives", [])]
        tolerance = float(config.get("consistency_tolerance", 0.02))
        min_ratio = float(config.get("min_long_ratio", 4.0))

        candidates = []
        for profile in inspection.dataframes(ctx.probe):
            rows = profile.get("rows", 0)
            n_columns = max(profile.get("n_columns", 1), 1)
            if rows < 50 or rows / n_columns < min_ratio:
                continue
            id_column = inspection.match_column(profile, self.id_hints)
            date_column = inspection.has_datelike_column(profile, self.date_hints)
            value_column = self._value_column(profile, id_column, date_column, required_name,
                                              alternatives)
            if not (id_column and date_column and value_column):
                continue
            candidates.append(
                {
                    "profile": profile,
                    "id": id_column,
                    "date": date_column,
                    "value": value_column,
                    "rows": rows,
                }
            )

        if not candidates:
            return self.result(
                item, 0.0, STATUS_NOT_FOUND, 0.6,
                "No tidy dataframe (one row per ZIP code per date) was found, so the melt "
                "step could not be verified.",
                {"dataframes_inspected": len(inspection.dataframes(ctx.probe))},
            )

        # Grade the melt against the student's own grid, not an expected size.
        for candidate in candidates:
            candidate["consistency"] = self._melt_consistency(candidate)
        candidates.sort(
            key=lambda c: (c["consistency"]["ok"], c["rows"]), reverse=True
        )
        best = candidates[0]
        consistency = best["consistency"]

        # The Center City and remainder frames are also internally consistent, but
        # they are slices of the answer, not competing answers — only frames of
        # comparable size count towards ambiguity.
        consistent = [c for c in candidates if c["consistency"]["ok"]] or candidates
        widest = max(c["rows"] for c in consistent)
        plausible = [c for c in consistent if c["rows"] >= 0.98 * widest]
        confidence = inspection.confidence_for_candidates(
            len({c["rows"] for c in plausible})
        )

        value_name_ok = str(best["value"]).lower() == required_name.lower()
        evidence = {
            "dataframe": inspection.describe_dataframe(best["profile"]),
            "detected_roles": {
                "identifier": best["id"], "date": best["date"], "value": best["value"],
            },
            "rows": best["rows"],
            "unique_ids": consistency.get("unique_ids"),
            "unique_dates": consistency.get("unique_dates"),
            "expected_rows_from_this_students_data": consistency.get("expected_rows"),
            "value_column_named_correctly": value_name_ok,
            "note": (
                "Row counts are checked against this student's own ZIP x date grid, "
                "not against a fixed number."
            ),
        }

        problems = []
        score = float(item.points)
        if not value_name_ok:
            penalty = float(config.get("wrong_name_penalty_ratio", 0.25))
            score -= item.points * penalty
            problems.append(
                f"the value column is `{best['value']}`; the instructions ask for "
                f"`{required_name}`"
            )
        if consistency.get("checked") and not consistency["ok"]:
            score -= item.points * 0.4
            problems.append(
                f"the frame has {best['rows']} rows but this student's data implies "
                f"{consistency['expected_rows']} "
                f"({consistency['unique_ids']} ZIP codes x {consistency['unique_dates']} dates)"
            )

        if not problems:
            return self.result(
                item, item.points, STATUS_PASS, confidence,
                f"Data melted into tidy format: {best['rows']} rows keyed by "
                f"`{best['id']}` and `{best['date']}`, values in `{best['value']}`.",
                evidence,
            )
        status = STATUS_PARTIAL if score > 0 else STATUS_FAIL
        return self.result(item, score, status, confidence,
                           "Mostly correct, but " + "; ".join(problems) + ".", evidence)

    def _value_column(
        self,
        profile: dict[str, Any],
        id_column: str | None,
        date_column: str | None,
        required_name: str,
        alternatives: list[str],
    ) -> str | None:
        for column in profile.get("columns", []):
            if str(column).lower() == required_name.lower():
                return str(column)
        for column in profile.get("columns", []):
            if str(column).lower() in alternatives and column not in (id_column, date_column):
                return str(column)
        named = inspection.match_column(profile, self.value_hints)
        if named and named not in (id_column, date_column):
            return named
        for column in inspection.numeric_columns(profile):
            if column not in (id_column, date_column):
                return column
        return None

    @staticmethod
    def _melt_consistency(candidate: dict[str, Any]) -> dict[str, Any]:
        """Does row count equal (this student's ZIPs) x (this student's dates)?"""
        nunique = candidate["profile"].get("nunique") or {}
        unique_ids = nunique.get(candidate["id"])
        unique_dates = nunique.get(candidate["date"])
        if not unique_ids or not unique_dates:
            # Older sessions, or a column the probe could not count: don't guess.
            return {"checked": False, "ok": True, "unique_ids": unique_ids,
                    "unique_dates": unique_dates, "expected_rows": None}
        expected = unique_ids * unique_dates
        rows = candidate["rows"]
        error = abs(rows - expected) / max(expected, 1)
        return {
            "checked": True,
            "ok": error <= 0.02 or rows == expected,
            "unique_ids": unique_ids,
            "unique_dates": unique_dates,
            "expected_rows": expected,
            "relative_error": round(error, 4),
        }

    # -----------------------------------------------------------------
    # 4. Split Center City from the rest of Philadelphia
    # -----------------------------------------------------------------
    def check_center_city_split(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        if not ctx.probe_ok:
            return self.no_probe_result(item, ctx)

        config = item.config
        listed = normalize_zips(config.get("center_city_zips", []))
        if not listed:
            return self.check_unimplemented(ctx, item)

        philly = self._philadelphia_zips(ctx)
        if not philly:
            return self.result(
                item, 0.0, STATUS_NOT_FOUND, 0.6,
                "The Philadelphia data could not be located, so the Center City split "
                "could not be checked.",
                {"center_city_zips_from_template": sorted(listed)},
            )

        # Only ZIP codes this student actually has can appear in either frame.
        expected_center = listed & philly
        expected_rest = philly - listed

        # A frame holding the whole Philadelphia ZIP set is the un-split data, not
        # half of the split, so it cannot answer either side.
        frames = [f for f in self._zip_frames(ctx) if (f["zips"] & philly) != philly]
        floor = float(config.get("min_match_similarity", 0.25))
        center_match = self._best_zip_match(frames, expected_center, floor)
        rest_match = self._best_zip_match(frames, expected_rest, floor)

        evidence = {
            "center_city_zips_from_template": sorted(listed),
            "student_philadelphia_zips": sorted(philly),
            "expected_center_city_zips": sorted(expected_center),
            "expected_remaining_zip_count": len(expected_rest),
            "center_frame": center_match and {
                "name": center_match["profile"].get("name"),
                "zips": sorted(center_match["zips"]),
                "similarity": round(center_match["similarity"], 2),
            },
            "rest_frame": rest_match and {
                "name": rest_match["profile"].get("name"),
                "zip_count": len(rest_match["zips"]),
                "similarity": round(rest_match["similarity"], 2),
            },
            "note": "Both frames are compared with this student's own Philadelphia ZIP set.",
        }

        center_score = center_match["similarity"] if center_match else 0.0
        rest_score = rest_match["similarity"] if rest_match else 0.0
        if center_match and rest_match and center_match["profile"] is rest_match["profile"]:
            # One frame cannot be both halves of the split.
            rest_score = 0.0
            evidence["warning"] = "only one frame was found; the data was not split in two"

        score = item.points * (0.6 * center_score + 0.4 * rest_score)
        confidence = 0.98 if (center_match and rest_match) else 0.6

        if center_score >= 0.999 and rest_score >= 0.999:
            return self.result(
                item, item.points, STATUS_PASS, confidence,
                f"Data split correctly: {len(expected_center)} Center City ZIP codes and "
                f"{len(expected_rest)} elsewhere in Philadelphia.",
                evidence,
            )

        problems = []
        if not center_match or center_score < 0.999:
            missing = sorted(expected_center - (center_match["zips"] if center_match else set()))
            extra = sorted((center_match["zips"] if center_match else set()) - expected_center)
            detail = []
            if missing:
                detail.append(f"missing {', '.join(missing)}")
            if extra:
                detail.append(f"unexpected {', '.join(extra)}")
            problems.append(
                "the Center City frame " + ("was not found" if not center_match
                                            else "differs: " + "; ".join(detail))
            )
        if not rest_match or rest_score < 0.999:
            problems.append(
                "the frame for the rest of Philadelphia "
                + ("was not found" if not rest_match else "does not hold exactly the "
                   "remaining ZIP codes")
            )
        status = STATUS_PARTIAL if score > 0 else STATUS_FAIL
        sentence = "; ".join(problems)
        return self.result(item, score, status, confidence,
                           sentence[:1].upper() + sentence[1:] + ".", evidence)

    @staticmethod
    def _best_zip_match(
        frames: list[dict[str, Any]], target: set[str], floor: float = 0.25
    ) -> dict[str, Any] | None:
        """Best frame for a target ZIP set, or None when nothing plausible matches.

        A candidate must be mostly *inside* the target (precision), not merely
        overlap it — otherwise a frame holding all of Philadelphia would be
        reported as the "rest of the city" frame just because it contains those
        ZIP codes among many others.
        """
        if not target:
            return None
        best = None
        for frame in frames:
            zips = frame["zips"]
            if not zips:
                continue
            precision = len(zips & target) / len(zips)
            similarity = jaccard(zips, target)
            if precision < 0.8 or similarity < floor:
                continue
            if best is None or similarity > best["similarity"]:
                best = {**frame, "similarity": similarity, "precision": precision}
        return best

    # -----------------------------------------------------------------
    # 5. Percent increase function
    # -----------------------------------------------------------------
    def check_percent_increase_function(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        if not ctx.probe_ok:
            return self.no_probe_result(item, ctx)

        config = item.config
        entry = inspection.hidden_test(ctx.probe, item.id)
        rel_tol = float(config.get("rel_tol", 1e-3))
        abs_tol = float(config.get("abs_tol", 1e-3))
        start_date = str(config.get("start_date"))
        end_date = str(config.get("end_date"))
        cases = config.get("cases", [])

        if entry is None or not entry.get("found"):
            defined = ctx.analysis.function_names()
            return self.result(
                item, 0.0,
                STATUS_NOT_FOUND if not defined else STATUS_MANUAL_REVIEW,
                1.0 if not defined else 0.5,
                "No percent-increase function could be identified in the notebook."
                + (f" Functions defined: {', '.join(defined[:8])}." if defined else ""),
                {"functions_defined": defined,
                 "selector_candidates": (entry or {}).get("candidates", [])},
            )

        source = entry.get("source", "") or ""
        if self._is_unfilled_stub(source):
            return self.result(
                item, item.points * float(config.get("stub_credit_ratio", 0.0)),
                STATUS_FAIL, 1.0,
                "The `calculate_percent_increase` template was left unfilled, so it does "
                "not compute anything.",
                {"function_name": entry.get("function_name"), "function_source": source[:2000]},
            )

        results = []
        for case, call in zip(cases, entry.get("calls", [])):
            anchors = {str(date): float(value) for date, value in case.get("anchors", [])}
            expected = self._percent(anchors.get(start_date), anchors.get(end_date))
            ordered = case.get("anchors", [])
            first_last = self._percent(
                float(ordered[0][1]) if ordered else None,
                float(ordered[-1][1]) if ordered else None,
            )
            actual = call.get("value") if call.get("ok") else None
            numeric = as_float(actual)

            passed = call.get("ok") and is_close(numeric, expected, rel_tol, abs_tol)
            results.append(
                {
                    "label": case.get("label"),
                    "expected": expected,
                    "actual": actual,
                    "passed": bool(passed),
                    "fraction_form": bool(
                        numeric is not None and not passed
                        and is_close(numeric * 100, expected, 1e-2, 1e-2)
                    ),
                    "first_last": bool(
                        numeric is not None and not passed and first_last is not None
                        and is_close(numeric, first_last, 1e-2, 1e-2)
                    ),
                    "error": call.get("error"),
                    "schema_used": call.get("schema_used"),
                }
            )

        total = len(results) or 1
        passed = sum(1 for r in results if r["passed"])
        failed = [r for r in results if not r["passed"]]
        errored = [r for r in results if r.get("error")]

        evidence = {
            "function_name": entry.get("function_name"),
            "function_source": source[:2000],
            "tests_passed": passed,
            "tests_failed": total - passed,
            "cases": results,
            "input_schema": entry.get("schema_source"),
            "candidates": entry.get("candidates", []),
            "comparison_dates": [start_date, end_date],
        }

        if errored and passed == 0:
            return self.result(
                item, item.points * 0.25, STATUS_MANUAL_REVIEW, 0.6,
                "The function raised an error on every test input "
                f"({errored[0]['error']}). It may depend on names or columns that only "
                "exist in this student's notebook — worth a look.",
                evidence,
            )

        confidence = 0.75 if entry.get("ambiguous") else 1.0
        if failed and all(r["fraction_form"] for r in failed):
            score = item.points * float(config.get("fraction_form_credit_ratio", 0.6))
            feedback = (
                "The function returns a fraction (e.g. 0.5) where the assignment asks for "
                "a percent increase (50). The formula is right; the units are not."
            )
            status = STATUS_PARTIAL
        elif failed and all(r["first_last"] for r in failed):
            score = item.points * float(config.get("first_last_credit_ratio", 0.5))
            feedback = (
                "The function uses the first and last rows of the group rather than "
                f"{start_date} and {end_date} as the instructions specify."
            )
            status = STATUS_PARTIAL
        else:
            score = item.points * passed / total
            if passed == total:
                feedback = f"All {total} hidden tests passed."
                status = STATUS_PASS
            elif passed == 0:
                feedback = f"The function failed all {total} hidden tests."
                status = STATUS_FAIL
            else:
                feedback = f"{passed} of {total} hidden tests passed."
                status = STATUS_PARTIAL

        if entry.get("ambiguous"):
            feedback += (
                " Several functions matched the expected signature, so the graded one "
                "may not be the intended answer."
            )
        return self.result(item, score, status, confidence, feedback, evidence)

    @staticmethod
    def _percent(start: float | None, end: float | None) -> float | None:
        if start in (None, 0) or end is None:
            return None
        return (end - start) / start * 100.0

    @staticmethod
    def _is_unfilled_stub(source: str) -> bool:
        """True when the function body is only a docstring, comments or `pass`.

        Parsing beats searching for the template's "Fill in this part!" comment,
        which students often leave in place above a correct answer.
        """
        if not source.strip():
            return False
        try:
            tree = ast.parse(textwrap.dedent(source))
        except SyntaxError:
            return False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = list(node.body)
            first = body[0] if body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(getattr(first, 'value', None), ast.Constant)
                and isinstance(first.value.value, str)
            ):
                body = body[1:]  # drop the docstring
            remaining = [
                statement
                for statement in body
                if not isinstance(statement, ast.Pass)
                and not (
                    isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Constant)
                    and statement.value.value is Ellipsis
                )
            ]
            return not remaining
        return False

    # -----------------------------------------------------------------
    # 6. Compare Center City with the rest of the city
    # -----------------------------------------------------------------
    def check_donut_effect_comparison(
        self, ctx: GradingContext, item: RubricItem
    ) -> RubricItemResult:
        if not ctx.probe_ok:
            return self.no_probe_result(item, ctx)

        config = item.config
        low, high = config.get("plausible_range", [-100, 1000])
        center_hints = [h.lower() for h in config.get("center_hints", ["center"])]
        outside_hints = [h.lower() for h in config.get("outside_hints", ["outside", "non"])]

        candidates = self._percent_candidates(ctx, float(low), float(high))
        if not candidates:
            return self.result(
                item, 0.0, STATUS_NOT_FOUND, 0.6,
                "No average percent-increase values were found in the notebook's namespace, "
                "so the comparison could not be verified automatically.",
                {"note": "Values that are only printed, never assigned, cannot be inspected."},
            )

        center, outside = self._classify(candidates, center_hints, outside_hints)

        evidence = {
            "candidate_values": [
                {"name": c["name"], "value": round(c["value"], 2), "source": c["source"]}
                for c in candidates[:10]
            ],
            "center_city_value": center and round(center["value"], 2),
            "outside_value": outside and round(outside["value"], 2),
            "note": (
                "The values themselves are not graded — they depend on the vintage of the "
                "student's Zillow download. Only their presence and direction are checked."
            ),
        }

        if center is None or outside is None:
            return self.result(
                item, item.points * 0.5, STATUS_MANUAL_REVIEW, 0.5,
                f"{len(candidates)} plausible percent-increase value(s) were found, but the "
                "Center City and non-Center City results could not be told apart by name. "
                "Please confirm the comparison by hand.",
                evidence,
            )

        if not config.get("expect_outside_greater", True):
            return self.result(item, item.points, STATUS_PASS, 0.95,
                               "Both averages were computed and compared.", evidence)

        if outside["value"] > center["value"]:
            return self.result(
                item, item.points, STATUS_PASS, 0.95,
                "Both averages were computed, and appreciation outside Center City "
                f"({outside['value']:.1f}%) exceeds Center City ({center['value']:.1f}%) — "
                "the Donut Effect.",
                evidence,
            )
        return self.result(
            item, item.points * 0.6, STATUS_PARTIAL, 0.8,
            f"Both averages were computed, but Center City ({center['value']:.1f}%) is not "
            f"below the rest of the city ({outside['value']:.1f}%), which is the opposite of "
            "the expected Donut Effect. Check which frame each value came from.",
            evidence,
        )

    def _percent_candidates(
        self, ctx: GradingContext, low: float, high: float
    ) -> list[dict[str, Any]]:
        """Scalars and per-ZIP result series that look like percent changes."""
        out: list[dict[str, Any]] = []
        for entry in inspection.scalars(ctx.probe):
            value = as_float(entry.get("value"))
            if value is None or isinstance(entry.get("value"), bool):
                continue
            if low <= value <= high:
                out.append({"name": entry["name"], "value": value, "source": "variable"})
        for entry in (ctx.probe or {}).get("series", []) or []:
            summary = entry.get("numeric_summary") or {}
            mean = as_float(summary.get("mean"))
            if mean is None or not (low <= mean <= high):
                continue
            out.append(
                {"name": entry["name"], "value": mean,
                 "source": f"mean of series `{entry['name']}` ({summary.get('count')} ZIP codes)"}
            )
        return out

    @staticmethod
    def _classify(
        candidates: list[dict[str, Any]],
        center_hints: list[str],
        outside_hints: list[str],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Assign values to the two groups by variable name.

        Scoring both sides and comparing them, rather than excluding one side's
        words outright, is what lets `non_cc_avg` land on the "outside" side even
        though its name also contains "cc".
        """
        center = outside = None
        for candidate in candidates:
            name = candidate["name"].lower()
            center_score = sum(len(h) for h in center_hints if h in name)
            outside_score = sum(len(h) for h in outside_hints if h in name)
            if outside_score > center_score:
                margin = outside_score - center_score
                if outside is None or margin > outside["_margin"]:
                    outside = {**candidate, "_margin": margin}
            elif center_score > outside_score:
                margin = center_score - outside_score
                if center is None or margin > center["_margin"]:
                    center = {**candidate, "_margin": margin}
        return center, outside
