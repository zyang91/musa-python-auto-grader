"""Session state for the Streamlit app.

The UI holds no grading logic — it holds a service, a session and a little
bookkeeping (design.md §4).
"""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from typing import Any, Iterable

import streamlit as st

from grader.executor import MODE_DOCKER, MODE_LOCAL, docker_available, docker_image_exists
from grader.llm import build_grader
from grader.models import GradingProgress
from grader.results import GradingSession, list_sessions
from grader.rubric import available_rubrics, load_rubric
from grader.service import GraderSettings, GradingService, LoadedSubmissions

# Uploaded data files live here so they survive reruns and app restarts.
DATA_DIR = Path(__file__).resolve().parent.parent / ".musa_grader_data"

PAGES = [
    "🏠 Overview",
    "📥 Submissions",
    "▶ Grading",
    "👥 Students",
    "⚠ Review Queue",
    "📊 Class Analytics",
    "📤 Export",
    "⚙ Settings",
]

DEFAULTS: dict[str, Any] = {
    "page": PAGES[0],
    # Navigation requested from a button; applied to the radio on the next run,
    # because a widget's own state wins over a recomputed index.
    "pending_page": None,
    "assignment_id": None,
    "loaded": None,
    "session": None,
    "progress": None,
    "grading_thread": None,
    "cancel_event": None,
    "selected_student": None,
    "student_filter": "All",
    "student_search": "",
    "toast": None,
    "last_error": None,
}


def init() -> None:
    for key, value in DEFAULTS.items():
        st.session_state.setdefault(key, value)
    if "settings" not in st.session_state:
        st.session_state.settings = GraderSettings(
            execution_mode=MODE_DOCKER if docker_available() else MODE_LOCAL
        )
    rubrics = available_rubrics()
    if st.session_state.assignment_id is None and rubrics:
        st.session_state.assignment_id = sorted(rubrics)[0]


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------

def settings() -> GraderSettings:
    return st.session_state.settings


def rubric_choices() -> dict[str, Path]:
    return available_rubrics()


def load_rubric_safe(path):
    try:
        return load_rubric(path)
    except Exception:
        return None


def current_rubric():
    choices = rubric_choices()
    assignment_id = st.session_state.assignment_id
    if not assignment_id or assignment_id not in choices:
        return None
    return load_rubric(choices[assignment_id])


def service() -> GradingService | None:
    rubric = current_rubric()
    if rubric is None:
        return None
    return GradingService(
        rubric,
        settings(),
        qualitative_grader=build_grader(settings().to_dict()),
    )


def loaded() -> LoadedSubmissions | None:
    return st.session_state.loaded


def session() -> GradingSession | None:
    return st.session_state.session


def set_page(page: str) -> None:
    st.session_state.pending_page = page


def apply_pending_page() -> None:
    """Called before the navigation widget is created."""
    pending = st.session_state.get("pending_page")
    if pending:
        st.session_state.nav_radio = pending
        st.session_state.page = pending
        st.session_state.pending_page = None


def open_student(student_id: str) -> None:
    st.session_state.selected_student = student_id
    set_page("👥 Students")


def notify(message: str) -> None:
    st.session_state.toast = message


def drain_toast() -> str | None:
    message = st.session_state.toast
    st.session_state.toast = None
    return message


# ---------------------------------------------------------------------------
# Submission loading
# ---------------------------------------------------------------------------

def set_shared_data(paths: list[str]) -> None:
    """Replace the instructor-supplied data files, expanding `~` for the user."""
    settings().shared_data_paths = _dedupe(
        str(Path(p).expanduser()) for p in paths if str(p).strip()
    )


def add_data_files(paths: Iterable[str]) -> None:
    """Add files, keeping the existing ones and ignoring duplicates."""
    settings().shared_data_paths = _dedupe(
        list(settings().shared_data_paths)
        + [str(Path(p).expanduser()) for p in paths if str(p).strip()]
    )


def remove_data_file(path: str) -> None:
    settings().shared_data_paths = [
        p for p in settings().shared_data_paths if p != path
    ]


