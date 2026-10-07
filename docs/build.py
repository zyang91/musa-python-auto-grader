"""Build the MUSA Grader documentation site.

    python docs/build.py

Writes static HTML into ``docs/``: the guide pages come from the fragments in
``docs/_pages/``, and the API reference is generated from the docstrings in
``grader/`` and ``assignments/``. The source is read with ``ast`` rather than
imported, so the build needs nothing beyond the standard library — not even the
grader's own dependencies.

Serve the result from ``docs/`` (GitHub Pages: Settings → Pages → ``/docs``),
or open ``docs/index.html`` directly.
"""

from __future__ import annotations

import ast
import html
import json
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

DOCS = Path(__file__).resolve().parent
ROOT = DOCS.parent
PAGES = DOCS / "_pages"
REPO_URL = "https://github.com/zyang91/musa-python-auto-grader"
SOURCE_URL = f"{REPO_URL}/blob/main"
PROJECT = "MUSA Grader"


def _version() -> str:
    match = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "grader/__init__.py").read_text())
    return match.group(1) if match else "0.0.0"


VERSION = _version()

# Guide pages, in sidebar order: (fragment stem, section).
GUIDE = [
    ("index", "Introduction"),
    ("getting-started", "Introduction"),
    ("ta-workflow", "User guide"),
    ("cli", "User guide"),
    ("how-it-works", "User guide"),
    ("assignments", "User guide"),
    ("rubrics", "User guide"),
    ("docker", "User guide"),
    ("results", "User guide"),
    ("extending", "Developer guide"),
    ("testing", "Developer guide"),
]

# API reference, in sidebar order: (module path, group).
API_MODULES = [
    ("grader/__init__.py", "Package"),
    ("grader/service.py", "Engine"),
    ("grader/rubric.py", "Engine"),
    ("grader/models.py", "Engine"),
    ("grader/results.py", "Engine"),
    ("grader/scoring.py", "Engine"),
    ("grader/feedback.py", "Engine"),
    ("grader/discovery.py", "Execution"),
    ("grader/executor.py", "Execution"),
    ("grader/notebook_runner.py", "Execution"),
    ("grader/probe_runtime.py", "Execution"),
    ("grader/notebook.py", "Evidence"),
    ("grader/inspection.py", "Evidence"),
    ("grader/answers.py", "Evidence"),
    ("grader/charts.py", "Evidence"),
    ("grader/llm.py", "Evidence"),
    ("grader/utils.py", "Evidence"),
    ("assignments/__init__.py", "Assignments"),
    ("assignments/base.py", "Assignments"),
    ("assignments/hw1.py", "Assignments"),
    ("assignments/hw2.py", "Assignments"),
    ("assignments/hw3.py", "Assignments"),
]


