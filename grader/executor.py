"""Notebook execution (design.md §18-19).

Two modes share one code path: the notebook is instrumented with probe cells,
written into an isolated working directory, and executed by a subprocess. Docker
is the default because student code is untrusted; local execution exists for
machines without Docker and is labelled unsafe everywhere it appears.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import nbformat
from nbformat.v4 import new_code_cell

from .models import ExecutionRecord
from .probe_runtime import MUSA_PROBE_MARKER
from .utils import truncate

MODE_DOCKER = "docker"
MODE_LOCAL = "local"

PACKAGE_DIR = Path(__file__).resolve().parent
RUNNER_SOURCE = PACKAGE_DIR / "notebook_runner.py"
PROBE_SOURCE = PACKAGE_DIR / "probe_runtime.py"

INSTRUMENTED_NAME = "_musa_instrumented.ipynb"
RUNNER_NAME = "_musa_runner.py"
ARTIFACTS_DIRNAME = "_musa_artifacts"

DEFAULT_IMAGE = "musa-grader:latest"


@dataclass
class ExecutionConfig:
    mode: str = MODE_DOCKER
    docker_image: str = DEFAULT_IMAGE
    timeout_seconds: int = 600
    cell_timeout_seconds: int = 300
    memory_limit: str = "2g"
    cpu_limit: str = "1.0"

    @property
    def hard_timeout(self) -> int:
        # The outer subprocess bound must outlive the per-cell bound.
        return max(self.timeout_seconds, self.cell_timeout_seconds + 60)


class ExecutionError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Instrumentation
# ---------------------------------------------------------------------------

def build_probe_cells(probe_config: dict[str, Any]) -> list[Any]:
    """Return the notebook cells that dump the student's namespace to JSON."""
    probe_source = PROBE_SOURCE.read_text(encoding="utf-8")
    # ``from __future__`` must be the first statement in a module, not a cell.
    probe_source = probe_source.replace("from __future__ import annotations\n", "")
    config_json = json.dumps(probe_config)

    setup = new_code_cell(
        "# --- MUSA Grader probe (added by the autograder, not by the student) ---\n"
        + probe_source
    )
    invoke = new_code_cell(
        "# --- MUSA Grader probe: collect namespace summary and hidden test results ---\n"
        "import json as _musa_json\n"
        "_musa_config = _musa_json.loads(r'''" + config_json + "''')\n"
        "try:\n"
        "    _musa_probe_main(globals(), _musa_config)\n"
        "except Exception as _musa_exc:\n"
        "    print('MUSA probe failed:', _musa_exc)\n"
    )
    for cell in (setup, invoke):
        cell.metadata["musa_probe"] = True
        cell.metadata["tags"] = ["musa-probe"]
    return [setup, invoke]


URL_REDIRECT_TEMPLATE = r'''# --- MUSA Grader: the grading run is offline; URLs of supplied data files read the local copy ---
def _musa_install_url_redirects(redirects):
    import functools
    import os
    import urllib.parse

    path_keywords = ("filepath_or_buffer", "path_or_buf", "io", "path", "filename")

    def resolve(target):
        if isinstance(target, str) and target.lower().startswith(("http://", "https://")):
            name = os.path.basename(urllib.parse.urlparse(target).path)
            return redirects.get(name, target)
        return target

    def wrap(module, attribute):
        original = getattr(module, attribute, None)
        if original is None or getattr(original, "_musa_redirect", False):
            return

        @functools.wraps(original)
        def patched(*args, **kwargs):
            if args:
                args = (resolve(args[0]),) + tuple(args[1:])
            else:
                for key in path_keywords:
                    if key in kwargs:
                        kwargs[key] = resolve(kwargs[key])
                        break
            return original(*args, **kwargs)

        patched._musa_redirect = True
        setattr(module, attribute, patched)

    try:
        import pandas
        for attribute in ("read_csv", "read_table", "read_json", "read_excel", "read_parquet"):
            wrap(pandas, attribute)
    except Exception:
        pass
    try:
        import geopandas
        wrap(geopandas, "read_file")
    except Exception:
        pass


_musa_install_url_redirects(__REDIRECTS__)
del _musa_install_url_redirects
'''


