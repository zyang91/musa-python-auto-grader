"""Standalone runner for isolated function tests. Copied into a fresh, otherwise
empty directory and executed inside the network-less grading container by
``grader/function_sandbox.py``. It must not import anything from the ``grader``
package.

It receives function definitions that were already cut out of a student notebook
on the host — never the notebook itself — plus the inputs to call them with. The
expected answers stay on the host; this script only reports what came back.

Usage: python _musa_functions.py <payload.json> <results.json>
"""

from __future__ import annotations

import contextlib
import io
import json
import signal
import sys
import traceback


class CaseTimeout(Exception):
    pass


def _on_alarm(signum, frame):  # pragma: no cover - only fires on a hung call
    raise CaseTimeout("the call did not return in time")


def _describe(value):
    """A JSON-safe account of a return value, keeping its type."""
    kind = type(value).__name__
    plain = value
    if hasattr(value, "item") and not isinstance(value, (list, tuple, dict, str)):
        try:
            plain = value.item()  # numpy scalars
        except Exception:
            plain = value
    if isinstance(plain, bool) or plain is None or isinstance(plain, (int, float, str)):
        jsonable = plain
    else:
        jsonable = None
    try:
        text = repr(value)
    except Exception:
        text = f"<{kind}>"
    return {"value": jsonable, "type": kind, "repr": text[:200]}


def main() -> int:
    payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
    out_path = sys.argv[2]
    timeout = max(int(payload.get("case_timeout", 5)), 1)
    namespace: dict = {"__name__": "__musa_functions__"}
    report: dict = {"imports": [], "definitions": {}, "cases": []}

    use_alarm = hasattr(signal, "SIGALRM")
    if use_alarm:
        signal.signal(signal.SIGALRM, _on_alarm)

    sink = io.StringIO()
    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        for source in payload.get("imports", []):
            try:
                exec(compile(source, "<import>", "exec"), namespace)
                report["imports"].append({"source": source, "ok": True})
            except Exception as exc:
                report["imports"].append(
                    {"source": source, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
                )

        for name, source in payload.get("functions", {}).items():
            try:
                exec(compile(source, f"<{name}>", "exec"), namespace)
                report["definitions"][name] = {"ok": callable(namespace.get(name))}
            except Exception as exc:
                report["definitions"][name] = {
                    "ok": False, "error": f"{type(exc).__name__}: {exc}"
                }

        for case in payload.get("cases", []):
            entry = {"id": case.get("id"), "function": case.get("function")}
            function = namespace.get(case.get("function"))
            if not callable(function):
                entry.update(ok=False, error="function is not defined")
                report["cases"].append(entry)
                continue
            try:
                if use_alarm:
                    signal.alarm(timeout)
                try:
                    value = function(*case.get("args", []))
                finally:
                    if use_alarm:
                        signal.alarm(0)
                entry.update(ok=True, **_describe(value))
            except BaseException as exc:  # a student's sys.exit() is a failure, not ours
                entry.update(
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}"[:300],
                    traceback=traceback.format_exc()[-1500:],
                )
            report["cases"].append(entry)

    report["stdout"] = sink.getvalue()[-2000:]
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