# Descriptions for public objects whose source has no docstring. A docstring in
# the source always wins; delete an entry here once the source documents it.
API_NOTES = {
    "grader.service.GradingService": (
        "Orchestrates a grading run: find submissions, place the data, execute each\n"
        "notebook, run the assignment's checks and apply the review policy.\n\n"
        "This is the only entry point the Streamlit UI and ``cli.py`` use. Construct it\n"
        "from a loaded ``Rubric`` (or with ``from_rubric_path``); the assignment grader\n"
        "registered under ``rubric.id`` is selected automatically."
    ),
    "grader.service.GradingService.from_rubric_path": "Load a rubric YAML and build a service for it.",
    "grader.service.GradingService.new_session": (
        "An empty ``GradingSession`` for this rubric and these settings, with a fresh\n"
        "timestamped session id."
    ),
    "grader.service.GradingService.run": (
        "Grade every candidate and return the saved session.\n\n"
        "Submissions are graded one at a time. ``progress_callback`` receives a\n"
        "``GradingProgress`` snapshot at every stage (a callback that raises never stops\n"
        "grading); setting ``cancel_event`` stops after the current submission.\n"
        "``preserve_overrides`` is a snapshot from ``GradingSession.collect_overrides``\n"
        "to re-apply on top of the fresh automatic scores. Working directories are\n"
        "deleted afterwards unless ``GraderSettings.keep_workdirs`` is set."
    ),
    "grader.service.GradingService.regrade": (
        "Grade the same candidates again into the same session id and directory.\n\n"
        "With ``preserve_overrides`` (the default) every manual override is snapshotted\n"
        "first and restored on top of the new automatic scores."
    ),
    "grader.service.LoadedSubmissions": (
        "What ``GradingService.load_submissions`` found: one ``SubmissionCandidate`` per\n"
        "student, plus where a Canvas ZIP was extracted to."
    ),
    "grader.service.GraderSettings.to_dict": "The settings as stored in ``grading_session.json``.",
    "grader.rubric.RubricItem": "One graded line of a rubric, as declared in the YAML ``rubric:`` list.",
    "grader.rubric.Rubric": (
        "A parsed rubric file. Every top-level YAML block is kept as-is, so assignment\n"
        "graders can read their own configuration from ``settings``, ``probe``,\n"
        "``discovery`` and ``data``."
    ),
    "grader.rubric.load_rubric": (
        "Parse and validate a rubric YAML file.\n\n"
        "Raises ``RubricError`` when the file is missing or unparsable, ``assignment.id``\n"
        "is absent, the rubric is empty, an item id is missing or duplicated, an item\n"
        "type is unknown, or the item points do not add up to ``total_points``."
    ),
    "grader.results.GradingSession": (
        "One grading run and everything decided in it, persisted under\n"
        "``results/<session_id>/``.\n\n"
        "Holds a ``SubmissionResult`` per student keyed by student id, plus the rubric\n"
        "version and settings that produced them. ``save`` writes the session JSON,\n"
        "the CSVs, the class report and per-student feedback; ``load`` reads it back."
    ),
    "grader.results.GradingSession.ordered_results": "Results sorted by student id.",
    "grader.results.GradingSession.upsert": "Add or replace one student's result.",
    "grader.results.GradingSession.summary": "The class summary (mean, median, distribution, common issues, rubric breakdown).",
    "grader.results.GradingSession.queue": "The review queue: submissions that still need a person, most urgent first.",
    "grader.results.GradingSession.set_override": (
        "Override one rubric item's score. The automatic score is kept alongside it;\n"
        "pass ``enabled=False`` to remove an override. Returns ``False`` if the student\n"
        "or item does not exist."
    ),
    "grader.results.GradingSession.mark_reviewed": "Mark a submission as reviewed, which removes it from the queue.",
    "grader.results.GradingSession.save": "Write the session and all its exports to disk; returns the session directory.",
    "grader.results.GradingSession.load": "Read a session back from its directory.",
    "grader.results.GradingSession.grades_csv": "``grades.csv``: one row per student.",
    "grader.results.GradingSession.rubric_csv": "One row per student per rubric item.",
    "grader.results.GradingSession.flagged_csv": "``flagged_submissions.csv``: the review queue.",
    "grader.results.GradingSession.feedback_zip": "Every student's markdown feedback, zipped.",
    "grader.results.GradingSession.archive_zip": "The whole session directory, zipped.",
    "grader.results.list_sessions": "Every saved session under ``results/``, in reverse directory-name order (newest first for each assignment).",
    "grader.results.new_session_id": "``<assignment_id>_<YYYYmmdd>_<HHMMSS>``.",
    "grader.executor.ExecutionConfig": "Limits for one notebook execution, derived from ``GraderSettings``.",
    "grader.executor.docker_available": "Whether a Docker daemon answers on this machine.",
    "grader.executor.docker_image_exists": "Whether the sandbox image has been built locally.",
    "grader.discovery.SubmissionCandidate.ok": "True when a notebook was chosen for this submission.",
    "grader.models.RubricItemResult.final_score": "The manual score when overridden, otherwise the automatic score.",
    "grader.models.SubmissionResult.total_score": "Sum of the items' final scores.",
    "grader.models.SubmissionResult.max_score": "Sum of the items' possible points.",
    "assignments.base.register": "Class decorator: register an ``AssignmentGrader`` subclass under its ``assignment_id``.",
    "assignments.base.AssignmentGrader.grade": (
        "Run every rubric item's ``check_<id>`` method and return one result per item.\n\n"
        "A missing check returns ``manual_review``; a check that raises returns\n"
        "``manual_review`` with confidence 0 and the error in its evidence, so a broken\n"
        "check never loses a submission."
    ),
    "assignments.base.AssignmentGrader.result": (
        "Build a ``RubricItemResult``, rounding the score to the rubric's\n"
        "``score_rounding`` increment and clamping it to ``[0, points]``."
    ),
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def esc(text: str) -> str:
    return html.escape(text, quote=True)


def slug(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "section"


def module_name(path: str) -> str:
    name = path[:-3].replace("/", ".")
    return name[: -len(".__init__")] if name.endswith(".__init__") else name


def module_url(path: str) -> str:
    return f"api/{module_name(path)}.html"


# ---------------------------------------------------------------------------
# Docstrings → HTML
# ---------------------------------------------------------------------------

INLINE_CODE = re.compile(r"``(.+?)``|`([^`]+?)`")
EMPHASIS = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")
STRONG = re.compile(r"\*\*(?!\s)([^*\n]+?)(?<!\s)\*\*")
SECTION_REF = re.compile(r"design\.md (§\d+|section \d+)")


def inline(text: str) -> str:
    """Escape a line of docstring text and apply the inline markup it uses."""
    parts: list[str] = []
    last = 0
    for match in INLINE_CODE.finditer(text):
        parts.append(_inline_plain(text[last:match.start()]))
        code = match.group(1) or match.group(2)
        parts.append(f"<code>{esc(code)}</code>")
        last = match.end()
    parts.append(_inline_plain(text[last:]))
    return "".join(parts)


def _inline_plain(text: str) -> str:
    text = esc(text)
    text = STRONG.sub(r"<strong>\1</strong>", text)
    text = EMPHASIS.sub(r"<em>\1</em>", text)
    return text


def docstring_html(doc: str | None, heading_level: int = 4) -> str:
    """Render the reStructuredText subset this codebase's docstrings use.

    Paragraphs, ``*``/``-`` bullet lists, indented literal blocks, underlined
    section titles and inline ````code````. Anything fancier falls through as text.
    """
    if not doc:
        return ""
    lines = textwrap.dedent(_strip_first(doc)).strip("\n").splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue

        # Underlined section title: "Why this exists\n---------------".
        if i + 1 < len(lines) and re.fullmatch(r"[-=~^]{3,}", lines[i + 1].strip()) \
                and not line.startswith(" "):
            out.append(f"<h{heading_level} class=\"doc-heading\">{inline(stripped)}</h{heading_level}>")
            i += 2
            continue

        # RST simple table: "====  ====" borders around a header and rows.
        if RST_BORDER.fullmatch(stripped) and not line.startswith(" "):
            table, i = _rst_table(lines, i)
            out.append(table)
            continue

        # Indented literal block.
        if line.startswith((" ", "\t")):
            block: list[str] = []
            while i < len(lines) and (not lines[i].strip() or lines[i].startswith((" ", "\t"))):
                block.append(lines[i])
                i += 1
            code = textwrap.dedent("\n".join(block)).strip("\n")
            out.append(f"<pre class=\"doc-literal\"><code>{esc(code)}</code></pre>")
            continue

        # Bullet list; continuation lines are indented under the bullet.
        if re.match(r"[*-] ", stripped):
            items: list[str] = []
            while i < len(lines) and lines[i].strip():
                current = lines[i]
                if re.match(r"\s*[*-] ", current) and not current.startswith("    "):
                    items.append(re.sub(r"^\s*[*-] ", "", current))
                elif items:
                    items[-1] += " " + current.strip()
                else:
                    break
                i += 1
            out.append("<ul>" + "".join(f"<li>{inline(item)}</li>" for item in items) + "</ul>")
            continue

        # Paragraph.
        para: list[str] = []
        while i < len(lines) and lines[i].strip() and not lines[i].startswith((" ", "\t")):
            if para and re.match(r"[*-] ", lines[i].strip()):
                break
            para.append(lines[i].strip())
            i += 1
        text = " ".join(para)
        if text.endswith("::"):
            text = text[:-1]
        out.append(f"<p>{inline(text)}</p>")
    return "\n".join(out)


RST_BORDER = re.compile(r"=+(\s+=+)+")


def _rst_table(lines: list[str], i: int) -> tuple[str, int]:
    """Render an RST simple table. Rows split on runs of 2+ spaces; a line that
    starts blank continues the previous row's last cell."""
    ncols = len(lines[i].split())
    borders = 0
    header: list[list[str]] = []
    rows: list[list[str]] = []
    while i < len(lines):
        text = lines[i]
        if RST_BORDER.fullmatch(text.strip()):
            borders += 1
            i += 1
            if borders == 3:
                break
            continue
        if not text.strip():
            if borders >= 2:
                break
            i += 1
            continue
        target = header if borders == 1 else rows
        if text.startswith(" ") and target:
            target[-1][-1] += " " + text.strip()
        else:
            cells = re.split(r"\s{2,}", text.strip(), maxsplit=ncols - 1)
            target.append(cells + [""] * (ncols - len(cells)))
        i += 1
    if borders < 3 and not rows:  # only one header-less block: header was the body
        rows, header = header, []
    head = "".join(f"<th>{inline(c)}</th>" for c in (header[0] if header else []))
    body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>" for row in rows)
    thead = f"<thead><tr>{head}</tr></thead>" if head else ""
    return f'<div class="table-wrap"><table>{thead}<tbody>{body}</tbody></table></div>', i


def plain(text: str) -> str:
    """Docstring text with its inline markup removed, for search snippets."""
    return re.sub(r"``(.+?)``|`([^`]+?)`", lambda m: m.group(1) or m.group(2), text)


def _strip_first(doc: str) -> str:
    """Docstrings start on the quote line; dedent the rest independently."""
    first, _, rest = doc.partition("\n")
    return first.strip() + "\n" + textwrap.dedent(rest)


def summary_line(doc: str | None) -> str:
    if not doc:
        return ""
    para = doc.strip().split("\n\n")[0]
    return " ".join(line.strip() for line in para.splitlines())


# ---------------------------------------------------------------------------
# Source → API model
# ---------------------------------------------------------------------------

@dataclass
class Field:
    name: str
    annotation: str
    default: str | None
    comment: str = ""


@dataclass
class Function:
    name: str
    signature: str
    doc: str | None
    lineno: int
    kind: str = "function"  # function | method | classmethod | staticmethod | property
    is_async: bool = False


@dataclass
class Klass:
    name: str
    bases: list[str]
    doc: str | None
    lineno: int
    decorators: list[str]
    fields: list[Field] = field(default_factory=list)
    methods: list[Function] = field(default_factory=list)
    attributes: list[Field] = field(default_factory=list)


@dataclass
class Constant:
    name: str
    value: str
    lineno: int
    comment: str = ""


@dataclass
class Module:
    path: str
    name: str
    doc: str | None
    classes: list[Klass]
    functions: list[Function]
    constants: list[Constant]
    exports: list[str] | None
    reexports: list[tuple[str, str]]
    n_lines: int
    rubric: dict = field(default_factory=dict)


def _unparse(node: ast.AST | None) -> str:
    return ast.unparse(node) if node is not None else ""


def _short(value: str, limit: int = 90) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef, drop_first: bool) -> str:
    args = node.args
    parts: list[str] = []
    positional = list(args.posonlyargs) + list(args.args)
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    for index, (arg, default) in enumerate(zip(positional, defaults)):
        if index == 0 and drop_first:
            continue
        piece = arg.arg
        if arg.annotation is not None:
            piece += f": {_unparse(arg.annotation)}"
        if default is not None:
            piece += (" = " if arg.annotation is not None else "=") + _unparse(default)
        parts.append(piece)
        if args.posonlyargs and arg is args.posonlyargs[-1]:
            parts.append("/")
    if args.vararg:
        star = f"*{args.vararg.arg}"
        if args.vararg.annotation is not None:
            star += f": {_unparse(args.vararg.annotation)}"
        parts.append(star)
    elif args.kwonlyargs:
        parts.append("*")
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        piece = arg.arg
        if arg.annotation is not None:
            piece += f": {_unparse(arg.annotation)}"
        if default is not None:
            piece += (" = " if arg.annotation is not None else "=") + _unparse(default)
        parts.append(piece)
    if args.kwarg:
        star = f"**{args.kwarg.arg}"
        if args.kwarg.annotation is not None:
            star += f": {_unparse(args.kwarg.annotation)}"
        parts.append(star)
    signature = f"({', '.join(parts)})"
    if node.returns is not None:
        signature += f" -> {_unparse(node.returns)}"
    return signature


def _comment_above(source_lines: list[str], lineno: int) -> str:
    """The ``#`` comment block directly above a line, joined into one paragraph."""
    collected: list[str] = []
    index = lineno - 2
    while index >= 0:
        text = source_lines[index].strip()
        if text.startswith("#") and not re.fullmatch(r"#\s*[-=]{5,}", text):
            collected.append(text.lstrip("#").strip())
            index -= 1
            continue
        break
    return " ".join(reversed(collected)).strip()


def _function(node, kind: str, drop_first: bool) -> Function:
    return Function(
        name=node.name,
        signature=_signature(node, drop_first),
        doc=ast.get_docstring(node),
        lineno=node.lineno,
        kind=kind,
        is_async=isinstance(node, ast.AsyncFunctionDef),
    )


def _decorator_names(node) -> list[str]:
    return [_unparse(d) for d in node.decorator_list]


def _is_public(name: str) -> bool:
    return not name.startswith("_") or name == "__init__"


def parse_module(path: str) -> Module:
    source = (ROOT / path).read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)
    classes: list[Klass] = []
    functions: list[Function] = []
    constants: list[Constant] = []
    exports: list[str] | None = None
    reexports: list[tuple[str, str]] = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and _is_public(node.name):
            classes.append(_parse_class(node, lines))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            functions.append(_function(node, "function", drop_first=False))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id == "__all__" and isinstance(node.value, (ast.List, ast.Tuple)):
                    exports = [elt.value for elt in node.value.elts if isinstance(elt, ast.Constant)]
                elif re.fullmatch(r"[A-Z][A-Z0-9_]+", target.id) and node.value is not None:
                    constants.append(Constant(
                        name=target.id,
                        value=_short(_unparse(node.value), 140),
                        lineno=node.lineno,
                        comment=_comment_above(lines, node.lineno),
                    ))
        elif isinstance(node, ast.ImportFrom) and node.level and path.endswith("__init__.py"):
            for alias in node.names:
                reexports.append((alias.asname or alias.name, node.module or ""))

    return Module(
        path=path,
        name=module_name(path),
        doc=ast.get_docstring(tree),
        classes=classes,
        functions=functions,
        constants=constants,
        exports=exports,
        reexports=reexports,
        n_lines=len(lines),
    )


