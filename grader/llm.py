"""Optional LLM-assisted qualitative grading (design.md §26).

Nothing in the engine requires this module to do anything: the default grader is
disabled, and a disabled grader means qualitative items fall back to structural
scoring plus human review.

Two rules are enforced here rather than left to the caller:
  * student names never reach the provider — only the response text,
  * a low-confidence judgement is always routed to a human.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Protocol

DEFAULT_REVIEW_THRESHOLD = 0.80

SYSTEM_PROMPT = (
    "You are helping a teaching assistant grade short written answers in a "
    "graduate geospatial data science course. Grade only the response text you "
    "are given. Be concise and specific. If the response is ambiguous, or you "
    "would not defend the score to a student, set manual_review to true and "
    "lower your confidence. Reply with JSON only."
)

USER_TEMPLATE = """Question / rubric item:
{question}

Maximum score: {max_score}

Rubric criteria:
{criteria}

Student response:
\"\"\"
{response}
\"\"\"

Reply with a JSON object with exactly these keys:
{{"score": number, "max_score": number, "confidence": number between 0 and 1,
  "feedback": string, "manual_review": boolean}}
"""


class QualitativeGrader(Protocol):
    """Interface the assignment graders depend on."""

    enabled: bool

    def grade(self, question: str, student_response: str, rubric: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass
class DisabledQualitativeGrader:
    """The default. Qualitative items stay with the human."""

    enabled: bool = False

    def grade(self, question: str, student_response: str, rubric: dict[str, Any]) -> dict[str, Any]:
        return {
            "score": 0.0,
            "max_score": float(rubric.get("max_score", 0)),
            "confidence": 0.0,
            "feedback": "LLM grading is disabled; this item needs manual grading.",
            "manual_review": True,
        }


class LLMQualitativeGrader:
    """Provider-independent grader.

    ``complete`` is any callable taking (system_prompt, user_prompt) and
    returning the model's text. Swapping providers means passing a different
    callable — the engine never imports a vendor SDK.
    """

    def __init__(
        self,
        complete: Callable[[str, str], str],
        review_threshold: float = DEFAULT_REVIEW_THRESHOLD,
        model_name: str = "unspecified",
    ):
        self.complete = complete
        self.review_threshold = review_threshold
        self.model_name = model_name
        self.enabled = True

    def grade(self, question: str, student_response: str, rubric: dict[str, Any]) -> dict[str, Any]:
        max_score = float(rubric.get("max_score", 0))
        criteria = rubric.get("criteria") or ["Correct interpretation of the result",
                                              "Reference to the data actually produced",
                                              "Clarity"]
        prompt = USER_TEMPLATE.format(
            question=question,
            max_score=max_score,
            criteria="\n".join(f"- {c}" for c in criteria),
            response=_redact(student_response)[:6000],
        )
        try:
            raw = self.complete(SYSTEM_PROMPT, prompt)
        except Exception as exc:
            return {
                "score": 0.0,
                "max_score": max_score,
                "confidence": 0.0,
                "feedback": f"LLM grading failed ({type(exc).__name__}); grade this by hand.",
                "manual_review": True,
                "error": str(exc)[:300],
            }

        parsed = _parse_json(raw)
        if parsed is None:
            return {
                "score": 0.0,
                "max_score": max_score,
                "confidence": 0.0,
                "feedback": "The model did not return usable JSON; grade this by hand.",
                "manual_review": True,
                "raw_response": str(raw)[:500],
            }

        score = max(0.0, min(float(parsed.get("score", 0.0)), max_score))
        confidence = max(0.0, min(float(parsed.get("confidence", 0.0)), 1.0))
        manual_review = bool(parsed.get("manual_review", False)) or confidence < self.review_threshold
        return {
            "score": score,
            "max_score": max_score,
            "confidence": confidence,
            "feedback": str(parsed.get("feedback", ""))[:2000],
            "manual_review": manual_review,
            "model": self.model_name,
        }


def _parse_json(raw: str) -> dict[str, Any] | None:
    if not raw:
        return None
    text = str(raw).strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


# Names, emails and student ids must not leave the machine (design.md §26).
_NAME_PATTERNS = (
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"),
    re.compile(r"\bstudent[_ ]?\d+\b", re.IGNORECASE),
    re.compile(r"\b\d{8,}\b"),
)


def _redact(text: str) -> str:
    for pattern in _NAME_PATTERNS:
        text = pattern.sub("[redacted]", text or "")
    return text


def anthropic_grader(
    model: str = "claude-sonnet-5",
    api_key: str | None = None,
    review_threshold: float = DEFAULT_REVIEW_THRESHOLD,
) -> QualitativeGrader:
    """Anthropic-backed grader, or a disabled one when it cannot be set up.

    This is a convenience wrapper, not a dependency: ``anthropic`` is imported
    lazily and its absence simply leaves qualitative grading manual.
    """
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return DisabledQualitativeGrader()
    try:
        import anthropic
    except ImportError:
        return DisabledQualitativeGrader()

    client = anthropic.Anthropic(api_key=api_key)

    def complete(system: str, user: str) -> str:
        message = client.messages.create(
            model=model,
            max_tokens=800,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in message.content if block.type == "text")

    return LLMQualitativeGrader(complete, review_threshold=review_threshold, model_name=model)


def build_grader(settings: dict[str, Any]) -> QualitativeGrader:
    """Construct a grader from UI settings."""
    if not settings.get("llm_enabled"):
        return DisabledQualitativeGrader()
    provider = (settings.get("llm_provider") or "anthropic").lower()
    threshold = float(settings.get("confidence_threshold", DEFAULT_REVIEW_THRESHOLD))
    if provider == "anthropic":
        return anthropic_grader(
            model=settings.get("llm_model", "claude-sonnet-5"),
            review_threshold=threshold,
        )
    return DisabledQualitativeGrader()
