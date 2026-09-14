"""Find student submissions in a folder or a Canvas export ZIP (design.md §16-17).

Notebook filenames are not standardised, so discovery scores the candidates and
refuses to guess when two files look equally plausible — an ambiguous submission
is flagged for review rather than graded against the wrong notebook.
"""

from __future__ import annotations

import difflib
import hashlib
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
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
    data_placement: dict[str, Any] = field(default_factory=dict)
    run_subdir: str = ""

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
    """Discover submissions under ``root``, handling both supported layouts.

    Nothing is ever written into ``root``: flat Canvas files are regrouped, and
    archives expanded, in a staging area under the system temp directory.
    """
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(f"Submissions folder not found: {root}")

    root = _unwrap_single_directory(root)
    student_dirs = [
        d for d in sorted(root.iterdir())
        if d.is_dir() and d.name not in SKIP_DIRS and not d.name.startswith(".")
    ]
    loose_files = [
        p for p in sorted(root.iterdir())
        if p.is_file() and not _is_ignored(p) and not p.name.startswith(".")
    ]

    candidates: list[SubmissionCandidate] = []
    for directory in student_dirs:
        candidates.append(
            _candidate_from_dir(
                _expand_archives(directory, root), notebook_hints, ignore_patterns,
                display_name=directory.name,
            )
        )
    if any(p.suffix == NOTEBOOK_SUFFIX or p.suffix.lower() == ".zip" for p in loose_files):
        candidates.extend(
            _candidates_from_flat_files(loose_files, root, notebook_hints, ignore_patterns)
        )

    return _deduplicate(candidates)


def _staging_root(root: Path) -> Path:
    """Per-source scratch area that lives outside the submissions folder."""
    digest = hashlib.sha1(str(root.resolve()).encode("utf-8")).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / "musa_grader_staging" / digest


def _extract_archive(archive: Path, dest: Path) -> bool:
    """Extract a student's own ZIP; True when it held at least one notebook."""
    try:
        extract_zip(archive, dest)
    except (zipfile.BadZipFile, OSError):
        return False
    return bool(find_notebooks(dest))


def _expand_archives(directory: Path, root: Path) -> Path:
    """A student folder whose work is inside a ZIP becomes a staged, expanded copy."""
    archives = [p for p in sorted(directory.rglob("*.zip")) if not _is_ignored(p)]
    if not archives or find_notebooks(directory):
        return directory
    stage = _staging_root(root) / "folders" / slugify(directory.name)
    if stage.exists():
        shutil.rmtree(stage)
    for path in sorted(directory.rglob("*")):
        if path.is_file() and not _is_ignored(path) and path.suffix.lower() != ".zip":
            _link_or_copy(path, stage / path.relative_to(directory))
    for archive in archives:
        _extract_archive(archive, stage / archive.stem)
    return stage


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
    directory: Path,
    hints: Iterable[str],
    ignore: Iterable[str],
    display_name: str | None = None,
    student_id: str | None = None,
) -> SubmissionCandidate:
    notebooks = find_notebooks(directory)
    chosen, reasons = choose_notebook(notebooks, hints, ignore, root=directory)
    name = display_name or directory.name
    candidate = SubmissionCandidate(
        student_id=student_id or slugify(name),
        display_name=name,
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
        candidate.warnings.append("no .ipynb file found in this submission")
    return candidate


def _candidates_from_flat_files(
    files: list[Path],
    root: Path,
    hints: Iterable[str] = (),
    ignore: Iterable[str] = (),
) -> list[SubmissionCandidate]:
    """Regroup a flat Canvas export into one staged folder per student.

    Canvas flattens every file a student uploads to
    ``<name>_<ids>_<original filename>``. Each file therefore belongs to exactly
    the student its prefix names — a data file one student uploaded must never
    end up in another student's run — and gets its original name back, which is
    what that student's code refers to. A ZIP a student uploaded is expanded
    into their folder, so work handed in as an archive is graded rather than
    silently skipped.
    """
    hints, ignore = list(hints), list(ignore)
    grouped: dict[str, list[tuple[Path, str]]] = {}
    names: dict[str, str] = {}
    late: dict[str, bool] = {}
    for path in files:
        match = CANVAS_RE.match(path.name)
        if match:
            student_id, display, is_late = parse_canvas_filename(path.name)
            original = match.group("file")
        elif path.suffix == NOTEBOOK_SUFFIX:
            student_id, display, is_late = slugify(path.stem), path.stem, False
            original = path.name
        else:
            continue  # not attributable to anyone: shared clutter, ignored
        grouped.setdefault(student_id, []).append((path, original))
        names.setdefault(student_id, display)
        late[student_id] = late.get(student_id, False) or is_late

    stage_root = _staging_root(root) / "flat"
    out: list[SubmissionCandidate] = []
    for student_id, entries in grouped.items():
        stage = stage_root / student_id
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True)

        notebooks = [(p, o) for p, o in entries if p.suffix == NOTEBOOK_SUFFIX]
        # Canvas keeps resubmissions side by side; the newest is the submission.
        notebooks.sort(key=lambda pair: (pair[0].stat().st_mtime, pair[0].name))
        for path, original in entries:
            if path.suffix.lower() == ".zip":
                _extract_archive(path, stage / Path(original).stem)
            elif path.suffix != NOTEBOOK_SUFFIX:
                _link_or_copy(path, stage / original)
        for index, (path, original) in enumerate(notebooks):
            target = stage / original
            if target.exists():  # two uploads with the same original name
                target = stage / f"{Path(original).stem}-{index}{NOTEBOOK_SUFFIX}"
            _link_or_copy(path, target)

        candidate = _candidate_from_dir(
            stage, hints, ignore, display_name=names[student_id], student_id=student_id
        )
        candidate.late = late[student_id]
        if len(notebooks) > 1:
            newest = stage / notebooks[-1][1]
            if newest.exists():
                candidate.notebook_path = newest
        if any(p.suffix.lower() == ".zip" for p, _ in entries):
            candidate.warnings.append("submitted as a ZIP archive — expanded for grading")
        out.append(candidate)
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


