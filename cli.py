"""Headless grading, for scripted runs and smoke tests.

The Streamlit app is the intended interface (design.md §38); this exists so a
grading run can also happen from a terminal or in CI.

    python cli.py grade examples/submissions --mode local
    python cli.py sessions
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from grader.executor import MODE_DOCKER, MODE_LOCAL, docker_available
from grader.feedback import build_class_report, summary_line
from grader.results import list_sessions
from grader.rubric import available_rubrics
from grader.service import GraderSettings, GradingService


def cmd_grade(args: argparse.Namespace) -> int:
    rubric_path = Path(args.rubric)
    if not rubric_path.exists():
        print(f"Rubric not found: {rubric_path}", file=sys.stderr)
        return 2

    if args.mode == MODE_DOCKER and not docker_available():
        print(
            "Docker is not available. Start Docker, or re-run with --mode local "
            "(which executes student code on this machine without isolation).",
            file=sys.stderr,
        )
        return 2

    settings = GraderSettings(
        shared_data_paths=[str(Path(p).expanduser()) for p in (args.data or [])],
        execution_mode=args.mode,
        docker_image=args.image,
        cell_timeout_seconds=args.cell_timeout,
        timeout_seconds=args.timeout,
        confidence_threshold=args.confidence_threshold,
    )
    service = GradingService.from_rubric_path(rubric_path, settings)
    for problem in service.preflight():
        print(f"warning: {problem}", file=sys.stderr)

    loaded = service.load_submissions(args.submissions)
    print(f"{len(loaded.candidates)} submissions found in {loaded.source}")

    def on_progress(progress):
        if progress.current_student and progress.stage == "execution":
            print(
                f"[{progress.completed + 1}/{progress.total}] {progress.current_student}",
                flush=True,
            )

    session = service.run(loaded.candidates, progress_callback=on_progress)
    print()
    for result in session.ordered_results():
        print(summary_line(result))
    print()
    print(build_class_report(session.summary(), session.assignment_name))
    print(f"\nSaved to {session.root}")
    return 0


def cmd_sessions(_: argparse.Namespace) -> int:
    sessions = list_sessions()
    if not sessions:
        print("No grading sessions yet.")
        return 0
    for entry in sessions:
        print(
            f"{entry['session_id']:<28} {entry['assignment_name']:<16}"
            f"{entry['submissions']:>4} submissions  {entry['updated_at']}"
        )
    return 0


def cmd_rubrics(_: argparse.Namespace) -> int:
    for assignment_id, path in available_rubrics().items():
        print(f"{assignment_id:<8} {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="musa-grader", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    grade = subparsers.add_parser("grade", help="grade a folder or Canvas ZIP")
    grade.add_argument("submissions", help="submissions folder or Canvas export ZIP")
    grade.add_argument("--rubric", default="rubrics/hw1.yaml")
    grade.add_argument(
        "--data", action="append", metavar="PATH",
        help="assignment data file to place into every submission; repeatable. "
             "Students submit notebooks only, so this is normally required.",
    )
    grade.add_argument("--mode", choices=[MODE_DOCKER, MODE_LOCAL], default=MODE_DOCKER,
                       help="'local' runs student code without isolation")
    grade.add_argument("--image", default="musa-grader:latest")
    grade.add_argument("--timeout", type=int, default=600)
    grade.add_argument("--cell-timeout", type=int, default=300)
    grade.add_argument("--confidence-threshold", type=float, default=0.8)
    grade.set_defaults(func=cmd_grade)

    subparsers.add_parser("sessions", help="list saved grading sessions").set_defaults(
        func=cmd_sessions
    )
    subparsers.add_parser("rubrics", help="list available rubrics").set_defaults(
        func=cmd_rubrics
    )

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
