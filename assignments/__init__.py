"""Per-assignment graders. Importing the package registers every grader."""

from .base import AssignmentGrader, GradingContext, get_grader, registered_assignments  # noqa: F401
from . import hw1  # noqa: F401,E402  (registers HW1Grader)

__all__ = ["AssignmentGrader", "GradingContext", "get_grader", "registered_assignments"]
