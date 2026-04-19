from __future__ import annotations

from evals.cases import CaseSpec
from evals.scoring import MetricResult, register_metric
from evals.trace import Trace


@register_metric("quote_grounding")
def score_quote_grounding(case: CaseSpec, trace: Trace, config: dict, _context) -> MetricResult:
    extract_calls = trace.tool_calls("extract_quotes")
    require_extract_quotes = bool(config.get("require_extract_quotes"))

    if require_extract_quotes and not extract_calls:
        return MetricResult(
            name="quote_grounding",
            passed=False,
            score=0.0,
            summary="expected extract_quotes to be used",
            details={"case_id": case.case_id, "checked_quotes": 0, "violations": []},
        )

    violations: list[dict] = []
    checked_quotes = 0
    for call in extract_calls:
        source_text = str(call.args.get("text") or "")
        if not isinstance(call.result, list):
            violations.append(
                {
                    "tool_use_id": call.id,
                    "quote": None,
                    "reason": "result was not a JSON list",
                }
            )
            continue
        for quote in call.result:
            quote_text = str(quote)
            checked_quotes += 1
            if quote_text not in source_text:
                violations.append(
                    {
                        "tool_use_id": call.id,
                        "quote": quote_text,
                        "reason": "quote was not a verbatim substring",
                    }
                )

    passed = not violations
    summary = "all extracted quotes were verbatim" if passed else "some extracted quotes were paraphrased or hallucinated"
    return MetricResult(
        name="quote_grounding",
        passed=passed,
        score=1.0 if passed else 0.0,
        summary=summary,
        details={
            "case_id": case.case_id,
            "checked_quotes": checked_quotes,
            "violations": violations,
        },
    )
