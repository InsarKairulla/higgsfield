from __future__ import annotations

import json
import re
from typing import Any

from evals.judges.base import JudgeOutput, RubricItemAssessment


class JudgeSchemaError(ValueError):
    """Raised when a judge response is not valid structured JSON."""


_VERDICTS = {"pass", "fail", "mixed"}
_ASSESSMENTS = {"pass", "fail", "partial", "not_applicable"}


def _strip_code_fences(raw: str) -> str:
    value = raw.strip()
    if value.startswith("```"):
        value = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", value)
        value = re.sub(r"\n```$", "", value)
    return value.strip()


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise JudgeSchemaError(f"{label} must be a JSON object")
    return value


def _require_string(mapping: dict[str, Any], key: str, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise JudgeSchemaError(f"{label}.{key} must be a non-empty string")
    return value.strip()


def _require_bool(mapping: dict[str, Any], key: str, label: str) -> bool:
    value = mapping.get(key)
    if not isinstance(value, bool):
        raise JudgeSchemaError(f"{label}.{key} must be a boolean")
    return value


def _require_score(mapping: dict[str, Any], key: str, label: str) -> float:
    value = mapping.get(key)
    if not isinstance(value, (int, float)):
        raise JudgeSchemaError(f"{label}.{key} must be a number")
    score = float(value)
    if score < 0.0 or score > 1.0:
        raise JudgeSchemaError(f"{label}.{key} must be between 0.0 and 1.0")
    return score


def _require_string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise JudgeSchemaError(f"{label} must be a list")
    items: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise JudgeSchemaError(f"{label}[{index}] must be a string")
        if item.strip():
            items.append(item.strip())
    return items


def _parse_rubric_items(value: Any, label: str) -> list[RubricItemAssessment]:
    if not isinstance(value, list) or not value:
        raise JudgeSchemaError(f"{label} must be a non-empty list")
    items: list[RubricItemAssessment] = []
    for index, item in enumerate(value):
        entry = _require_object(item, f"{label}[{index}]")
        assessment = _require_string(entry, "assessment", f"{label}[{index}]")
        if assessment not in _ASSESSMENTS:
            raise JudgeSchemaError(
                f"{label}[{index}].assessment must be one of {sorted(_ASSESSMENTS)}"
            )
        items.append(
            RubricItemAssessment(
                item=_require_string(entry, "item", f"{label}[{index}]"),
                assessment=assessment,
                evidence=_require_string(entry, "evidence", f"{label}[{index}]"),
            )
        )
    return items


def parse_judge_response(raw_text: str, expected_metric_name: str) -> JudgeOutput:
    try:
        payload = json.loads(_strip_code_fences(raw_text))
    except json.JSONDecodeError as exc:
        raise JudgeSchemaError("judge response was not valid JSON") from exc

    data = _require_object(payload, "response")
    metric_name = _require_string(data, "metric_name", "response")
    if metric_name != expected_metric_name:
        raise JudgeSchemaError(
            f"response.metric_name must equal {expected_metric_name!r}, got {metric_name!r}"
        )

    verdict = _require_string(data, "verdict", "response")
    if verdict not in _VERDICTS:
        raise JudgeSchemaError(f"response.verdict must be one of {sorted(_VERDICTS)}")

    return JudgeOutput(
        metric_name=metric_name,
        verdict=verdict,
        passed=_require_bool(data, "passed", "response"),
        score=_require_score(data, "score", "response"),
        rationale=_require_string(data, "rationale", "response"),
        rubric_items=_parse_rubric_items(data.get("rubric_items"), "response.rubric_items"),
        failure_modes_detected=_require_string_list(
            data.get("failure_modes_detected"), "response.failure_modes_detected"
        ),
        raw_response=raw_text,
    )

