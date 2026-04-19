from __future__ import annotations

from pathlib import Path

from evals.cases import CaseSpec


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUBRICS_ROOT = PROJECT_ROOT / "rubrics"


class RubricLoadError(FileNotFoundError):
    """Raised when a required checked-in rubric file is missing."""


def _safe_resolve(path: Path) -> Path:
    resolved = path.resolve()
    resolved.relative_to(PROJECT_ROOT.resolve())
    return resolved


def _read_rubric(path: Path) -> str:
    safe_path = _safe_resolve(path)
    if not safe_path.exists():
        raise RubricLoadError(f"rubric file not found: {safe_path}")
    return safe_path.read_text(encoding="utf-8").strip()


def load_rubric_text(metric_name: str, case: CaseSpec, config: dict) -> tuple[str, list[str]]:
    rubric_paths: list[Path] = []
    base_metric_path = RUBRICS_ROOT / "metrics" / f"{metric_name}.md"
    rubric_paths.append(base_metric_path)

    explicit_path = config.get("rubric_path")
    if explicit_path:
        rubric_paths.append(PROJECT_ROOT / str(explicit_path))
    else:
        case_path = RUBRICS_ROOT / "cases" / case.case_id / f"{metric_name}.md"
        if case_path.exists():
            rubric_paths.append(case_path)

    texts: list[str] = []
    labels: list[str] = []
    for path in rubric_paths:
        labels.append(str(_safe_resolve(path).relative_to(PROJECT_ROOT.resolve())))
        texts.append(_read_rubric(path))

    if not texts:
        raise RubricLoadError(f"no rubric text found for metric {metric_name}")

    return "\n\n".join(texts), labels

