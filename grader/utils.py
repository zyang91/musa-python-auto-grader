"""Small shared helpers for the grading engine."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ZIP_RE = re.compile(r"^\d{5}$")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(value: str) -> str:
    """Filesystem-safe identifier."""
    value = re.sub(r"[^\w\-. ]+", "_", str(value)).strip().replace(" ", "_")
    return re.sub(r"_+", "_", value) or "unknown"


def json_default(obj: Any) -> Any:
    """Best-effort JSON encoder for numpy / pandas / arbitrary objects."""
    for attr in ("isoformat",):
        if hasattr(obj, attr):
            try:
                return getattr(obj, attr)()
            except Exception:  # pragma: no cover - defensive
                pass
    if hasattr(obj, "item"):
        try:
            return obj.item()
        except Exception:  # pragma: no cover - defensive
            pass
    if hasattr(obj, "tolist"):
        try:
            return obj.tolist()
        except Exception:  # pragma: no cover - defensive
            pass
    return repr(obj)


def dump_json(path: Path, payload: Any, indent: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=indent, default=json_default), encoding="utf-8"
    )


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def is_close(actual: Any, expected: Any, rel_tol: float = 1e-4, abs_tol: float = 1e-4) -> bool:
    try:
        a = float(actual)
        e = float(expected)
    except (TypeError, ValueError):
        return False
    if math.isnan(a) or math.isnan(e):
        return False
    return math.isclose(a, e, rel_tol=rel_tol, abs_tol=abs_tol)


def as_float(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def normalize_zips(values: Iterable[Any]) -> set[str]:
    """Coerce mixed zip representations (int, float, str, padded) to 5-char strings."""
    out: set[str] = set()
    for value in values:
        if value is None:
            continue
        if isinstance(value, float):
            if math.isnan(value):
                continue
            value = int(value)
        text = str(value).strip()
        if text.endswith(".0"):
            text = text[:-2]
        text = text.split("-")[0].strip()
        if text.isdigit():
            text = text.zfill(5)
        if ZIP_RE.match(text):
            out.add(text)
    return out


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def truncate(text: str, limit: int = 4000) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, {len(text) - limit} more characters]"


def pluralize(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"