def _dedupe(paths: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    return [p for p in paths if not (p in seen or seen.add(p))]


def save_uploaded_data(uploaded_file) -> str:
    """Persist an uploaded data file next to the app.

    Streamlit hands the same upload back on every rerun, so an unchanged file is
    written once — re-writing a 117 MB extract on each interaction would make the
    whole UI crawl.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    target = DATA_DIR / Path(uploaded_file.name).name
    size = getattr(uploaded_file, "size", None)
    if not (target.exists() and size is not None and target.stat().st_size == size):
        target.write_bytes(uploaded_file.getbuffer())
    return str(target)


def describe_data_file(path: str) -> str:
    resolved = Path(path)
    if not resolved.is_file():
        return f"⚠ missing: {resolved.name}"
    megabytes = resolved.stat().st_size / 1_048_576
    return f"{resolved.name} ({megabytes:,.0f} MB)"


def preflight() -> list[str]:
    svc = service()
    return svc.preflight() if svc is not None else []


def load_from_path(path: str) -> None:
    svc = service()
    if svc is None:
        st.session_state.last_error = "No rubric is available."
        return
    try:
        st.session_state.loaded = svc.load_submissions(path)
        st.session_state.last_error = None
        notify(f"Found {len(st.session_state.loaded.candidates)} submissions.")
    except Exception as exc:
        st.session_state.loaded = None
        st.session_state.last_error = f"{type(exc).__name__}: {exc}"


def load_from_upload(uploaded_file) -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="musa_upload_"))
    zip_path = temp_dir / Path(uploaded_file.name).name
    zip_path.write_bytes(uploaded_file.getbuffer())
    load_from_path(str(zip_path))


def _upload_identity(uploaded_file) -> str:
    file_id = getattr(uploaded_file, "file_id", None)
    if file_id:
        return str(file_id)
    return f"{uploaded_file.name}:{getattr(uploaded_file, 'size', '')}"


def load_upload_once(uploaded_file) -> bool:
    """Load a newly uploaded ZIP as soon as it arrives.

    Previously the upload also needed a separate "Load ZIP" click, and until that
    click the Run button stayed disabled with no explanation. Streamlit hands the
    same upload back on every rerun, so the identity check keeps a large archive
    from being re-extracted on each interaction. Returns True when it loaded.
    """
    identity = _upload_identity(uploaded_file)
    if st.session_state.get("loaded_upload_id") == identity:
        return False
    st.session_state.loaded_upload_id = identity
    load_from_upload(uploaded_file)
    return True


def run_blockers() -> list[str]:
    """Why the Run button is disabled, in words a TA can act on."""
    reasons: list[str] = []
    if is_grading():
        reasons.append("Grading is already running.")
    current = loaded()
    if current is None:
        reasons.append("Load submissions first: upload a ZIP or load a folder.")
    elif not current.candidates:
        reasons.append("No submissions were found in what you loaded.")
    return reasons


def load_session_from_disk(path: str) -> None:
    try:
        st.session_state.session = GradingSession.load(path)
        st.session_state.selected_student = None
        notify(f"Loaded session {st.session_state.session.session_id}.")
    except Exception as exc:
        st.session_state.last_error = f"Could not load session: {exc}"


def previous_sessions() -> list[dict[str, Any]]:
    return list_sessions()


# ---------------------------------------------------------------------------
# Grading run (background thread so the UI keeps painting, design.md §7)
# ---------------------------------------------------------------------------

def is_grading() -> bool:
    thread = st.session_state.grading_thread
    return bool(thread and thread.is_alive())


def start_grading(preserve_overrides: bool = False) -> None:
    svc = service()
    loaded_submissions = loaded()
    if svc is None or loaded_submissions is None:
        st.session_state.last_error = "Load submissions before running the grader."
        return
    if is_grading():
        return

    progress_holder = GradingProgress(total=len(loaded_submissions.candidates), stage="starting")
    st.session_state.progress = progress_holder
    cancel_event = threading.Event()
    st.session_state.cancel_event = cancel_event

    existing = session()
    snapshot = (
        existing.collect_overrides() if (preserve_overrides and existing is not None) else None
    )
    # Always a named session: without it the saved session forgot its source.
    target_session = svc.new_session(loaded_submissions.source)
    if existing is not None and preserve_overrides:
        target_session.session_id = existing.session_id
        target_session.root = existing.root
        target_session.created_at = existing.created_at

    results_box: dict[str, Any] = {}
    st.session_state.results_box = results_box

    def on_progress(update: GradingProgress) -> None:
        # Copy the mutable snapshot the service reuses between callbacks.
        progress_holder.__dict__.update(update.__dict__)

    def worker() -> None:
        try:
            results_box["session"] = svc.run(
                loaded_submissions.candidates,
                session=target_session,
                progress_callback=on_progress,
                cancel_event=cancel_event,
                preserve_overrides=snapshot,
            )
        except Exception as exc:  # surfaced on the Grading page
            results_box["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            progress_holder.finished = True

    thread = threading.Thread(target=worker, name="musa-grading", daemon=True)
    st.session_state.grading_thread = thread
    thread.start()
    set_page("▶ Grading")


def cancel_grading() -> None:
    event = st.session_state.cancel_event
    if event is not None:
        event.set()


def collect_finished_run() -> None:
    """Move a completed background run into session state."""
    box = st.session_state.get("results_box") or {}
    if is_grading():
        return
    if box.get("session") is not None and st.session_state.session is not box["session"]:
        st.session_state.session = box["session"]
        notify("Grading finished.")
    if box.get("error"):
        st.session_state.last_error = box["error"]
        box["error"] = None


# ---------------------------------------------------------------------------
# Environment checks shown in the sidebar
# ---------------------------------------------------------------------------

def execution_warnings() -> list[str]:
    config = settings()
    warnings: list[str] = []
    if config.execution_mode == MODE_DOCKER:
        if not docker_available():
            warnings.append(
                "Docker is not running, so grading will fail. Start Docker, or "
                "switch to Unsafe Local execution."
            )
        elif not docker_image_exists(config.docker_image):
            warnings.append(
                f"The image `{config.docker_image}` is not built yet. Run "
                "`docker build -t musa-grader:latest -f docker/Dockerfile .`"
            )
    else:
        warnings.append(
            "Unsafe Local mode runs student code directly on this machine with no "
            "isolation. Only use it for notebooks you trust."
        )
    return warnings
