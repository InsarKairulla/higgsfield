from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from evals.cases import CaseSpec
from evals.trace import Trace


@dataclass
class MetricResult:
    name: str
    passed: bool
    score: float
    summary: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "score": self.score,
            "summary": self.summary,
            "details": self.details,
        }


@dataclass
class CaseScore:
    case_id: str
    passed: bool
    metrics: list[MetricResult]

    def failed_metrics(self) -> list[MetricResult]:
        return [metric for metric in self.metrics if not metric.passed]

    def failure_reason(self) -> str:
        for metric in self.metrics:
            if not metric.passed:
                return metric.summary
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "failure_reason": self.failure_reason(),
            "metrics": [metric.to_dict() for metric in self.metrics],
        }


MetricFn = Callable[[CaseSpec, Trace, dict[str, Any]], MetricResult]
_METRIC_REGISTRY: dict[str, MetricFn] = {}


def register_metric(name: str) -> Callable[[MetricFn], MetricFn]:
    def decorator(func: MetricFn) -> MetricFn:
        _METRIC_REGISTRY[name] = func
        return func

    return decorator


def get_metric(name: str) -> MetricFn:
    from evals.metrics import load_builtin_metrics

    load_builtin_metrics()
    try:
        return _METRIC_REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"unknown metric plugin: {name}") from exc


def score_case(case: CaseSpec, trace: Trace) -> CaseScore:
    results: list[MetricResult] = []
    for metric in case.metrics:
        scorer = get_metric(metric.name)
        results.append(scorer(case, trace, metric.config))
    return CaseScore(
        case_id=case.case_id,
        passed=all(result.passed for result in results),
        metrics=results,
    )
