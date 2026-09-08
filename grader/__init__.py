"""MUSA Grader — grading engine.

The engine is independent of the UI: ``GradingService`` is the only entry point
Streamlit needs (design.md §4).
"""

__version__ = "0.1.0"

from .models import (  # noqa: F401
    ExecutionRecord,
    GradingProgress,
    RubricItemResult,
    SubmissionResult,
)
from .rubric import Rubric, load_rubric  # noqa: F401
from .service import GraderSettings, GradingService  # noqa: F401

__all__ = [
    "__version__",
    "GradingService",
    "GraderSettings",
    "Rubric",
    "load_rubric",
    "SubmissionResult",
    "RubricItemResult",
    "ExecutionRecord",
    "GradingProgress",
]
