"""Host-side reasoning over the probe payload.

Students do not use the solution's variable names, so grading works by finding
objects that *look like* the expected result and reporting how sure we are
(design.md §21 and §25).
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from .utils import normalize_zips

# Confidence ladder from design.md §25.
CONFIDENCE_UNIQUE = 0.98
CONFIDENCE_TWO = 0.75
CONFIDENCE_MANY = 0.40
CONFIDENCE_NONE = 0.0


def confidence_for_candidates(count: int) -> float:
    if count <= 0:
        return CONFIDENCE_NONE
    if count == 1:
        return CONFIDENCE_UNIQUE
    if count == 2:
        return CONFIDENCE_TWO
    return CONFIDENCE_MANY


def dataframes(probe: dict[str, Any] | None) -> list[dict[str, Any]]:
    return list((probe or {}).get("dataframes", []) or [])


def scalars(probe: dict[str, Any] | None) -> list[dict[str, Any]]:
    return list((probe or {}).get("scalars", []) or [])


def collections(probe: dict[str, Any] | None) -> list[dict[str, Any]]:
    return list((probe or {}).get("collections", []) or [])


def hidden_test(probe: dict[str, Any] | None, test_id: str) -> dict[str, Any] | None:
    for entry in (probe or {}).get("hidden_tests", []) or []:
        if entry.get("id") == test_id:
            return entry
    return None


# ---------------------------------------------------------------------------
# Column matching
# ---------------------------------------------------------------------------

def match_column(profile: dict[str, Any], hints: Iterable[str]) -> str | None:
    """Best column in ``profile`` matching any of ``hints`` (substring, case-insensitive)."""
    hints = [h.lower() for h in hints]
    best: tuple[float, str] | None = None
    for column in profile.get("columns", []):
        lowered = str(column).lower()
        score = 0.0
        for hint in hints:
            if lowered == hint:
                score = max(score, 3.0)
            elif hint in lowered:
                score = max(score, 2.0)
        if score and (best is None or score > best[0]):
            best = (score, str(column))
    return best[1] if best else None


def has_datelike_column(profile: dict[str, Any], hints: Iterable[str]) -> str | None:
    """A date role can be satisfied by a column name hint or a datetime dtype."""
    named = match_column(profile, hints)
    if named:
        return named
    for column, dtype in (profile.get("dtypes") or {}).items():
        if "datetime" in str(dtype) or "period" in str(dtype):
            return str(column)
    # A melt of date-named columns leaves the dates as values, not a dtype.
    for column, values in (profile.get("value_samples") or {}).items():
        sample = [str(v) for v in values[:5]]
        if sample and all(len(s) >= 6 and s[:4].isdigit() for s in sample):
            return str(column)
    return None


def numeric_columns(profile: dict[str, Any]) -> list[str]:
    return list((profile.get("numeric_summary") or {}).keys())


# ---------------------------------------------------------------------------
# ZIP extraction
# ---------------------------------------------------------------------------

def zips_in_profile(profile: dict[str, Any], id_hints: Iterable[str] = ()) -> set[str]:
    """All ZIP-looking values visible in a dataframe profile."""
    found: set[str] = set()
    columns = list(profile.get("id_columns") or [])
    hinted = match_column(profile, id_hints) if id_hints else None
    if hinted and hinted not in columns:
        columns.append(hinted)
    samples = profile.get("value_samples") or {}
    for column in columns:
        if column in samples:
            found |= normalize_zips(samples[column])
    if not found:
        for values in samples.values():
            candidate = normalize_zips(values)
            # Only accept a column that is overwhelmingly ZIP-like.
            if candidate and len(candidate) >= max(1, int(0.8 * len(values))):
                found |= candidate
    return found


def zips_in_collection(entry: dict[str, Any]) -> set[str]:
    return normalize_zips(entry.get("values", []) or [])


# ---------------------------------------------------------------------------
# Candidate search
# ---------------------------------------------------------------------------

def find_dataframe_candidates(
    probe: dict[str, Any] | None,
    predicate: Callable[[dict[str, Any]], bool],
    score: Callable[[dict[str, Any]], float] | None = None,
) -> list[dict[str, Any]]:
    """Return profiles satisfying ``predicate``, best first.

    This is the generic form of design.md §21's ``find_dataframe_with_columns``:
    matching may use columns, row counts, value ranges or expected geography.
    """
    matches = [p for p in dataframes(probe) if _safe_predicate(predicate, p)]
    if score is not None:
        matches.sort(key=lambda p: _safe_score(score, p), reverse=True)
    return matches


def _safe_predicate(predicate: Callable[[dict[str, Any]], bool], profile: dict[str, Any]) -> bool:
    try:
        return bool(predicate(profile))
    except Exception:
        return False


def _safe_score(score: Callable[[dict[str, Any]], float], profile: dict[str, Any]) -> float:
    try:
        return float(score(profile))
    except Exception:
        return 0.0


def find_scalar_close_to(
    probe: dict[str, Any] | None, expected: float, tolerance: float
) -> list[dict[str, Any]]:
    """Scalars in the namespace within ``tolerance`` of the expected answer."""
    out = []
    for entry in scalars(probe):
        value = entry.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if abs(float(value) - expected) <= tolerance:
            out.append(entry)
    return out


def describe_dataframe(profile: dict[str, Any], max_columns: int = 12) -> dict[str, Any]:
    """Compact, TA-readable description used as rubric evidence (design.md §12)."""
    columns = profile.get("columns", [])
    return {
        "name": profile.get("name"),
        "rows": profile.get("rows"),
        "columns": columns[:max_columns] + (["..."] if len(columns) > max_columns else []),
        "n_columns": profile.get("n_columns"),
        "head": (profile.get("head") or [])[:3],
    }
