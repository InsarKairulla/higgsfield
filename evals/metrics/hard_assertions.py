from __future__ import annotations

from evals.assertions import evaluate_assertions
from evals.cases import CaseSpec
from evals.scoring import MetricResult, register_metric
from evals.trace import Trace


@register_metric("hard_assertions")
def score_hard_assertions(case: CaseSpec, trace: Trace, config: dict, _context) -> MetricResult:
    assertions = config.get("assertions") or []
    outcomes = evaluate_assertions(trace, assertions)
    passed = bool(outcomes) and all(outcome.passed for outcome in outcomes)
    summary = "all hard assertions passed" if passed else next(
        (outcome.message for outcome in outcomes if not outcome.passed),
        "no hard assertions configured",
    )
    return MetricResult(
        name="hard_assertions",
        passed=passed,
        score=1.0 if passed else 0.0,
        summary=summary,
        details={
            "case_id": case.case_id,
            "assertions": [outcome.to_dict() for outcome in outcomes],
        },
    )
