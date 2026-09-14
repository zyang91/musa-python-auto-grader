"""Instructor-supplied data: uploads, the in-use list, and placement.

The UI's file picker cannot be driven from a test, so the helpers behind it are
tested directly.
"""

from __future__ import annotations

import io

import pytest

from grader.discovery import place_shared_data
from grader.service import GraderSettings, GradingService
from grader.rubric import load_rubric


class StubUpload:
    """Stands in for Streamlit's UploadedFile."""

    def __init__(self, name: str, payload: bytes):
        self.name = name
        self._payload = payload
        self.size = len(payload)
        self.reads = 0

    def getbuffer(self):
        self.reads += 1
        return self._payload


@pytest.fixture
def state(monkeypatch, tmp_path):
    """ui.state without a live Streamlit session."""
    import ui.state as module

    settings = GraderSettings()
    monkeypatch.setattr(module, "settings", lambda: settings)
    monkeypatch.setattr(module, "DATA_DIR", tmp_path / "uploads")
    return module, settings


def test_uploaded_file_is_written_once(state):
    module, settings = state
    upload = StubUpload("zhvi.csv", b"RegionName,City\n19102,Philadelphia\n")

    first = module.save_uploaded_data(upload)
    second = module.save_uploaded_data(upload)

    assert first == second
    # Streamlit replays the same upload on every rerun; a 117 MB file must not
    # be rewritten each time.
    assert upload.reads == 1
    assert open(first, "rb").read() == upload.getbuffer()


def test_a_changed_upload_replaces_the_file(state):
    module, _ = state
    path = module.save_uploaded_data(StubUpload("zhvi.csv", b"old"))
    module.save_uploaded_data(StubUpload("zhvi.csv", b"much longer new content"))
    assert open(path, "rb").read() == b"much longer new content"


def test_upload_name_cannot_escape_the_data_directory(state, tmp_path):
    module, _ = state
    path = module.save_uploaded_data(StubUpload("../../evil.csv", b"x"))
    assert path.endswith("/uploads/evil.csv")
    assert not (tmp_path / "evil.csv").exists()


def test_files_accumulate_without_duplicates(state):
    module, settings = state
    module.add_data_files(["/tmp/a.csv"])
    module.add_data_files(["/tmp/b.csv", "/tmp/a.csv"])
    assert settings.shared_data_paths == ["/tmp/a.csv", "/tmp/b.csv"]


def test_a_file_can_be_removed(state):
    module, settings = state
    module.add_data_files(["/tmp/a.csv", "/tmp/b.csv"])
    module.remove_data_file("/tmp/a.csv")
    assert settings.shared_data_paths == ["/tmp/b.csv"]


def test_home_relative_paths_are_expanded(state):
    module, settings = state
    module.add_data_files(["~/Downloads/zhvi.csv"])
    assert settings.shared_data_paths[0].startswith("/")
    assert "~" not in settings.shared_data_paths[0]


def test_describe_reports_size_and_missing_files(state, tmp_path):
    module, _ = state
    present = tmp_path / "zhvi.csv"
    present.write_bytes(b"x" * 2_100_000)
    assert "2 MB" in module.describe_data_file(str(present))
    assert module.describe_data_file(str(tmp_path / "gone.csv")).startswith("⚠ missing")


def test_several_files_are_placed_by_best_name_match(tmp_path):
    """Assignments with more than one data file still land in the right places."""
    zhvi = tmp_path / "Zip_zhvi_uc_sfrcondo.csv"
    tracts = tmp_path / "Census_Tracts_2010.geojson"
    zhvi.write_text("a\n")
    tracts.write_text("{}\n")
    workdir = tmp_path / "work"
    workdir.mkdir()

    report = place_shared_data(
        workdir, [zhvi, tracts],
        referenced_paths=["data/zhvi.csv", "data/tracts.geojson"],
    )
    placed = {entry["path"]: entry["source"] for entry in report["placed"]}
    assert placed["data/zhvi.csv"] == zhvi.name
    assert placed["data/tracts.geojson"] == tracts.name


def test_preflight_clears_once_a_file_is_supplied(tmp_path):
    rubric = load_rubric("rubrics/hw1.yaml")
    data = tmp_path / "zhvi.csv"
    data.write_text("a\n")

    assert GradingService(rubric, GraderSettings()).preflight()
    supplied = GraderSettings(shared_data_paths=[str(data)])
    assert GradingService(rubric, supplied).preflight() == []


# ---------------------------------------------------------------------------
# Submission ZIP upload: loads on arrival, once, and explains a disabled Run
# ---------------------------------------------------------------------------

@pytest.fixture
def upload_state(monkeypatch):
    """ui.state with a dict standing in for st.session_state."""
    import ui.state as module

    session = {"loaded": None, "last_error": None, "grading_thread": None}

    class SessionState(dict):
        __getattr__ = dict.get

        def __setattr__(self, key, value):
            self[key] = value

    fake = SessionState(session)
    monkeypatch.setattr(module.st, "session_state", fake)
    calls = []
    monkeypatch.setattr(module, "load_from_upload", lambda upload: calls.append(upload.name))
    return module, fake, calls


def test_an_uploaded_zip_loads_without_a_second_click(upload_state):
    module, _, calls = upload_state
    assert module.load_upload_once(StubUpload("canvas.zip", b"PK")) is True
    assert calls == ["canvas.zip"]


def test_the_same_upload_is_not_reextracted_on_every_rerun(upload_state):
    module, _, calls = upload_state
    upload = StubUpload("canvas.zip", b"PK")
    module.load_upload_once(upload)
    assert module.load_upload_once(upload) is False
    assert calls == ["canvas.zip"]


def test_a_different_upload_loads_again(upload_state):
    module, _, calls = upload_state
    module.load_upload_once(StubUpload("week1.zip", b"PK"))
    module.load_upload_once(StubUpload("week2.zip", b"PK12"))
    assert calls == ["week1.zip", "week2.zip"]


def test_run_blockers_explain_why_run_is_disabled(upload_state):
    from grader.service import LoadedSubmissions

    module, session, _ = upload_state
    assert any("Load submissions first" in r for r in module.run_blockers())

    session["loaded"] = LoadedSubmissions(source="empty.zip", candidates=[])
    assert any("No submissions were found" in r for r in module.run_blockers())

    session["loaded"] = LoadedSubmissions(source="canvas.zip", candidates=[object()])
    assert module.run_blockers() == []
