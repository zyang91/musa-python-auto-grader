"""Static analysis of a student notebook (design.md §23, structural grading).

Everything here works without executing anything, so it still produces evidence
when a notebook fails to run.
"""

from __future__ import annotations

import ast
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import nbformat

# /Users/..., C:\Users\..., ~/Desktop/... inside a string literal.
ABSOLUTE_PATH_RE = re.compile(
    r"""(?P<quote>['"])(?P<path>(?:[A-Za-z]:[\\/]|/(?:Users|home|mnt|Volumes|var|tmp)/|~[\\/])[^'"]{2,200})(?P=quote)"""
)
# Any string literal that looks like a data file the notebook wants to open.
DATA_SUFFIXES = (
    ".csv", ".tsv", ".json", ".geojson", ".xlsx", ".xls", ".parquet",
    ".shp", ".gpkg", ".tif", ".txt", ".zip", ".gz",
)
READ_FUNCS = {
    "read_csv", "read_excel", "read_json", "read_parquet", "read_file",
    "read_table", "read_html", "read_feather", "read_stata",
}
PLOT_HINTS = (
    "plt.", "sns.", ".plot(", ".plot.", "plotly", "altair", "alt.Chart",
    "figure(", "subplots(", "hvplot",
)


@dataclass
class NotebookAnalysis:
    """Static facts about a notebook."""

    path: str
    valid: bool = True
    parse_error: str | None = None
    n_cells: int = 0
    n_code_cells: int = 0
    n_markdown_cells: int = 0
    code_source: str = ""
    code_cells: list[str] = field(default_factory=list)
    markdown_cells: list[str] = field(default_factory=list)
    imports: set[str] = field(default_factory=set)
    functions: list[dict[str, Any]] = field(default_factory=list)
    absolute_paths: list[str] = field(default_factory=list)
    read_calls: list[str] = field(default_factory=list)
    referenced_files: list[str] = field(default_factory=list)
    # Every data-file-looking string literal, wherever it appears — students
    # often assign the path to a variable before reading it.
    data_path_literals: list[str] = field(default_factory=list)
    plot_calls: int = 0
    has_syntax_error: bool = False
    # Cells that could not be parsed; the rest of the notebook is still analysed.
    unparsed_cells: list[int] = field(default_factory=list)
    stored_outputs: dict[str, int] = field(default_factory=dict)
    stored_errors: list[dict[str, Any]] = field(default_factory=list)

    def function_names(self) -> list[str]:
        return [f["name"] for f in self.functions]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "valid": self.valid,
            "parse_error": self.parse_error,
            "n_cells": self.n_cells,
            "n_code_cells": self.n_code_cells,
            "n_markdown_cells": self.n_markdown_cells,
            "imports": sorted(self.imports),
            "functions": self.functions,
            "absolute_paths": self.absolute_paths,
            "read_calls": self.read_calls,
            "referenced_files": self.referenced_files,
            "data_path_literals": self.data_path_literals,
            "plot_calls": self.plot_calls,
            "has_syntax_error": self.has_syntax_error,
            "unparsed_cells": self.unparsed_cells,
            "stored_outputs": self.stored_outputs,
            "stored_errors": self.stored_errors,
            "markdown_cells": self.markdown_cells,
        }


def empty_analysis(path: str = "") -> NotebookAnalysis:
    """Placeholder used when no notebook was submitted at all."""
    return NotebookAnalysis(path=path, valid=False, parse_error="no notebook submitted")


def read_notebook(path: str | Path) -> nbformat.NotebookNode:
    return nbformat.read(str(path), as_version=4)


def analyze_notebook(path: str | Path) -> NotebookAnalysis:
    path = Path(path)
    analysis = NotebookAnalysis(path=str(path))
    try:
        nb = read_notebook(path)
    except Exception as exc:
        analysis.valid = False
        analysis.parse_error = f"{type(exc).__name__}: {exc}"
        return analysis

    code_chunks: list[str] = []
    output_counts: dict[str, int] = {}
    for cell in nb.cells:
        analysis.n_cells += 1
        source = cell.get("source", "") or ""
        if cell.get("cell_type") == "code":
            analysis.n_code_cells += 1
            code_chunks.append(source)
            for output in cell.get("outputs", []) or []:
                kind = output.get("output_type", "unknown")
                output_counts[kind] = output_counts.get(kind, 0) + 1
                if kind == "error":
                    analysis.stored_errors.append(
                        {
                            "ename": output.get("ename"),
                            "evalue": output.get("evalue"),
                            "cell": analysis.n_code_cells,
                        }
                    )
                if kind in {"display_data", "execute_result"}:
                    data = output.get("data", {}) or {}
                    if any(k.startswith("image/") for k in data):
                        output_counts["image"] = output_counts.get("image", 0) + 1
        elif cell.get("cell_type") == "markdown":
            analysis.n_markdown_cells += 1
            analysis.markdown_cells.append(source)

    analysis.stored_outputs = output_counts
    analysis.code_cells = code_chunks
    analysis.code_source = "\n\n".join(code_chunks)
    _analyze_code(analysis)
    return analysis


