"""Standalone notebook runner. Copied into the working directory and executed
as a subprocess — locally with the host interpreter, or inside the grading
container. It must not import anything from the ``grader`` package.

Usage: python _musa_runner.py <notebook> <artifacts_dir> <cell_timeout_seconds>
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path


def main() -> int:
    notebook_path = Path(sys.argv[1])
    artifacts = Path(sys.argv[2])
    cell_timeout = int(float(sys.argv[3])) if len(sys.argv) > 3 else 300
    artifacts.mkdir(parents=True, exist_ok=True)

    record = {
        "success": False,
        "execution_time_seconds": 0.0,
        "timeout": False,
        "error_cell": None,
        "error_message": None,
        "traceback": "",
    }

    try:
        import nbformat
        from nbclient import NotebookClient
        from nbclient.exceptions import CellTimeoutError
    except Exception as exc:  # pragma: no cover - environment problem
        record["error_message"] = f"grading environment is missing nbclient/nbformat: {exc}"
        record["traceback"] = traceback.format_exc()
        (artifacts / "execution.json").write_text(json.dumps(record, indent=2))
        return 2

    started = time.time()
    try:
        nb = nbformat.read(str(notebook_path), as_version=4)
    except Exception as exc:
        record["error_message"] = f"notebook could not be parsed: {exc}"
        record["traceback"] = traceback.format_exc()
        (artifacts / "execution.json").write_text(json.dumps(record, indent=2))
        return 3

    client = NotebookClient(
        nb,
        timeout=cell_timeout,
        kernel_name="python3",
        # Keep going after an error so the probe cells at the end still run and
        # partial grading stays possible (design.md §19).
        allow_errors=True,
        resources={"metadata": {"path": str(notebook_path.parent)}},
    )

    try:
        client.execute()
    except CellTimeoutError as exc:
        record["timeout"] = True
        record["error_message"] = f"execution timed out after {cell_timeout}s"
        record["traceback"] = str(exc)[:8000]
    except Exception as exc:
        record["error_message"] = f"{type(exc).__name__}: {exc}"
        record["traceback"] = traceback.format_exc()[:8000]

    record["execution_time_seconds"] = round(time.time() - started, 2)

    # Find the first student cell that errored; probe cells are excluded so a
    # broken probe is never reported as a student mistake.
    code_cell_number = 0
    for cell in nb.cells:
        if cell.get("cell_type") != "code":
            continue
        if cell.get("metadata", {}).get("musa_probe"):
            continue
        code_cell_number += 1
        index = code_cell_number
        for output in cell.get("outputs", []) or []:
            if output.get("output_type") == "error":
                if record["error_cell"] is None:
                    record["error_cell"] = index
                    record["error_message"] = (
                        f"{output.get('ename', 'Error')}: {output.get('evalue', '')}"
                    )
                    record["traceback"] = "\n".join(output.get("traceback", []))[:8000]
                break
        if record["error_cell"] is not None:
            break

    record["success"] = (
        record["error_cell"] is None and not record["timeout"] and not record["error_message"]
    )

    try:
        nbformat.write(nb, str(artifacts / "executed.ipynb"))
    except Exception as exc:  # pragma: no cover - defensive
        record.setdefault("warnings", []).append(f"could not save executed notebook: {exc}")

    (artifacts / "execution.json").write_text(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
