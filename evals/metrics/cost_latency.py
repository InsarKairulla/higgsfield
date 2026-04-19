from __future__ import annotations

from evals.cases import CaseSpec
from evals.scoring import MetricResult, register_metric
from evals.trace import Trace


def _build_summary(checks: list[dict]) -> tuple[bool, str]:
    for check in checks:
        if not check["passed"]:
            return False, check["message"]
    return True, "cost and latency stayed within configured bounds"


@register_metric("cost_latency")
def score_cost_latency(case: CaseSpec, trace: Trace, config: dict, _context) -> MetricResult:
    checks: list[dict] = []

    max_wall_time_ms = config.get("max_wall_time_ms")
    if max_wall_time_ms is not None:
        actual = trace.wall_time_ms
        limit = int(max_wall_time_ms)
        checks.append(
            {
                "name": "max_wall_time_ms",
                "passed": actual <= limit,
                "message": f"wall time {actual}ms <= {limit}ms"
                if actual <= limit
                else f"wall time {actual}ms exceeded {limit}ms",
                "actual": actual,
            }
        )

    max_cost_usd = config.get("max_cost_usd")
    if max_cost_usd is not None:
        actual = trace.cost_usd
        limit = float(max_cost_usd)
        checks.append(
            {
                "name": "max_cost_usd",
                "passed": actual <= limit,
                "message": f"cost ${actual:.4f} <= ${limit:.4f}"
                if actual <= limit
                else f"cost ${actual:.4f} exceeded ${limit:.4f}",
                "actual": actual,
            }
        )

    max_total_tokens = config.get("max_total_tokens")
    if max_total_tokens is not None:
        tokens = trace.total_tokens
        actual = tokens["input"] + tokens["output"]
        limit = int(max_total_tokens)
        checks.append(
            {
                "name": "max_total_tokens",
                "passed": actual <= limit,
                "message": f"total tokens {actual} <= {limit}"
                if actual <= limit
                else f"total tokens {actual} exceeded {limit}",
                "actual": actual,
            }
        )

    passed, summary = _build_summary(checks or [{"passed": True, "message": "no cost checks configured"}])
    return MetricResult(
        name="cost_latency",
        passed=passed,
        score=1.0 if passed else 0.0,
        summary=summary,
        details={"case_id": case.case_id, "checks": checks},
    )
