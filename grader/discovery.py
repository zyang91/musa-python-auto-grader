"""Find student submissions in a folder or a Canvas export ZIP (design.md §16-17).

Notebook filenames are not standardised, so discovery scores the candidates and
refuses to guess when two files look equally plausible — an ambiguous submission
is flagged for review rather than graded against the wrong notebook.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .utils import slugify

NOTEBOOK_SUFFIX = ".ipynb"
DATA_SUFFIXES = {".csv", ".xlsx", ".xls", ".json", ".geojson", ".shp", ".dbf",
                 ".shx", ".prj", ".txt", ".parquet", ".gpkg", ".zip"}
SKIP_DIRS = {".ipynb_checkpoints", "__MACOSX", ".git", "__pycache__", ".ipynb_checkpoint"}

# Canvas flattens submissions to e.g. "doejane_12345_67890_assignment1-2.ipynb",
# sometimes with a LATE marker.
CANVAS_RE = re.compile(
    r"^(?P<name>[a-z\-']+?)(?P<late>_late)?_(?P<sub>\d+)_(?P<attempt>\d+)_(?P<file>.+)$",
    re.IGNORECASE,
)

REASON_MULTIPLE_NOTEBOOKS = "multiple_notebooks"
REASON_NO_NOTEBOOK = "no_notebook"


@dataclass
class SubmissionCandidate:
    """One student's submission as found on disk."""

    student_id: str
    display_name: str = ""
    source_dir: Path | None = None
    notebook_path: Path | None = None
    all_notebooks: list[Path] = field(default_factory=list)
    data_files: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    late: bool = False

    @property
    def ok(self) -> bool:
        return self.notebook_path is not None

    @property
    def needs_review(self) -> bool:
        return bool(self.review_reasons)

    def summary(self) -> dict[str, Any]:
        return {
            "student_id": self.student_id,
            "display_name": self.display_name,
            "notebook": self.notebook_path.name if self.notebook_path else None,
            "notebook_count": len(self.all_notebooks),
            "data_files": len(self.data_files),
            "warnings": list(self.warnings),
            "review_reasons": list(self.review_reasons),
            "late": self.late,
        }


# ---------------------------------------------------------------------------
# Notebook ranking
# ---------------------------------------------------------------------------

def _notebook_score(path: Path, hints: Iterable[str], ignore: Iterable[str]) -> float:
    name = path.name.lower()
    score = 0.0
    for hint in hints:
        if hint and hint.lower() in name:
            score += 3.0
    for pattern in ignore:
        if pattern and pattern.lower() in name:
            score -= 5.0
    # Prefer files that sit near the top of the submission.
    score -= 0.5 * max(len(path.parts) - 1, 0)
    try:
        # A larger notebook is more likely to be the real submission than a stub.
        score += min(path.stat().st_size / 200_000, 2.0)
    except OSError:  # pragma: no cover - defensive
        pass
    return score


def choose_notebook(
    notebooks: list[Path],
    hints: Iterable[str] = (),
    ignore: Iterable[str] = (),
    root: Path | None = None,
) -> tuple[Path | None, list[str]]:
    """Return the most plausible notebook and any review reasons.

    Ties are not broken: design.md §17 says not to guess aggressively.
    """
    real = [n for n in notebooks if not _is_ignored(n)]
    if not real:
        return None, [REASON_NO_NOTEBOOK]
    if len(real) == 1:
        return real[0], []

    hints, ignore = list(hints), list(ignore)
    scored = sorted(
        ((_notebook_score(n.relative_to(root) if root else n, hints, ignore), n) for n in real),
        key=lambda pair: pair[0],
        reverse=True,
    )
    best, runner_up = scored[0], scored[1]
    if best[0] - runner_up[0] < 1.0:
        return best[1], [REASON_MULTIPLE_NOTEBOOKS]
    return best[1], []