# IPython syntax that is not Python.
IPYTHON_LINE_PREFIXES = ("%", "!", "?")
IMPORT_RE = re.compile(
    r"^[ \t]*(?:from[ \t]+([\w.]+)[ \t]+import\b|import[ \t]+([^\n#]+))", re.M
)
READ_CALL_RE = re.compile(
    r"\b(read_(?:csv|excel|json|parquet|file|table|html|feather|stata))[ \t]*\("
    r"[ \t]*(?:[rRbBuUfF]*(['\"])([^'\"\n]{1,300})\2)?"
)
STRING_LITERAL_RE = re.compile(r"(['\"])([^'\"\n]{1,300})\1")


def _clean_cell(source: str) -> str:
    """Turn a Jupyter cell into something ``ast.parse`` will accept."""
    lines = []
    for line in source.splitlines():
        if line.lstrip().startswith(IPYTHON_LINE_PREFIXES):
            lines.append("")  # magic or shell escape
            continue
        # `pd.read_csv?` and `df.head??` are IPython help, not Python.
        trimmed = line.rstrip()
        if trimmed.endswith("?"):
            line = trimmed.rstrip("?")
        lines.append(line)
    return "\n".join(lines)


def _parse_cell(source: str) -> tuple[ast.AST, str] | None:
    """Parse one cell, recovering from the usual notebook oddities.

    Returns the tree and the exact text it was parsed from, so source segments
    stay accurate.
    """
    attempts = [
        source,
        textwrap.dedent(source),
        # A cell that continues an indented block from the cell above.
        "if True:\n" + textwrap.indent(source, "    "),
    ]
    for candidate in attempts:
        try:
            return ast.parse(candidate), candidate
        except SyntaxError:
            continue
    return None


def _analyze_code(analysis: NotebookAnalysis) -> None:
    """Collect structural facts cell by cell.

    Parsing per cell rather than parsing the whole notebook at once matters more
    than it looks: one cell containing `pd.read_csv?`, a stray indent or an
    unclosed bracket used to make the entire analysis come back empty, which
    showed up as a student being told they never imported pandas when the import
    was on the first line of the first cell.
    """
    source = analysis.code_source
    analysis.plot_calls = sum(source.count(hint) for hint in PLOT_HINTS)

    for match in ABSOLUTE_PATH_RE.finditer(source):
        candidate = match.group("path")
        if candidate not in analysis.absolute_paths:
            analysis.absolute_paths.append(candidate)

    for index, cell in enumerate(analysis.code_cells, start=1):
        cleaned = _clean_cell(cell)
        if not cleaned.strip():
            continue
        parsed = _parse_cell(cleaned)
        if parsed is None:
            # Keep what this cell plainly says even though it will not parse.
            analysis.has_syntax_error = True
            analysis.unparsed_cells.append(index)
            if analysis.parse_error is None:
                analysis.parse_error = f"code cell {index} could not be parsed"
            _scan_text(analysis, cleaned)
            continue
        tree, parsed_source = parsed
        _collect_from_tree(analysis, tree, parsed_source)


