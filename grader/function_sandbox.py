"""Run a few named functions from a notebook, and nothing else, in the sandbox.

Why this exists
---------------
Assignment 4 must never be executed: its notebooks scrape Craigslist and pull
data from OpenStreetMap and ArcGIS, and running a class of them would repeat all
of those requests once per student (see ``never_executes`` in
``grader/rubric.py``). But three of its answers are small pure functions —
``format_bedrooms``, ``format_size`` and ``format_price`` turn ``"2br"`` into
``2`` — and calling a function is far better evidence of what it does than
reading it.

So those functions, and only those, are run, under four rules:

1. **Extracted, not executed in place.** The host parses the notebook and cuts
   out the top-level ``def`` of each named function. No other statement of the
   notebook is sent anywhere: not the Selenium driver, not the scraping loop, not
   a cell that happens to sit next to the function.
2. **Nothing runs at definition time.** A decorator, a default value or an
   annotation is evaluated when ``def`` executes, so it could smuggle any call
   in. Decorators and annotations are stripped; a default that is not a plain
   literal makes the function ineligible, and it goes to a person instead.
3. **Only harmless imports.** A function may use ``re`` or ``numpy`` imported in
   another cell, so top-level imports of an allowlisted set of modules are sent
   along. Anything else (``selenium``, ``requests``, ``osmnx``) is not.
4. **Docker with ``--network none``, or not at all.** The functions run in the
   grading container with the same isolation flags as a full notebook run, and
   the container sees one scratch directory holding the extracted source and the
   inputs — not the submission. In local mode the machine has a network, so the
   functions are not run; the item falls back to the source and the student's
   saved outputs and goes to a TA.

The expected answers never leave the host: the container is told what to call,
not what should come back (the same split as ``hidden_test_specs``).
"""

from __future__ import annotations

import ast
import json
import math
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .executor import MODE_DOCKER, ExecutionConfig, sandbox_isolation_flags
from .notebook import _clean_cell, _parse_cell
from .utils import truncate

RUNNER_SOURCE = Path(__file__).resolve().parent / "function_runner.py"
SANDBOX_DIRNAME = "_musa_functions"
RUNNER_NAME = "_musa_functions.py"

# Modules a string-formatting function plausibly needs. Importing any of these
# cannot reach the network on its own.
DEFAULT_ALLOWED_IMPORTS = ("re", "string", "math", "decimal", "numpy", "pandas")

STATUS_RAN = "ran"
STATUS_SKIPPED = "skipped"
STATUS_ERROR = "error"


@dataclass
class ExtractedFunctions:
    """What was cut out of the notebook, and what was refused."""

    functions: dict[str, str] = field(default_factory=dict)
    cells: dict[str, int] = field(default_factory=dict)
    imports: list[str] = field(default_factory=list)
    rejected: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FunctionTestRun:
    status: str
    reason: str = ""
    extracted: ExtractedFunctions = field(default_factory=ExtractedFunctions)
    report: dict[str, Any] = field(default_factory=dict)
    command: list[str] = field(default_factory=list)

    def case(self, case_id: str) -> dict[str, Any] | None:
        for entry in self.report.get("cases", []):
            if entry.get("id") == case_id:
                return entry
        return None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["extracted"] = self.extracted.to_dict()
        return data


# ---------------------------------------------------------------------------
# Extraction (host side, never executes anything)
# ---------------------------------------------------------------------------

def _top_level(tree: ast.AST) -> list[ast.stmt]:
    body = list(getattr(tree, "body", []))
    # ``_parse_cell`` wraps an indented cell in ``if True:`` to parse it.
    if (
        len(body) == 1 and isinstance(body[0], ast.If)
        and isinstance(body[0].test, ast.Constant) and body[0].test.value is True
    ):
        return list(body[0].body)
    return body


def _literal(node: ast.AST | None) -> bool:
    if node is None:
        return True
    try:
        ast.literal_eval(node)
        return True
    except Exception:
        return False


def _sanitise(node: ast.FunctionDef) -> tuple[ast.FunctionDef | None, str]:
    """Strip what runs at definition time; refuse what cannot be stripped."""
    args = node.args
    defaults = list(args.defaults) + [d for d in args.kw_defaults if d is not None]
    if not all(_literal(d) for d in defaults):
        return None, "a default argument is not a plain literal"
    node.decorator_list = []
    node.returns = None
    for arg in args.posonlyargs + args.args + args.kwonlyargs:
        arg.annotation = None
    for arg in (args.vararg, args.kwarg):
        if arg is not None:
            arg.annotation = None
    return node, ""