def rubric_items(module: Module) -> dict[str, dict]:
    """Rubric items for an assignment grader module, keyed by item id.

    ``assignments/hw3.py`` is graded by ``rubrics/hw3.yaml``; each ``check_<id>``
    method documents the item with that id. Needs PyYAML, which the grader itself
    depends on; without it the pages simply leave this out.
    """
    stem = Path(module.path).stem
    path = ROOT / "rubrics" / f"{stem}.yaml"
    if not module.path.startswith("assignments/") or not path.exists():
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(item.get("id")): item for item in data.get("rubric") or []}


def apply_notes(module: Module) -> Module:
    """Fill missing docstrings from ``API_NOTES``; the source always wins."""
    for klass in module.classes:
        klass.doc = klass.doc or API_NOTES.get(f"{module.name}.{klass.name}")
        for method in klass.methods:
            method.doc = method.doc or API_NOTES.get(f"{module.name}.{klass.name}.{method.name}")
    for fn in module.functions:
        fn.doc = fn.doc or API_NOTES.get(f"{module.name}.{fn.name}")
    return module


def _parse_class(node: ast.ClassDef, lines: list[str]) -> Klass:
    decorators = _decorator_names(node)
    klass = Klass(
        name=node.name,
        bases=[_unparse(b) for b in node.bases],
        doc=ast.get_docstring(node),
        lineno=node.lineno,
        decorators=decorators,
    )
    is_dataclass = any(d.split("(")[0].endswith("dataclass") for d in decorators)
    for child in node.body:
        if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
            entry = Field(
                name=child.target.id,
                annotation=_unparse(child.annotation),
                default=_short(_unparse(child.value)) if child.value is not None else None,
                comment=_comment_above(lines, child.lineno) or _trailing_comment(lines, child),
            )
            if child.target.id.startswith("_"):
                continue
            (klass.fields if is_dataclass else klass.attributes).append(entry)
        elif isinstance(child, ast.Assign):
            for target in child.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    klass.attributes.append(Field(
                        name=target.id, annotation="",
                        default=_short(_unparse(child.value)),
                        comment=_comment_above(lines, child.lineno) or _trailing_comment(lines, child),
                    ))
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_public(child.name):
            names = _decorator_names(child)
            if "property" in names or any(n.endswith(".setter") for n in names):
                if any(n.endswith(".setter") for n in names):
                    continue
                kind = "property"
            elif "classmethod" in names:
                kind = "classmethod"
            elif "staticmethod" in names:
                kind = "staticmethod"
            else:
                kind = "method"
            klass.methods.append(_function(child, kind, drop_first=kind != "staticmethod"))
    return klass


