from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class CaseLoadError(ValueError):
    """Raised when a case file does not match the expected shape."""


@dataclass(frozen=True)
class MetricSpec:
    name: str
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CaseSpec:
    case_id: str
    input: str
    description: str = ""
    tags: tuple[str, ...] = ()
    metrics: tuple[MetricSpec, ...] = ()
    notes: dict[str, str] = field(default_factory=dict)
    source_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.case_id,
            "input": self.input,
            "description": self.description,
            "tags": list(self.tags),
            "metrics": [
                {"name": metric.name, "config": metric.config}
                for metric in self.metrics
            ],
            "notes": self.notes,
            "source_path": str(self.source_path) if self.source_path else None,
        }


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CaseLoadError(f"{label} must be a mapping")
    return value


def _require_string(mapping: dict[str, Any], key: str, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CaseLoadError(f"{label}.{key} must be a non-empty string")
    return value.strip()


def _string_list(value: Any, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise CaseLoadError(f"{label} must be a list of strings")
    items: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise CaseLoadError(f"{label}[{index}] must be a non-empty string")
        items.append(item.strip())
    return tuple(items)


def load_case(path: str | Path) -> CaseSpec:
    case_path = Path(path)
    raw = yaml.safe_load(case_path.read_text(encoding="utf-8")) or {}
    case_data = _require_mapping(raw, str(case_path))

    expected_behavior = _require_mapping(
        case_data.get("expected_behavior"), f"{case_path}.expected_behavior"
    )
    metrics_raw = expected_behavior.get("metrics")
    if not isinstance(metrics_raw, list) or not metrics_raw:
        raise CaseLoadError(f"{case_path}.expected_behavior.metrics must be a non-empty list")

    metrics: list[MetricSpec] = []
    for index, metric_raw in enumerate(metrics_raw):
        metric_data = _require_mapping(
            metric_raw, f"{case_path}.expected_behavior.metrics[{index}]"
        )
        name = _require_string(
            metric_data, "name", f"{case_path}.expected_behavior.metrics[{index}]"
        )
        config = metric_data.get("config") or {}
        if not isinstance(config, dict):
            raise CaseLoadError(
                f"{case_path}.expected_behavior.metrics[{index}].config must be a mapping"
            )
        metrics.append(MetricSpec(name=name, config=config))

    notes_raw = case_data.get("notes") or {}
    if isinstance(notes_raw, str):
        notes = {"summary": notes_raw}
    elif isinstance(notes_raw, dict):
        notes = {str(key): str(value) for key, value in notes_raw.items()}
    else:
        raise CaseLoadError(f"{case_path}.notes must be a string or mapping")

    return CaseSpec(
        case_id=_require_string(case_data, "id", str(case_path)),
        input=_require_string(case_data, "input", str(case_path)),
        description=str(case_data.get("description") or "").strip(),
        tags=_string_list(case_data.get("tags"), f"{case_path}.tags"),
        metrics=tuple(metrics),
        notes=notes,
        source_path=case_path,
    )


def load_cases(case_dir: str | Path = "cases") -> list[CaseSpec]:
    base_dir = Path(case_dir)
    case_paths = [
        path for path in sorted(base_dir.glob("*.yaml")) if path.name != "schema.yaml"
    ]
    return [load_case(path) for path in case_paths]


def find_case(case_id: str, case_dir: str | Path = "cases") -> CaseSpec:
    for case in load_cases(case_dir):
        if case.case_id == case_id:
            return case
    raise CaseLoadError(f"unknown case id: {case_id}")