def _allowed_import(node: ast.stmt, allowed: set[str]) -> bool:
    if isinstance(node, ast.Import):
        return all(alias.name.split(".")[0] in allowed for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        return node.level == 0 and (node.module or "").split(".")[0] in allowed
    return False


def extract_functions(
    code_cells: Iterable[str],
    names: Iterable[str],
    allowed_imports: Iterable[str] = DEFAULT_ALLOWED_IMPORTS,
) -> ExtractedFunctions:
    """Cut the named top-level functions out of a notebook's code cells.

    The last definition of a name wins, as it would in the kernel.
    """
    wanted = list(names)
    allowed = set(allowed_imports)
    found = ExtractedFunctions()
    for number, raw in enumerate(code_cells, start=1):
        parsed = _parse_cell(_clean_cell(raw or ""))
        if parsed is None:
            continue
        for node in _top_level(parsed[0]):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if _allowed_import(node, allowed):
                    source = ast.unparse(node)
                    if source not in found.imports:
                        found.imports.append(source)
                continue
            if isinstance(node, ast.AsyncFunctionDef) and node.name in wanted:
                found.functions.pop(node.name, None)
                found.rejected[node.name] = "defined as async"
                continue
            if not isinstance(node, ast.FunctionDef) or node.name not in wanted:
                continue
            clean, reason = _sanitise(node)
            if clean is None:
                found.functions.pop(node.name, None)
                found.rejected[node.name] = reason
                continue
            found.rejected.pop(node.name, None)
            found.functions[node.name] = ast.unparse(clean)
            found.cells[node.name] = number
    found.missing = [
        name for name in wanted
        if name not in found.functions and name not in found.rejected
    ]
    return found


# ---------------------------------------------------------------------------
# Execution (inside the network-less container only)
# ---------------------------------------------------------------------------

def build_command(sandbox: Path, config: ExecutionConfig) -> list[str]:
    return [
        "docker", "run", "--rm",
        "--name", f"musa-functions-{sandbox.parent.name}"[:60],
        *sandbox_isolation_flags(config),
        "--workdir", "/functions",
        # Only the scratch directory: the submission itself is not mounted.
        "-v", f"{sandbox}:/functions:rw",
        config.docker_image,
        "python", f"/functions/{RUNNER_NAME}",
        "/functions/payload.json", "/functions/results.json",
    ]


def run_isolated_functions(
    workdir: str | Path,
    extracted: ExtractedFunctions,
    cases: list[dict[str, Any]],
    config: ExecutionConfig,
    case_timeout: int = 5,
    hard_timeout: int = 120,
) -> FunctionTestRun:
    """Call each case's function with its arguments, in the sandbox.

    ``cases`` carry ``id``, ``function`` and ``args`` only; whatever else the
    caller keeps (the expected value) is not sent.
    """
    if config.mode != MODE_DOCKER:
        return FunctionTestRun(
            status=STATUS_SKIPPED,
            reason=(
                "Functions are only run in the Docker sandbox, which has no network. "
                f"This run uses {config.mode} mode, so they were not called."
            ),
            extracted=extracted,
        )
    if not extracted.functions:
        return FunctionTestRun(
            status=STATUS_SKIPPED,
            reason="None of the functions could be extracted, so there was nothing to run.",
            extracted=extracted,
        )

    sandbox = Path(workdir) / SANDBOX_DIRNAME
    if sandbox.exists():
        shutil.rmtree(sandbox)
    sandbox.mkdir(parents=True)
    payload = {
        "imports": extracted.imports,
        "functions": extracted.functions,
        "cases": [
            {"id": c["id"], "function": c["function"], "args": list(c.get("args", []))}
            for c in cases if c.get("function") in extracted.functions
        ],
        "case_timeout": case_timeout,
    }
    (sandbox / "payload.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    shutil.copy2(RUNNER_SOURCE, sandbox / RUNNER_NAME)

    command = build_command(sandbox, config)
    run = FunctionTestRun(status=STATUS_ERROR, extracted=extracted, command=command)
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=hard_timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "rm", "-f", command[3]], capture_output=True, check=False)
        run.reason = f"the sandbox did not finish within {hard_timeout}s"
        return run
    except FileNotFoundError as exc:
        run.reason = f"could not start Docker: {exc}"
        return run

    results = sandbox / "results.json"
    if not results.exists():
        run.reason = truncate(
            f"the sandbox produced no result (exit code {completed.returncode}): "
            + (completed.stderr or completed.stdout or ""),
            1500,
        )
        return run
    run.report = json.loads(results.read_text(encoding="utf-8"))
    run.status = STATUS_RAN
    return run


def matches(entry: dict[str, Any] | None, expected: Any, abs_tol: float = 1e-6) -> bool:
    """Did a call return this number? Any numeric type will do: 2, 2.0, np.int64(2)."""
    if not entry or not entry.get("ok"):
        return False
    value = entry.get("value")
    # "2" is not the int 2: the template asks for a number back.
    if isinstance(value, (bool, str)) or value is None:
        return False
    try:
        value = float(value)
        return math.isfinite(value) and abs(value - float(expected)) <= abs_tol
    except (TypeError, ValueError):
        return False


__all__ = [
    "DEFAULT_ALLOWED_IMPORTS",
    "ExtractedFunctions",
    "FunctionTestRun",
    "STATUS_ERROR",
    "STATUS_RAN",
    "STATUS_SKIPPED",
    "extract_functions",
    "matches",
    "run_isolated_functions",
]