def _is_ignored(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def find_notebooks(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob(f"*{NOTEBOOK_SUFFIX}") if not _is_ignored(p))


def find_data_files(directory: Path, limit: int = 200) -> list[Path]:
    files = [
        p
        for p in sorted(directory.rglob("*"))
        if p.is_file() and p.suffix.lower() in DATA_SUFFIXES and not _is_ignored(p)
    ]
    return files[:limit]


# ---------------------------------------------------------------------------
# Canvas ZIP handling
# ---------------------------------------------------------------------------

def extract_zip(zip_path: str | Path, dest: str | Path) -> Path:
    """Extract a Canvas export, refusing path traversal entries."""
    zip_path, dest = Path(zip_path), Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            name = member.filename
            if name.startswith("/") or ".." in Path(name).parts:
                continue
            if any(part in SKIP_DIRS for part in Path(name).parts):
                continue
            archive.extract(member, dest)
    return dest


def parse_canvas_filename(filename: str) -> tuple[str, str, bool]:
    """Return (student_id, display_name, late) for a flat Canvas filename."""
    match = CANVAS_RE.match(filename)
    if not match:
        stem = Path(filename).stem
        return slugify(stem), stem, False
    name = match.group("name")
    return slugify(name), name, bool(match.group("late"))


# ---------------------------------------------------------------------------
# Discovery entry points
# ---------------------------------------------------------------------------

def discover_submissions(
    root: str | Path,
    notebook_hints: Iterable[str] = (),
    ignore_patterns: Iterable[str] = (),
) -> list[SubmissionCandidate]:
    """Discover submissions under ``root``, handling both supported layouts."""
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(f"Submissions folder not found: {root}")

    root = _unwrap_single_directory(root)
    student_dirs = [
        d for d in sorted(root.iterdir()) if d.is_dir() and d.name not in SKIP_DIRS
    ]
    loose_notebooks = [
        p for p in sorted(root.glob(f"*{NOTEBOOK_SUFFIX}")) if not _is_ignored(p)
    ]

    candidates: list[SubmissionCandidate] = []
    if student_dirs:
        for directory in student_dirs:
            candidates.append(
                _candidate_from_dir(directory, notebook_hints, ignore_patterns)
            )
    if loose_notebooks:
        candidates.extend(
            _candidates_from_flat_files(loose_notebooks, root)
        )

    return _deduplicate(candidates)


def _unwrap_single_directory(root: Path) -> Path:
    """Step into a ZIP's wrapper folder — but never into a single student's folder.

    A wrapper looks like a container: it holds submissions but no work of its
    own. A lone student folder holds notebooks directly, and stepping into it
    would turn that student's files into separate "students".
    """
    for _ in range(3):
        entries = [e for e in root.iterdir() if e.name not in SKIP_DIRS]
        subdirs = [e for e in entries if e.is_dir()]
        files = [e for e in entries if e.is_file()]
        if len(subdirs) != 1 or any(f.suffix == NOTEBOOK_SUFFIX for f in files):
            break
        inner = subdirs[0]
        if not find_notebooks(inner):
            break  # nothing to gain; keep the folder as the (empty) submission
        top_level = [p for p in inner.glob(f"*{NOTEBOOK_SUFFIX}") if not _is_ignored(p)]
        canvas_named = [p for p in top_level if CANVAS_RE.match(p.name)]
        # No notebooks at its top level -> a container of student folders.
        # Several Canvas-named notebooks -> a container of flat submissions.
        if top_level and len(canvas_named) < 2:
            break
        root = inner
    return root


def _candidate_from_dir(
    directory: Path, hints: Iterable[str], ignore: Iterable[str]
) -> SubmissionCandidate:
    notebooks = find_notebooks(directory)
    chosen, reasons = choose_notebook(notebooks, hints, ignore, root=directory)
    student_id = slugify(directory.name)
    candidate = SubmissionCandidate(
        student_id=student_id,
        display_name=directory.name,
        source_dir=directory,
        notebook_path=chosen,
        all_notebooks=notebooks,
        data_files=find_data_files(directory),
        review_reasons=list(reasons),
    )
    if REASON_MULTIPLE_NOTEBOOKS in reasons:
        candidate.warnings.append(
            f"{len(notebooks)} notebooks found — grading {chosen.name if chosen else '?'}"
        )
    if REASON_NO_NOTEBOOK in reasons:
        candidate.warnings.append("no .ipynb file found in this folder")
    return candidate


def _candidates_from_flat_files(
    notebooks: list[Path], root: Path
) -> list[SubmissionCandidate]:
    """Group flat Canvas-style files by the student encoded in the filename."""
    grouped: dict[str, list[Path]] = {}
    names: dict[str, str] = {}
    late: dict[str, bool] = {}
    for path in notebooks:
        student_id, display, is_late = parse_canvas_filename(path.name)
        grouped.setdefault(student_id, []).append(path)
        names.setdefault(student_id, display)
        late[student_id] = late.get(student_id, False) or is_late

    shared_data = find_data_files(root)
    out: list[SubmissionCandidate] = []
    for student_id, paths in grouped.items():
        reasons: list[str] = []
        warnings: list[str] = []
        if len(paths) > 1:
            # Canvas appends "-1", "-2" for resubmissions; the highest wins.
            paths = sorted(paths, key=lambda p: (p.stat().st_mtime, p.name))
            reasons.append(REASON_MULTIPLE_NOTEBOOKS)
            warnings.append(f"{len(paths)} notebooks submitted — grading {paths[-1].name}")
        out.append(
            SubmissionCandidate(
                student_id=student_id,
                display_name=names[student_id],
                source_dir=root,
                notebook_path=paths[-1],
                all_notebooks=paths,
                data_files=shared_data,
                warnings=warnings,
                review_reasons=reasons,
                late=late[student_id],
            )
        )
    return out


def _deduplicate(candidates: list[SubmissionCandidate]) -> list[SubmissionCandidate]:
    seen: dict[str, SubmissionCandidate] = {}
    for candidate in candidates:
        key = candidate.student_id
        if key in seen:
            key = f"{key}_{len(seen)}"
            candidate.student_id = key
        seen[key] = candidate
    return sorted(seen.values(), key=lambda c: c.student_id)


def prepare_workdir(candidate: SubmissionCandidate, workdir: str | Path) -> Path:
    """Copy one submission into an isolated working directory (design.md §17).

    The notebook always lands at ``<workdir>/notebook.ipynb`` so the executor does
    not have to care about student filenames; sibling data files keep their
    relative layout so relative paths in student code still resolve.
    """
    workdir = Path(workdir)
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    if candidate.notebook_path is None:
        return workdir

    source_root = candidate.source_dir or candidate.notebook_path.parent
    notebook_parent = candidate.notebook_path.parent

    # Copy everything that lives beside the notebook, minus other notebooks.
    for path in sorted(notebook_parent.rglob("*")):
        if _is_ignored(path) or not path.is_file():
            continue
        if path.suffix == NOTEBOOK_SUFFIX:
            continue
        relative = path.relative_to(notebook_parent)
        target = workdir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)

    # Canvas flat exports keep shared data at the root instead.
    if notebook_parent != source_root:
        for path in candidate.data_files:
            if not path.is_file() or _is_ignored(path):
                continue
            target = workdir / path.name
            if not target.exists():
                shutil.copy2(path, target)

    shutil.copy2(candidate.notebook_path, workdir / "notebook.ipynb")
    return workdir