def build_url_redirect_cell(redirects: dict[str, str]) -> Any:
    """A first cell that points data URLs at the supplied local file.

    The container has no network, by design. A student who loads the data
    straight from Zillow's URL is following a reasonable pattern, so a URL whose
    filename matches a file the instructor supplied is read from that local copy;
    any other URL still fails exactly as it would offline.
    """
    source = URL_REDIRECT_TEMPLATE.replace("__REDIRECTS__", repr(dict(redirects)))
    cell = new_code_cell(source)
    cell.metadata["musa_probe"] = True
    cell.metadata["tags"] = ["musa-probe"]
    return cell


def instrument_notebook(
    notebook_path: str | Path,
    probe_config: dict[str, Any],
    output_path: str | Path,
    url_redirects: dict[str, str] | None = None,
) -> Path:
    """Append probe cells (and, if needed, prepend URL redirects) to a copy."""
    notebook_path, output_path = Path(notebook_path), Path(output_path)
    nb = nbformat.read(str(notebook_path), as_version=4)
    # Clear stale outputs so what we grade is what this run produced.
    for cell in nb.cells:
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
    if url_redirects:
        nb.cells.insert(0, build_url_redirect_cell(url_redirects))
    nb.cells.extend(build_probe_cells(probe_config))
    nbformat.write(nb, str(output_path))
    return output_path


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=20, check=False
        )
        return result.returncode == 0
    except Exception:
        return False


def docker_image_exists(image: str) -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image], capture_output=True, timeout=20, check=False
        )
        return result.returncode == 0
    except Exception:
        return False


def execute_submission(
    workdir: str | Path,
    probe_config: dict[str, Any],
    config: ExecutionConfig,
    run_subdir: str = "",
) -> tuple[ExecutionRecord, dict[str, Any] | None]:
    """Execute one prepared submission. Returns (execution record, probe payload).

    ``run_subdir`` is where inside ``workdir`` the notebook runs from (see
    ``prepare_workdir``); artifacts always go to ``workdir/_musa_artifacts``.
    """
    workdir = Path(workdir)
    run_dir = workdir / run_subdir if run_subdir else workdir
    notebook = run_dir / "notebook.ipynb"
    if not notebook.exists():
        return (
            ExecutionRecord(mode=config.mode, attempted=False,
                            error_message="no notebook was prepared for execution"),
            None,
        )

    artifacts = workdir / ARTIFACTS_DIRNAME
    artifacts.mkdir(parents=True, exist_ok=True)
    probe_config = dict(probe_config)
    url_redirects = probe_config.pop("url_redirects", None) or {}
    probe_config["out_dir"] = _container_path(artifacts, workdir, config)

    instrument_notebook(
        notebook, probe_config, run_dir / INSTRUMENTED_NAME, url_redirects=url_redirects
    )
    shutil.copy2(RUNNER_SOURCE, run_dir / RUNNER_NAME)

    command = _build_command(workdir, config, run_subdir)
    record = ExecutionRecord(mode=config.mode, attempted=True)

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=config.hard_timeout,
            cwd=str(workdir),
            check=False,
        )
        stdout, stderr, returncode = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as exc:
        record.timeout = True
        record.success = False
        record.error_message = f"execution exceeded the {config.hard_timeout}s hard limit"
        record.log = truncate(_decode(exc.stdout) + "\n" + _decode(exc.stderr), 8000)
        _cleanup_container(workdir, config)
        return record, _read_probe(artifacts, record.log)
    except FileNotFoundError as exc:
        record.success = False
        record.error_message = f"could not start the execution backend: {exc}"
        return record, None

    raw_log = (stdout or "") + ("\n" + stderr if stderr else "")
    # The probe dumps a large JSON blob to stdout as a fallback; keep it out of
    # the log the TA reads, but still parse it below.
    record.log = truncate(raw_log.split(MUSA_PROBE_MARKER, 1)[0].rstrip(), 20000)

    execution_json = artifacts / "execution.json"
    if execution_json.exists():
        data = json.loads(execution_json.read_text(encoding="utf-8"))
        record.success = bool(data.get("success"))
        record.execution_time_seconds = float(data.get("execution_time_seconds", 0.0))
        record.timeout = bool(data.get("timeout"))
        record.error_cell = data.get("error_cell")
        record.error_message = data.get("error_message")
        record.traceback = data.get("traceback", "")
    else:
        record.success = False
        record.error_message = (
            f"the runner produced no result (exit code {returncode}). "
            "Check the execution log."
        )

    executed = artifacts / "executed.ipynb"
    if executed.exists():
        strip_probe_cells(executed)
        record.executed_notebook_path = str(executed)

    return record, _read_probe(artifacts, raw_log)


