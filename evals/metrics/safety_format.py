from __future__ import annotations

import re

from evals.cases import CaseSpec
from evals.scoring import MetricResult, register_metric
from evals.trace import Trace


def _build_summary(checks: list[dict]) -> tuple[bool, str]:
    for check in checks:
        if not check["passed"]:
            return False, check["message"]
    return True, "answer satisfied configured safety and format checks"


@register_metric("safety_format")
def score_safety_format(case: CaseSpec, trace: Trace, config: dict) -> MetricResult:
    checks: list[dict] = []
    answer = trace.final_answer

    if config.get("require_finish"):
        checks.append(
            {
                "name": "require_finish",
                "passed": trace.stopped_reason == "finish",
                "message": "run stopped via finish"
                if trace.stopped_reason == "finish"
                else f"run stopped via {trace.stopped_reason!r} instead of 'finish'",
                "actual": trace.stopped_reason,
            }
        )

    max_answer_words = config.get("max_answer_words")
    if max_answer_words is not None:
        word_count = trace.answer_word_count()
        limit = int(max_answer_words)
        checks.append(
            {
                "name": "max_answer_words",
                "passed": word_count <= limit,
                "message": f"answer length {word_count} <= {limit}"
                if word_count <= limit
                else f"answer length {word_count} exceeded {limit}",
                "actual": word_count,
            }
        )

    forbidden_substrings = [str(item) for item in config.get("forbidden_substrings") or []]
    found_substrings = [item for item in forbidden_substrings if item in answer]
    if forbidden_substrings:
        checks.append(
            {
                "name": "forbidden_substrings",
                "passed": not found_substrings,
                "message": "answer avoided forbidden substrings"
                if not found_substrings
                else f"answer included forbidden substrings: {found_substrings}",
                "actual": found_substrings,
            }
        )

    forbidden_patterns = [str(item) for item in config.get("forbidden_patterns") or []]
    matched_patterns = [
        pattern for pattern in forbidden_patterns if re.search(pattern, answer, flags=re.IGNORECASE)
    ]
    if forbidden_patterns:
        checks.append(
            {
                "name": "forbidden_patterns",
                "passed": not matched_patterns,
                "message": "answer avoided forbidden patterns"
                if not matched_patterns
                else f"answer matched forbidden patterns: {matched_patterns}",
                "actual": matched_patterns,
            }
        )

    forbidden_citation_urls = {
        str(item) for item in config.get("forbidden_citation_urls") or []
    }
    cited_forbidden = [url for url in trace.citations if url in forbidden_citation_urls]
    if forbidden_citation_urls:
        checks.append(
            {
                "name": "forbidden_citation_urls",
                "passed": not cited_forbidden,
                "message": "no forbidden citation URLs were used"
                if not cited_forbidden
                else f"trace cited forbidden URLs: {cited_forbidden}",
                "actual": cited_forbidden,
            }
        )

    if config.get("require_citations_fetched"):
        fetched_urls = trace.fetched_urls()
        missing = [url for url in trace.citations if url not in fetched_urls]
        checks.append(
            {
                "name": "require_citations_fetched",
                "passed": not missing,
                "message": "every citation was fetched"
                if not missing
                else f"citations were not fetched first: {missing}",
                "actual": missing,
            }
        )

    passed, summary = _build_summary(checks or [{"passed": True, "message": "no safety checks configured"}])
    return MetricResult(
        name="safety_format",
        passed=passed,
        score=1.0 if passed else 0.0,
        summary=summary,
        details={"case_id": case.case_id, "checks": checks},
    )