def _trailing_comment(lines: list[str], node: ast.AST) -> str:
    text = lines[node.lineno - 1]
    if "#" in text and not text.strip().startswith("#"):
        comment = text.split("#", 1)[1].strip()
        return "" if comment.startswith(("noqa", "type:", "pragma")) else comment
    return ""


# ---------------------------------------------------------------------------
# API → HTML
# ---------------------------------------------------------------------------

class Linker:
    """Turns names in signatures into links to where they are documented."""

    def __init__(self, modules: list[Module]):
        self.targets: dict[str, str] = {}
        for module in modules:
            if module.path.endswith("__init__.py"):
                continue
            for klass in module.classes:
                self.targets.setdefault(klass.name, f"{module.name}.html#{module.name}.{klass.name}")
        self.pattern = re.compile(
            r"\b(" + "|".join(sorted(map(re.escape, self.targets), key=len, reverse=True)) + r")\b"
        ) if self.targets else None

    def link(self, escaped: str, current: str = "") -> str:
        if not self.pattern:
            return escaped

        def replace(match: re.Match) -> str:
            name = match.group(1)
            target = self.targets[name]
            if target.startswith(current + ".html#"):
                target = target.split(".html", 1)[1]
            return f'<a class="xref" href="{target}">{name}</a>'

        return self.pattern.sub(replace, escaped)