def strip_probe_cells(notebook_path: str | Path) -> Path:
    """Remove the injected cells so the saved notebook is the student's work."""
    notebook_path = Path(notebook_path)
    try:
        nb = nbformat.read(str(notebook_path), as_version=4)
    except Exception:  # pragma: no cover - defensive
        return notebook_path
    nb.cells = [
        cell for cell in nb.cells if not cell.get("metadata", {}).get("musa_probe")
    ]
    nbformat.write(nb, str(notebook_path))
    return notebook_path


def _decode(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _container_path(artifacts: Path, workdir: Path, config: ExecutionConfig) -> str:
    if config.mode == MODE_DOCKER:
        return f"/grading/{artifacts.relative_to(workdir).as_posix()}"
    return str(artifacts)


def _build_command(workdir: Path, config: ExecutionConfig, run_subdir: str = "") -> list[str]:
    if config.mode == MODE_DOCKER:
        run = f"/grading/{run_subdir}" if run_subdir else "/grading"
        return [
            "docker", "run", "--rm",
            "--name", f"musa-grader-{workdir.name}"[:60],
            # Isolation requirements from design.md §18.
            "--network", "none",
            "--memory", config.memory_limit,
            "--memory-swap", config.memory_limit,
            "--cpus", str(config.cpu_limit),
            "--pids-limit", "256",
            "--read-only",
            "--tmpfs", "/tmp:rw,size=256m",
            "--env", "HOME=/tmp",
            # Not Agg: under Agg a figure is never displayed, so a chart the
            # student drew leaves no image in the notebook to grade.
            "--env", "MPLBACKEND=module://matplotlib_inline.backend_inline",
            "--env", "MPLCONFIGDIR=/tmp/mpl",
            "--workdir", run,
            "-v", f"{workdir}:/grading:rw",
            config.docker_image,
            "python", f"{run}/{RUNNER_NAME}",
            f"{run}/{INSTRUMENTED_NAME}",
            f"/grading/{ARTIFACTS_DIRNAME}",
            str(config.cell_timeout_seconds),
        ]
    run_dir = workdir / run_subdir if run_subdir else workdir
    return [
        sys.executable,
        str(run_dir / RUNNER_NAME),
        str(run_dir / INSTRUMENTED_NAME),
        str(workdir / ARTIFACTS_DIRNAME),
        str(config.cell_timeout_seconds),
    ]


def _cleanup_container(workdir: Path, config: ExecutionConfig) -> None:
    if config.mode != MODE_DOCKER:
        return
    name = f"musa-grader-{workdir.name}"[:60]
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)


def _read_probe(artifacts: Path, log: str) -> dict[str, Any] | None:
    """Prefer the artifact file; fall back to the marker printed to stdout."""
    path = artifacts / "probe_results.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    if MUSA_PROBE_MARKER in (log or ""):
        blob = log.split(MUSA_PROBE_MARKER, 1)[1].strip().splitlines()
        for line in blob:
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
    return None