def _link_or_copy(source: Path, target: Path) -> str:
    """Hard-link the file if possible, else copy it.

    The ZHVI extract is well over 100 MB; hard-linking it into fifty working
    directories costs nothing, while copying it would cost gigabytes. A hard link
    is a real directory entry, so it is still visible inside the grading
    container's bind mount.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return "already present"
    try:
        os.link(source, target)
        return "linked"
    except OSError:
        # Different filesystem, or a filesystem without hard links.
        shutil.copy2(source, target)
        return "copied"


def _is_safe_relative_path(text: str) -> bool:
    if not text or text.startswith(("/", "~", "http://", "https://")):
        return False
    if re.match(r"^[A-Za-z]:[\\/]", text):  # Windows absolute path
        return False
    return len(PurePosixPath(text.replace("\\", "/")).parts) <= 8


def _leading_parent_count(text: str) -> int:
    """How many directories a relative path climbs before descending."""
    count = 0
    for part in PurePosixPath(text.replace("\\", "/")).parts:
        if part == "..":
            count += 1
        elif part not in (".", ""):
            break
    return count


def _inside(base: Path, relative: str, start: Path) -> Path | None:
    """Resolve ``relative`` from ``start``; None if it escapes ``base``."""
    target = Path(os.path.normpath(start / relative.replace("\\", "/")))
    base = Path(os.path.normpath(base))
    try:
        target.relative_to(base)
    except ValueError:
        return None
    return target


def _best_source(sources: list[Path], target_name: str) -> Path | None:
    """Pick which supplied file belongs at a path the notebook asked for."""
    suffix = PurePosixPath(target_name).suffix.lower()
    same_suffix = [s for s in sources if s.suffix.lower() == suffix] or sources
    if len(same_suffix) == 1:
        return same_suffix[0]
    scored = sorted(
        same_suffix,
        key=lambda s: difflib.SequenceMatcher(
            None, s.name.lower(), PurePosixPath(target_name).name.lower()
        ).ratio(),
        reverse=True,
    )
    return scored[0] if scored else None


def place_shared_data(
    workdir: str | Path,
    shared_files: Iterable[str | Path],
    referenced_paths: Iterable[str] = (),
    fallback_dirs: Iterable[str] = ("data", ""),
    max_placements: int = 12,
    run_dir: str | Path | None = None,
    prefer_student_files: bool = False,
) -> dict[str, Any]:
    """Put instructor-supplied data where a notebook expects to find it.

    Students submit a notebook and nothing else, so the data has to come from the
    grader. Rather than dictating one filename, this puts the supplied file at
    every relative path the notebook actually passes to a ``read_*`` call, plus
    the conventional ``data/<name>`` and ``<name>`` locations. Paths are resolved
    from the directory the notebook runs in, so ``../data/x.csv`` works too, as
    long as it stays inside the working directory.

    If a student did hand in a data file at the same path, the uploaded file
    replaces it in the working copy unless ``prefer_student_files`` is set, so the
    whole class is graded on the same data. The student's original is untouched.
    """
    workdir = Path(workdir)
    start = Path(run_dir) if run_dir else workdir
    sources = [Path(f) for f in shared_files]
    missing = [str(s) for s in sources if not s.is_file()]
    sources = [s for s in sources if s.is_file()]

    report: dict[str, Any] = {
        "supplied": [str(s) for s in sources],
        "missing_sources": missing,
        "placed": [],
        "skipped": [],
    }
    if not sources:
        return report

    targets: list[tuple[str, Path]] = []
    for reference in referenced_paths:
        reference = str(reference)
        if not _is_safe_relative_path(reference) or _inside(workdir, reference, start) is None:
            report["skipped"].append(reference)
            continue
        source = _best_source(sources, reference)
        if source is not None:
            targets.append((reference.replace("\\", "/"), source))

    # Conventional locations, so a notebook that builds its path dynamically
    # (or that we could not parse) still finds the file.
    for source in sources:
        for directory in fallback_dirs:
            relative = f"{directory}/{source.name}" if directory else source.name
            targets.append((relative, source))

    # The student's own data files, by name. Canvas flattens `data/x.csv` to a
    # bare `x.csv`, so a file the notebook reads from `data/` may be sitting at
    # the root of the submission; matching by name finds it wherever it landed.
    own_files: dict[str, Path] = {}
    if prefer_student_files:
        for path in sorted(workdir.rglob("*")):
            if path.is_file() and not path.name.startswith(("_musa", "notebook.ipynb")):
                own_files.setdefault(path.name.lower(), path)

    seen: set[Path] = set()
    for relative, source in targets:
        target = _inside(workdir, relative, start)
        if target is None or target in seen or len(report["placed"]) >= max_placements:
            continue
        seen.add(target)
        own = own_files.get(target.name.lower())
        try:
            if own is not None and own != target and not target.exists():
                _link_or_copy(own, target)
                report["placed"].append(
                    {"path": relative, "source": own.name, "action": "student file linked"}
                )
                continue
            if target.exists():
                if prefer_student_files:
                    report["placed"].append(
                        {"path": relative, "source": target.name, "action": "student file kept"}
                    )
                    continue
                target.unlink()  # the working copy only; the submission is untouched
                action = "replaced student file"
                _link_or_copy(source, target)
            else:
                action = _link_or_copy(source, target)
        except OSError as exc:  # pragma: no cover - defensive
            report["skipped"].append(f"{relative}: {exc}")
            continue
        report["placed"].append({"path": relative, "source": source.name, "action": action})
    return report


def prepare_workdir(
    candidate: SubmissionCandidate,
    workdir: str | Path,
    shared_data: Iterable[str | Path] = (),
    referenced_paths: Iterable[str] = (),
    fallback_dirs: Iterable[str] = ("data", ""),
    prefer_student_files: bool = False,
) -> Path:
    """Copy one submission into an isolated working directory (design.md §17).

    The submission keeps its own layout, and the notebook runs from the folder it
    was submitted in, so ``../data/x.csv`` from ``assignments/hw1.ipynb`` means
    what it meant on the student's machine. When the notebook climbs higher than
    its submission is deep (a lone notebook reading ``../data``), the tree is
    nested one level further down so that path still lands inside the working
    directory. The notebook is renamed ``notebook.ipynb``; the run directory is
    recorded on ``candidate.run_subdir`` and returned.
    """
    workdir = Path(workdir)
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    candidate.run_subdir = ""

    if candidate.notebook_path is None:
        return workdir

    notebook = candidate.notebook_path
    source_root = candidate.source_dir or notebook.parent
    try:
        notebook_dir = notebook.parent.relative_to(source_root)
    except ValueError:
        source_root, notebook_dir = notebook.parent, Path("")

    references = list(referenced_paths)
    climb = max((_leading_parent_count(r) for r in references), default=0)
    extra = max(0, min(climb, 4) - len(notebook_dir.parts))
    tree_root = workdir.joinpath(*(["_up"] * extra)) if extra else workdir
    run_dir = tree_root / notebook_dir

    for path in sorted(source_root.rglob("*")):
        if _is_ignored(path) or not path.is_file() or path.suffix == NOTEBOOK_SUFFIX:
            continue
        _link_or_copy(path, tree_root / path.relative_to(source_root))

    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(notebook, run_dir / "notebook.ipynb")
    candidate.run_subdir = run_dir.relative_to(workdir).as_posix()
    if candidate.run_subdir == ".":
        candidate.run_subdir = ""

    shared = list(shared_data)
    if shared:
        candidate.data_placement = place_shared_data(
            workdir, shared, references, fallback_dirs,
            run_dir=run_dir, prefer_student_files=prefer_student_files,
        )
    return run_dir