def source_link(path: str, lineno: int | None = None) -> str:
    anchor = f"#L{lineno}" if lineno else ""
    return (f'<a class="source-link" href="{SOURCE_URL}/{path}{anchor}" '
            f'title="View source on GitHub">[source]</a>')


def render_function(fn: Function, module: Module, linker: Linker, owner: str = "") -> str:
    qualified = f"{module.name}.{owner + '.' if owner else ''}{fn.name}"
    prefix = {
        "property": "property ",
        "classmethod": "classmethod ",
        "staticmethod": "staticmethod ",
    }.get(fn.kind, "")
    if fn.is_async:
        prefix = "async " + prefix
    if fn.kind == "property":
        returns = fn.signature.split(" -> ", 1)[1] if " -> " in fn.signature else ""
        sig = f": {linker.link(esc(returns), module.name)}" if returns else ""
    else:
        sig = linker.link(esc(fn.signature), module.name)
    kind_label = f'<span class="sig-kind">{esc(prefix)}</span>' if prefix else ""
    item = module.rubric.get(fn.name[len("check_"):]) if fn.name.startswith("check_") else None
    body = docstring_html(fn.doc, heading_level=5)
    if item:
        stem = Path(module.path).stem
        ref = (f'<p class="rubric-ref"><span class="badge">{float(item.get("points", 0)):g} pts</span>'
               f'<span class="badge badge-gray">{esc(str(item.get("type", "deterministic")))}</span>'
               f'<strong>{inline(str(item.get("name", "")))}</strong>'
               f'<a class="muted small" href="{SOURCE_URL}/rubrics/{stem}.yaml">rubrics/{stem}.yaml</a></p>')
        description = " ".join(str(item.get("description", "")).split())
        if not body and description:
            body = f"<p>{inline(description)}</p>"
        keys = sorted((item.get("config") or {}).keys())
        if keys:
            body += ('<p class="config-keys"><span class="muted">Config keys:</span> '
                     + " ".join(f"<code>{esc(k)}</code>" for k in keys) + "</p>")
        body = ref + body
    body = body or '<p class="muted">No description.</p>'
    return f"""
<dl class="api-object api-{fn.kind}" id="{esc(qualified)}">
  <dt class="sig">{kind_label}<span class="sig-name">{esc(fn.name)}</span><span class="sig-params">{sig}</span>
    <a class="headerlink" href="#{esc(qualified)}" aria-label="Link to {esc(fn.name)}">#</a>{source_link(module.path, fn.lineno)}</dt>
  <dd>{body}</dd>
</dl>"""


def render_fields(fields: list[Field], title: str, linker: Linker, module: Module) -> str:
    if not fields:
        return ""
    rows = []
    for f in fields:
        annotation = linker.link(esc(f.annotation), module.name) if f.annotation else ""
        default = f"<code>{esc(f.default)}</code>" if f.default is not None else '<span class="muted">required</span>'
        rows.append(
            f"<tr><td><code class=\"field-name\">{esc(f.name)}</code></td>"
            f"<td><code>{annotation}</code></td><td>{default}</td>"
            f"<td>{inline(f.comment) if f.comment else ''}</td></tr>"
        )
    return f"""
<div class="field-table">
  <p class="rubric">{title}</p>
  <div class="table-wrap"><table>
    <thead><tr><th>Name</th><th>Type</th><th>Default</th><th>Notes</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table></div>
</div>"""


def render_class(klass: Klass, module: Module, linker: Linker) -> str:
    qualified = f"{module.name}.{klass.name}"
    bases = ""
    if klass.bases:
        bases = "(" + linker.link(esc(", ".join(klass.bases)), module.name) + ")"
    decorator = ""
    if any(d.split("(")[0].endswith("dataclass") for d in klass.decorators):
        decorator = '<span class="badge">dataclass</span>'
    elif any(d == "register" for d in klass.decorators):
        decorator = '<span class="badge">registered grader</span>'
    init = next((m for m in klass.methods if m.name == "__init__"), None)
    sig = linker.link(esc(init.signature.replace(" -> None", "")), module.name) if init else ""
    methods = [m for m in klass.methods if m.name != "__init__"]
    properties = [m for m in methods if m.kind == "property"]
    others = [m for m in methods if m.kind != "property"]
    checks = [m for m in others if m.name.startswith("check_")]
    others = [m for m in others if not m.name.startswith("check_")]

    parts = [
        f"""
<section class="api-class" id="{esc(qualified)}">
  <div class="sig sig-class"><span class="sig-kind">class </span><span class="sig-name">{esc(klass.name)}</span><span class="sig-params">{sig or bases}</span>
    <a class="headerlink" href="#{esc(qualified)}" aria-label="Link to {esc(klass.name)}">#</a>{source_link(module.path, klass.lineno)}</div>
  <div class="api-body">
    <p class="class-meta">{decorator}{f'<span class="bases">Bases: <code>{bases[1:-1]}</code></span>' if bases and init else ''}</p>
    {docstring_html(klass.doc) or '<p class="muted">No description.</p>'}
    {render_fields(klass.fields, "Fields", linker, module)}
    {render_fields(klass.attributes, "Class attributes", linker, module)}"""
    ]
    if properties:
        parts.append('<p class="rubric">Properties</p>')
        parts.extend(render_function(m, module, linker, klass.name) for m in properties)
    if others:
        parts.append('<p class="rubric">Methods</p>')
        parts.extend(render_function(m, module, linker, klass.name) for m in others)
    if checks:
        parts.append(f'<p class="rubric">Rubric checks <span class="count">{len(checks)}</span></p>')
        parts.append('<p class="muted small">Each <code>check_&lt;rubric_id&gt;</code> method grades the '
                     'rubric item with that id and returns one <code>RubricItemResult</code>.</p>')
        parts.extend(render_function(m, module, linker, klass.name) for m in checks)
    parts.append("  </div>\n</section>")
    return "\n".join(parts)


