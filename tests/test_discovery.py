"""Submission discovery (design.md §16-17)."""

from __future__ import annotations

import zipfile

from grader.discovery import (
    REASON_MULTIPLE_NOTEBOOKS,
    REASON_NO_NOTEBOOK,
    choose_notebook,
    discover_submissions,
    parse_canvas_filename,
    prepare_workdir,
)


def _touch(path, content="{}"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_folder_layout(tmp_path):
    _touch(tmp_path / "student_001" / "assignment1.ipynb")
    _touch(tmp_path / "student_001" / "data" / "values.csv", "a,b\n1,2\n")
    _touch(tmp_path / "student_002" / "homework1.ipynb")

    candidates = discover_submissions(tmp_path)
    assert [c.student_id for c in candidates] == ["student_001", "student_002"]
    assert candidates[0].notebook_path.name == "assignment1.ipynb"
    assert len(candidates[0].data_files) == 1


def test_checkpoints_are_ignored(tmp_path):
    _touch(tmp_path / "student_001" / "hw1.ipynb")
    _touch(tmp_path / "student_001" / ".ipynb_checkpoints" / "hw1-checkpoint.ipynb")
    candidate = discover_submissions(tmp_path)[0]
    assert len(candidate.all_notebooks) == 1


def test_ambiguous_notebooks_are_flagged_not_guessed(tmp_path):
    _touch(tmp_path / "student_001" / "part_one.ipynb", "{}" + " " * 500)
    _touch(tmp_path / "student_001" / "part_two.ipynb", "{}" + " " * 500)
    candidate = discover_submissions(tmp_path)[0]
    assert REASON_MULTIPLE_NOTEBOOKS in candidate.review_reasons
    assert candidate.notebook_path is not None  # still graded, but flagged


def test_name_hints_break_a_tie(tmp_path):
    _touch(tmp_path / "student_001" / "scratch.ipynb")
    _touch(tmp_path / "student_001" / "musa5500_hw1.ipynb")
    candidate = discover_submissions(
        tmp_path, notebook_hints=["hw1"], ignore_patterns=["scratch"]
    )[0]
    assert candidate.notebook_path.name == "musa5500_hw1.ipynb"
    assert candidate.review_reasons == []


def test_missing_notebook(tmp_path):
    (tmp_path / "student_001").mkdir()
    (tmp_path / "student_001" / "README.txt").write_text("oops")
    candidate = discover_submissions(tmp_path)[0]
    assert candidate.ok is False
    assert REASON_NO_NOTEBOOK in candidate.review_reasons


def test_canvas_flat_export(tmp_path):
    _touch(tmp_path / "doejane_late_12345_67890_assignment1.ipynb")
    _touch(tmp_path / "smithjohn_998877_112233_hw1.ipynb")
    candidates = discover_submissions(tmp_path)
    by_id = {c.student_id: c for c in candidates}
    assert set(by_id) == {"doejane", "smithjohn"}
    assert by_id["doejane"].late is True


def test_parse_canvas_filename():
    assert parse_canvas_filename("doejane_late_1_2_hw1.ipynb") == ("doejane", "doejane", True)
    student_id, _, late = parse_canvas_filename("notcanvas.ipynb")
    assert student_id == "notcanvas" and late is False


def test_zip_with_wrapper_folder_is_unwrapped(tmp_path):
    root = tmp_path / "src" / "canvas_download" / "student_001"
    _touch(root / "hw1.ipynb")
    archive = tmp_path / "download.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.write(root / "hw1.ipynb", "canvas_download/student_001/hw1.ipynb")

    from grader.discovery import extract_zip

    extracted = extract_zip(archive, tmp_path / "out")
    candidates = discover_submissions(extracted)
    assert [c.student_id for c in candidates] == ["student_001"]


def test_zip_path_traversal_is_refused(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../escaped.ipynb", "{}")
        handle.writestr("student_001/hw1.ipynb", "{}")

    from grader.discovery import extract_zip

    extract_zip(archive, tmp_path / "out")
    assert not (tmp_path / "escaped.ipynb").exists()


def test_prepare_workdir_normalises_the_notebook_name(tmp_path):
    _touch(tmp_path / "student_001" / "weird name.ipynb", "{}")
    _touch(tmp_path / "student_001" / "data" / "values.csv", "a\n1\n")
    candidate = discover_submissions(tmp_path)[0]

    workdir = prepare_workdir(candidate, tmp_path / "work")
    assert (workdir / "notebook.ipynb").exists()
    assert (workdir / "data" / "values.csv").exists()
    # Other notebooks are not copied into the execution directory.
    assert not (workdir / "weird name.ipynb").exists()


def test_choose_notebook_prefers_shallower_files(tmp_path):
    deep = _touch(tmp_path / "a" / "b" / "hw1.ipynb", "{}" + " " * 100)
    shallow = _touch(tmp_path / "hw1.ipynb", "{}" + " " * 100)
    chosen, reasons = choose_notebook([deep, shallow], ["hw1"], [], root=tmp_path)
    assert chosen == shallow or REASON_MULTIPLE_NOTEBOOKS in reasons
