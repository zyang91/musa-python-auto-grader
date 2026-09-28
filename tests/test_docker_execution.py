"""The same correct submission as test_integration, executed in the sandbox image.

Every other test runs notebooks with ``--mode local``, which is not how a class is
graded. This one catches what only the container can break: a package missing
from docker/requirements-sandbox.txt, a pin bumped to a release that no longer
installs, or a file permission the container user cannot read.

Skipped unless the image is built (``docker build -t musa-grader:latest -f
docker/Dockerfile .``); CI builds it and runs ``pytest -m docker``.
"""

from __future__ import annotations

import importlib.util

import pytest

from grader.executor import DEFAULT_IMAGE, MODE_DOCKER, docker_image_exists
from grader.service import GraderSettings, GradingService

pytestmark = [
    pytest.mark.slow,
    pytest.mark.docker,
    pytest.mark.skipif(
        not docker_image_exists(DEFAULT_IMAGE), reason=f"{DEFAULT_IMAGE} is not built"
    ),
]


def test_correct_submission_scores_full_marks_in_the_sandbox(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "make_example_submissions", "examples/make_example_submissions.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    submissions = module.build_submissions(tmp_path / "submissions")

    settings = GraderSettings(
        execution_mode=MODE_DOCKER, docker_image=DEFAULT_IMAGE,
        cell_timeout_seconds=120, timeout_seconds=300,
        shared_data_paths=["examples/data/zillow_zhvi.csv"],
    )
    service = GradingService.from_rubric_path("rubrics/hw1.yaml", settings)
    loaded = service.load_submissions(submissions)
    good = [c for c in loaded.candidates if c.student_id == "student_001"]
    session = service.new_session(loaded.source)
    session.root = tmp_path / session.session_id
    session = service.run(good, session=session)

    result = session.results["student_001"]
    assert result.execution.success is True, result.execution.error_message
    assert result.execution.mode == MODE_DOCKER
    assert result.total_score == 100