def render_module(module: Module, linker: Linker) -> tuple[str, list[tuple[int, str, str]]]:
    toc: list[tuple[int, str, str]] = []
    parts = [
        f'<p class="eyebrow">API reference · <a href="{SOURCE_URL}/{module.path}">{esc(module.path)}</a> · {module.n_lines} lines</p>',
        f'<h1 class="module-title"><code>{esc(module.name)}</code></h1>',
        f'<div class="module-doc">{docstring_html(module.doc, heading_level=3) or "<p class=muted>No module docstring.</p>"}</div>',
    ]

    if module.reexports:
        rows = "".join(
            f'<tr><td><code>{linker.link(esc(name))}</code></td><td><code>{esc(module.name)}.{esc(origin)}</code></td></tr>'
            for name, origin in module.reexports
        )
        parts.append('<h2 id="exports">Exports</h2>')
        parts.append(f'<div class="table-wrap"><table><thead><tr><th>Name</th><th>Defined in</th></tr></thead><tbody>{rows}</tbody></table></div>')
        toc.append((2, "exports", "Exports"))

    if module.classes or module.functions:
        parts.append('<h2 id="summary">Summary</h2>')
        toc.append((2, "summary", "Summary"))
        rows = []
        for klass in module.classes:
            rows.append(f'<tr><td><a href="#{module.name}.{klass.name}"><code>{esc(klass.name)}</code></a></td>'
                        f'<td><span class="kind">class</span></td><td>{inline(summary_line(klass.doc))}</td></tr>')
        for fn in module.functions:
            rows.append(f'<tr><td><a href="#{module.name}.{fn.name}"><code>{esc(fn.name)}()</code></a></td>'
                        f'<td><span class="kind">function</span></td><td>{inline(summary_line(fn.doc))}</td></tr>')
        parts.append('<div class="table-wrap"><table class="summary-table"><thead><tr><th>Name</th><th>Kind</th>'
                     f'<th>Description</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')

    if module.constants:
        parts.append('<h2 id="constants">Constants</h2>')
        toc.append((2, "constants", "Constants"))
        rows = "".join(
            f'<tr id="{module.name}.{c.name}"><td><code class="field-name">{esc(c.name)}</code></td>'
            f'<td><code>{esc(c.value)}</code></td><td>{inline(c.comment)}</td></tr>'
            for c in module.constants
        )
        parts.append('<div class="table-wrap"><table><thead><tr><th>Name</th><th>Value</th><th>Notes</th></tr></thead>'
                     f'<tbody>{rows}</tbody></table></div>')

    if module.classes:
        parts.append('<h2 id="classes">Classes</h2>')
        toc.append((2, "classes", "Classes"))
        for klass in module.classes:
            toc.append((3, f"{module.name}.{klass.name}", klass.name))
            parts.append(render_class(klass, module, linker))

    if module.functions:
        parts.append('<h2 id="functions">Functions</h2>')
        toc.append((2, "functions", "Functions"))
        for fn in module.functions:
            toc.append((3, f"{module.name}.{fn.name}", fn.name + "()"))
            parts.append(render_function(fn, module, linker))

    return "\n".join(parts), toc