def _collect_from_tree(analysis: NotebookAnalysis, tree: ast.AST, source: str) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            _note_data_literal(analysis, node.value)
        if isinstance(node, ast.Import):
            for alias in node.names:
                analysis.imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            analysis.imports.add(node.module.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            analysis.functions.append(
                {
                    "name": node.name,
                    "params": args,
                    "arity": len(args),
                    "has_docstring": bool(ast.get_docstring(node)),
                    "lineno": node.lineno,
                    "source": _segment(source, node),
                }
            )
        elif isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name in READ_FUNCS:
                analysis.read_calls.append(name)
                for arg in node.args[:1]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        analysis.referenced_files.append(arg.value)


def _scan_text(analysis: NotebookAnalysis, text: str) -> None:
    """Regex fallback for a cell that will not parse."""
    for module, modules in IMPORT_RE.findall(text):
        if module:
            analysis.imports.add(module.split(".")[0])
        for name in modules.split(","):
            name = name.strip().split(" as ")[0].strip()
            if name:
                analysis.imports.add(name.split(".")[0])

    for name, _, path in READ_CALL_RE.findall(text):
        analysis.read_calls.append(name)
        if path:
            analysis.referenced_files.append(path)

    for _, literal in STRING_LITERAL_RE.findall(text):
        _note_data_literal(analysis, literal)


def _note_data_literal(analysis: NotebookAnalysis, text: str) -> None:
    text = text.strip()
    if (
        text.lower().endswith(DATA_SUFFIXES)
        and text not in analysis.data_path_literals
        and len(text) < 300
    ):
        analysis.data_path_literals.append(text)


def _segment(source: str, node: ast.AST) -> str:
    try:
        text = ast.get_source_segment(source, node) or ""
    except Exception:  # pragma: no cover - defensive
        return ""
    return text if len(text) <= 4000 else text[:4000] + "\n... [truncated]"


# ---------------------------------------------------------------------------
# Markdown response extraction (design.md §23, written response)
# ---------------------------------------------------------------------------

def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z']+", text))


# Phrasing that belongs to the assignment prompt rather than a student answer.
INSTRUCTION_RE = re.compile(
    r"\b(in (?:a|one) (?:short |brief )?(?:paragraph|sentence)"
    r"|describe|explain|discuss|interpret the|comment on"
    r"|write (?:a|your)|answer the following|your answer here"
    r"|in your own words|briefly)\b",
    re.IGNORECASE,
)


def _is_instruction(text: str) -> bool:
    """A prompt cell restates the task; an answer cell responds to it."""
    body = text.strip()
    if not body:
        return False
    return bool(INSTRUCTION_RE.search(body)) and _word_count(body) < 80


def _is_boilerplate(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    lowered = stripped.lower()
    placeholders = (
        "your answer here", "type your answer", "write your response",
        "todo", "your response here", "answer:", "[your answer]",
    )
    without_headings = "\n".join(
        line for line in stripped.splitlines() if not line.lstrip().startswith("#")
    ).strip()
    if not without_headings:
        return True
    return any(lowered.replace("*", "").strip().startswith(p) and _word_count(without_headings) < 12
               for p in placeholders)


def extract_markdown_responses(
    analysis: NotebookAnalysis,
    heading_hints: list[str] | None = None,
    min_words: int = 30,
) -> dict[str, Any]:
    """Find the most substantial free-text markdown answer in the notebook."""
    heading_hints = [h.lower() for h in (heading_hints or [])]
    scored: list[tuple[float, str, int]] = []

    for index, cell in enumerate(analysis.markdown_cells):
        if _is_boilerplate(cell) or _is_instruction(cell):
            continue
        words = _word_count(cell)
        if words < 2:
            continue
        score = float(words)
        lowered = cell.lower()
        if any(hint in lowered for hint in heading_hints):
            score += 60
        # A cell that follows a prompt heading is more likely the answer.
        if index > 0:
            previous = analysis.markdown_cells[index - 1].lower()
            if any(hint in previous for hint in heading_hints):
                score += 40
        # The notebook's own title block is never the answer.
        if index == 0 and cell.lstrip().startswith("#"):
            score -= 50
        scored.append((score, cell, words))

    # A negative score means the only thing left was scaffolding, not a response.
    scored = [entry for entry in scored if entry[0] > 0]
    scored.sort(key=lambda triple: triple[0], reverse=True)
    best = scored[0] if scored else None
    return {
        "found": best is not None,
        "text": best[1] if best else "",
        "word_count": best[2] if best else 0,
        "meets_minimum": bool(best and best[2] >= min_words),
        "candidate_count": len(scored),
        "all_candidates": [c[1] for c in scored[:5]],
    }


def render_cells(path: str | Path, max_output_chars: int = 4000) -> list[dict[str, Any]]:
    """Flatten a notebook into a read-only structure for the UI (design.md §13)."""
    try:
        nb = read_notebook(path)
    except Exception as exc:
        return [{"cell_type": "error", "source": f"Could not read notebook: {exc}", "outputs": []}]

    cells: list[dict[str, Any]] = []
    for cell in nb.cells:
        if cell.get("metadata", {}).get("musa_probe"):
            continue  # grader scaffolding, not the student's work
        entry: dict[str, Any] = {
            "cell_type": cell.get("cell_type", "raw"),
            "source": cell.get("source", ""),
            "execution_count": cell.get("execution_count"),
            "outputs": [],
        }
        for output in cell.get("outputs", []) or []:
            kind = output.get("output_type")
            if kind == "stream":
                entry["outputs"].append(
                    {"type": "text", "text": (output.get("text") or "")[:max_output_chars]}
                )
            elif kind in {"execute_result", "display_data"}:
                data = output.get("data", {}) or {}
                if "image/png" in data:
                    entry["outputs"].append({"type": "image", "data": data["image/png"]})
                elif "text/html" in data:
                    entry["outputs"].append(
                        {"type": "html", "html": "".join(data["text/html"])[:max_output_chars]}
                    )
                elif "text/plain" in data:
                    entry["outputs"].append(
                        {"type": "text", "text": "".join(data["text/plain"])[:max_output_chars]}
                    )
            elif kind == "error":
                entry["outputs"].append(
                    {
                        "type": "error",
                        "ename": output.get("ename", ""),
                        "evalue": output.get("evalue", ""),
                        "traceback": "\n".join(output.get("traceback", []))[:max_output_chars],
                    }
                )
        cells.append(entry)
    return cells