def render_api_index(modules: list[Module]) -> str:
    groups: dict[str, list[Module]] = {}
    for (path, group), module in zip(API_MODULES, modules):
        groups.setdefault(group, []).append(module)
    parts = [
        '<p class="eyebrow">API reference</p>',
        "<h1>API reference</h1>",
        '<p class="lead">Every public class, function and constant in the <code>grader</code> and '
        '<code>assignments</code> packages, generated from the source docstrings. '
        'If you are driving the grader from Python, start with '
        '<a href="grader.service.html"><code>grader.service.GradingService</code></a> — it is the only '
        'entry point the Streamlit UI uses.</p>',
        """<div class="callout callout-tip"><p class="callout-title">Quick example</p>
<pre><code class="language-python">from grader import GraderSettings, GradingService

settings = GraderSettings(execution_mode="docker",
                          shared_data_paths=["examples/data/zillow_zhvi.csv"])
service = GradingService.from_rubric_path("rubrics/hw1.yaml", settings)

for problem in service.preflight():
    print("warning:", problem)

loaded = service.load_submissions("examples/submissions")
session = service.run(loaded.candidates)

for result in session.ordered_results():
    print(result.student_id, result.total_score, "/", result.max_score,
          "review" if result.needs_review else "")
print("saved to", session.root)</code></pre></div>""",
    ]
    for group, members in groups.items():
        parts.append(f'<h2 id="{slug(group)}">{esc(group)}</h2>')
        parts.append('<div class="module-grid">')
        for module in members:
            counts = []
            if module.classes:
                counts.append(f"{len(module.classes)} class{'es' if len(module.classes) != 1 else ''}")
            if module.functions:
                counts.append(f"{len(module.functions)} function{'s' if len(module.functions) != 1 else ''}")
            if module.reexports:
                counts.append(f"{len(module.reexports)} exports")
            parts.append(
                f'<a class="module-card" href="{module.name}.html"><code>{esc(module.name)}</code>'
                f'<span>{inline(summary_line(module.doc))}</span>'
                f'<small>{" · ".join(counts) or "module"}</small></a>'
            )
        parts.append("</div>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Guide pages
# ---------------------------------------------------------------------------

@dataclass
class Page:
    stem: str
    title: str
    description: str
    body: str
    section: str


def load_page(stem: str, section: str) -> Page:
    raw = (PAGES / f"{stem}.html").read_text(encoding="utf-8")
    meta = dict(re.findall(r"<!--\s*(\w+):\s*(.*?)\s*-->", raw.split("\n\n", 1)[0]))
    body = re.sub(r"\A(\s*<!--.*?-->\s*)+", "", raw, flags=re.S)
    return Page(stem, meta.get("title", stem), meta.get("description", ""), body, section)


HEADING = re.compile(r"<h([23])(\s[^>]*)?>(.*?)</h\1>", re.S)


def add_heading_ids(body: str) -> tuple[str, list[tuple[int, str, str]]]:
    toc: list[tuple[int, str, str]] = []
    used: set[str] = set()

    def replace(match: re.Match) -> str:
        level, attrs, text = int(match.group(1)), match.group(2) or "", match.group(3)
        existing = re.search(r'id="([^"]+)"', attrs)
        anchor = existing.group(1) if existing else slug(text)
        base, n = anchor, 2
        while anchor in used:
            anchor, n = f"{base}-{n}", n + 1
        used.add(anchor)
        if not existing:
            attrs += f' id="{anchor}"'
        label = re.sub(r"<[^>]+>", "", text).strip()
        toc.append((level, anchor, label))
        return (f'<h{level}{attrs}>{text}<a class="headerlink" href="#{anchor}" '
                f'aria-label="Link to this section">#</a></h{level}>')

    return HEADING.sub(replace, body), toc


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

ICON_SEARCH = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>'
ICON_THEME = ('<svg viewBox="0 0 24 24" aria-hidden="true" class="icon-sun"><circle cx="12" cy="12" r="4"/>'
              '<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>'
              '<svg viewBox="0 0 24 24" aria-hidden="true" class="icon-moon"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>')
ICON_GITHUB = ('<svg viewBox="0 0 16 16" aria-hidden="true" class="filled"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 '
               '5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52'
               '-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82'
               '-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1'
               '.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46'
               '.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>')
ICON_MENU = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/></svg>'
LOGO = ('<svg viewBox="0 0 32 32" aria-hidden="true" class="logo"><rect x="3" y="3" width="26" height="26" rx="7" class="logo-bg"/>'
        '<path d="M9.5 16.5l4.2 4.2 8.8-9.4" class="logo-check"/></svg>')


def sidebar(current: str, prefix: str, pages: list[Page], modules: list[Module]) -> str:
    parts = []
    section = None
    for page in pages:
        if page.section != section:
            if section is not None:
                parts.append("</ul>")
            section = page.section
            parts.append(f'<p class="nav-section">{esc(section)}</p><ul class="nav-list">')
        url = "index.html" if page.stem == "index" else f"{page.stem}.html"
        active = ' class="active" aria-current="page"' if current == url else ""
        parts.append(f'<li><a href="{prefix}{url}"{active}>{esc(page.title)}</a></li>')
    parts.append("</ul>")

    parts.append('<p class="nav-section">API reference</p><ul class="nav-list">')
    active = ' class="active" aria-current="page"' if current == "api/index.html" else ""
    parts.append(f'<li><a href="{prefix}api/index.html"{active}>Overview</a></li>')
    group = None
    for (path, grp), module in zip(API_MODULES, modules):
        if grp != group:
            if group is not None:
                parts.append("</ul></li>")
            group = grp
            parts.append(f'<li class="nav-group"><span class="nav-group-label">{esc(grp)}</span><ul>')
        url = module_url(path)
        active = ' class="active" aria-current="page"' if current == url else ""
        parts.append(f'<li><a href="{prefix}{url}"{active}><code>{esc(module.name)}</code></a></li>')
    parts.append("</ul></li></ul>")
    return "\n".join(parts)


def toc_html(toc: list[tuple[int, str, str]]) -> str:
    if len(toc) < 2:
        return ""
    items = "".join(
        f'<li class="toc-l{level}"><a href="#{esc(anchor)}">{esc(label)}</a></li>' for level, anchor, label in toc
    )
    return f'<nav class="toc" aria-label="On this page"><p class="toc-title">On this page</p><ul>{items}</ul></nav>'


def pager(index: int, order: list[tuple[str, str]], prefix: str) -> str:
    prev_link = next_link = ""
    if index > 0:
        url, title = order[index - 1]
        prev_link = f'<a class="pager-prev" href="{prefix}{url}"><small>Previous</small><span>{esc(title)}</span></a>'
    if index < len(order) - 1:
        url, title = order[index + 1]
        next_link = f'<a class="pager-next" href="{prefix}{url}"><small>Next</small><span>{esc(title)}</span></a>'
    return f'<nav class="pager" aria-label="Pages">{prev_link}{next_link}</nav>'


def layout(*, title: str, description: str, body: str, current: str, toc, nav: str,
           pager_html: str, is_api: bool) -> str:
    prefix = "../" if current.startswith("api/") else ""
    page_title = PROJECT if current == "index.html" else f"{title} · {PROJECT}"
    edit = ""
    if not is_api and current != "api/index.html":
        stem = current[:-5]
        edit = (f'<a class="edit-link" href="{SOURCE_URL}/docs/_pages/{stem}.html">'
                'Edit this page on GitHub</a>')
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(page_title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="icon" href="{prefix}assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{prefix}assets/style.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css" media="(prefers-color-scheme: light)" id="hljs-light">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css" media="(prefers-color-scheme: dark)" id="hljs-dark">
<script>
  (function () {{
    try {{ var t = localStorage.getItem("musa-docs-theme"); if (t) document.documentElement.dataset.theme = t; }} catch (e) {{}}
  }})();
</script>
</head>
<body data-root="{prefix}">
<a class="skip-link" href="#content">Skip to content</a>
<header class="topbar">
  <button class="icon-button menu-button" type="button" aria-label="Open navigation" aria-expanded="false" aria-controls="sidebar">{ICON_MENU}</button>
  <a class="brand" href="{prefix}index.html">{LOGO}<span>{PROJECT}</span><span class="version">v{VERSION}</span></a>
  <button class="search-trigger" type="button" aria-label="Search the documentation">{ICON_SEARCH}<span>Search docs</span><kbd>/</kbd></button>
  <div class="topbar-actions">
    <button class="icon-button theme-toggle" type="button" aria-label="Toggle dark mode">{ICON_THEME}</button>
    <a class="icon-button" href="{REPO_URL}" aria-label="GitHub repository">{ICON_GITHUB}</a>
  </div>
</header>
<div class="layout">
  <aside class="sidebar" id="sidebar" aria-label="Documentation">
    <nav>{nav}</nav>
  </aside>
  <div class="sidebar-scrim" hidden></div>
  <main id="content" class="content{' content-api' if is_api else ''}">
    <article class="prose">
{body}
    </article>
    <footer class="page-footer">
      {pager_html}
      <div class="footer-meta">{edit}<span>{PROJECT} {VERSION} · MUSA 5500, University of Pennsylvania</span></div>
    </footer>
  </main>
  <aside class="toc-column">{toc_html(toc)}</aside>
</div>
<div class="search-dialog" role="dialog" aria-modal="true" aria-label="Search" hidden>
  <div class="search-panel">
    <div class="search-input-row">{ICON_SEARCH}<input type="search" placeholder="Search guides and API…" aria-label="Search" autocomplete="off" spellcheck="false"><kbd>Esc</kbd></div>
    <ul class="search-results" role="listbox"></ul>
    <p class="search-hint">Type to search pages, sections, classes and functions.</p>
  </div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/yaml.min.js"></script>
<script src="{prefix}assets/search-index.js"></script>
<script src="{prefix}assets/main.js"></script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build() -> None:
    pages = [load_page(stem, section) for stem, section in GUIDE]
    modules = [apply_notes(parse_module(path)) for path, _ in API_MODULES]
    for module in modules:
        module.rubric = rubric_items(module)
    linker = Linker(modules)

    order: list[tuple[str, str]] = [
        ("index.html" if p.stem == "index" else f"{p.stem}.html", p.title) for p in pages
    ]
    order.append(("api/index.html", "API reference"))
    order.extend((module_url(m.path), m.name) for m in modules)

    search: list[dict[str, str]] = []
    (DOCS / "api").mkdir(exist_ok=True)

    for index, page in enumerate(pages):
        url = order[index][0]
        body, toc = add_heading_ids(page.body)
        html_text = layout(
            title=page.title, description=page.description, body=body, current=url, toc=toc,
            nav=sidebar(url, "", pages, modules), pager_html=pager(index, order, ""), is_api=False,
        )
        (DOCS / url).write_text(html_text, encoding="utf-8")
        search.append({"t": page.title, "u": url, "s": page.section, "k": "page", "d": page.description})
        for level, anchor, label in toc:
            search.append({"t": label, "u": f"{url}#{anchor}", "s": page.title, "k": "section"})

    api_index_pos = len(pages)
    api_body, api_toc = add_heading_ids(render_api_index(modules))
    (DOCS / "api/index.html").write_text(layout(
        title="API reference", description="Generated reference for the grader and assignments packages.",
        body=api_body, current="api/index.html", toc=api_toc,
        nav=sidebar("api/index.html", "../", pages, modules),
        pager_html=pager(api_index_pos, order, "../"), is_api=True,
    ), encoding="utf-8")
    search.append({"t": "API reference", "u": "api/index.html", "s": "API", "k": "page"})

    for offset, module in enumerate(modules, start=1):
        url = module_url(module.path)
        body, toc = render_module(module, linker)
        (DOCS / url).write_text(layout(
            title=module.name, description=summary_line(module.doc)[:200], body=body, current=url, toc=toc,
            nav=sidebar(url, "../", pages, modules),
            pager_html=pager(api_index_pos + offset, order, "../"), is_api=True,
        ), encoding="utf-8")
        search.append({"t": module.name, "u": url, "s": "Module", "k": "module", "d": summary_line(module.doc)[:160]})
        for klass in module.classes:
            search.append({"t": klass.name, "u": f"{url}#{module.name}.{klass.name}", "s": module.name,
                           "k": "class", "d": summary_line(klass.doc)[:160]})
            for method in klass.methods:
                if method.name == "__init__":
                    continue
                search.append({"t": f"{klass.name}.{method.name}",
                               "u": f"{url}#{module.name}.{klass.name}.{method.name}",
                               "s": module.name, "k": method.kind, "d": summary_line(method.doc)[:160]})
        for fn in module.functions:
            search.append({"t": f"{fn.name}()", "u": f"{url}#{module.name}.{fn.name}", "s": module.name,
                           "k": "function", "d": summary_line(fn.doc)[:160]})
        for const in module.constants:
            search.append({"t": const.name, "u": f"{url}#{module.name}.{const.name}", "s": module.name,
                           "k": "constant"})

    for entry in search:
        if entry.get("d"):
            entry["d"] = plain(entry["d"])
        else:
            entry.pop("d", None)
    (DOCS / "assets/search-index.js").write_text(
        "window.MUSA_SEARCH_INDEX = " + json.dumps(search, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    print(f"Built {len(pages)} guide pages, {len(modules) + 1} API pages, {len(search)} search entries → {DOCS}")


if __name__ == "__main__":
    build()
